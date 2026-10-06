"""Application CSV intake and automation-run HTTP boundary."""

from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select

from command_center.api import schemas as s
from command_center.api.workspace import Database, serialize, write
from command_center.core.identity import CurrentIdentity
from command_center.db.adapters import load_adapter_definition
from command_center.db.applications_automation import (
    MAX_IMPORT_BYTES,
    Application,
    ApplicationImport,
    AutomationRun,
)
from command_center.db.errors import RecordConflict
from command_center.db.job_identity import posting_identity

router = APIRouter(prefix="/api/v1/applications-automation", tags=["applications-automation"])


def _csv_text(data: bytes) -> str:
    """Decode one bounded CSV upload, rejecting control bytes and NUL."""
    if not 0 < len(data) <= MAX_IMPORT_BYTES:
        raise HTTPException(413, "CSV uploads accept between 1 byte and 5 MiB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "The CSV must be UTF-8 encoded") from None
    if "\x00" in text:
        raise HTTPException(422, "The CSV cannot contain NUL bytes")
    for char in text:
        if ord(char) < 32 and char not in "\t\n\r":
            raise HTTPException(422, "The CSV cannot contain control characters")
    return text


def _owned_application(db: Any, record_id: UUID, actor_id: UUID, *, lock: bool) -> Application:
    statement = select(Application).where(
        Application.id == record_id,
        Application.owner_id == actor_id,
    )
    if lock:
        statement = statement.with_for_update()
    application = db.scalar(statement)
    if application is None:
        raise HTTPException(404, "Application not found")
    return cast(Application, application)


@router.post("/csv", status_code=201)
def upload_csv(
    file: UploadFile,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
) -> dict[str, Any]:
    """Parse one CSV batch synchronously and create normalized application rows."""
    text = _csv_text(file.file.read(MAX_IMPORT_BYTES + 1))
    # The Idempotency-Key identifies the batch: a retried upload with the same
    # key deterministically REPLACES nothing — replay returns the first batch,
    # because uuid5 keys both the batch and its rows off this id.
    key_header = request.headers.get("Idempotency-Key")
    try:
        key = UUID(key_header) if key_header else uuid4()
    except ValueError:
        raise HTTPException(422, "Idempotency-Key must be a UUID") from None
    request_id = UUID(request.state.request_id)
    import_id = uuid5(key, "application-import")
    existing = db.scalar(
        select(ApplicationImport).where(
            ApplicationImport.id == import_id, ApplicationImport.owner_id == identity.id
        )
    )
    if existing is not None:
        return {
            "id": str(existing.id),
            "filename": existing.filename,
            "row_count": existing.row_count,
            "accepted_count": existing.accepted_count,
            "rejected_count": existing.rejected_count,
            "reject_reasons": existing.reject_reasons,
        }
    try:
        batch = ApplicationImport.create_from_upload(
            db,
            import_id=import_id,
            owner_id=identity.id,
            filename=file.filename or "applications.csv",
            text=text,
            request_id=request_id,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {
        "id": str(batch.id),
        "filename": batch.filename,
        "row_count": batch.row_count,
        "accepted_count": batch.accepted_count,
        "rejected_count": batch.rejected_count,
        "reject_reasons": batch.reject_reasons,
    }


@router.get("/imports")
def imports(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ApplicationImport)
        .where(ApplicationImport.owner_id == identity.id)
        .order_by(ApplicationImport.created_at.desc())
        .limit(50)
    ).all()
    return [serialize(row) for row in rows]


@router.get("/imports/{import_id}")
def get_import(import_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    batch = db.scalar(
        select(ApplicationImport).where(
            ApplicationImport.id == import_id, ApplicationImport.owner_id == identity.id
        )
    )
    if batch is None:
        raise HTTPException(404, "Import not found")
    return serialize(batch)


@router.get("/applications")
def applications(
    identity: CurrentIdentity,
    db: Database,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    statement = select(Application).where(Application.owner_id == identity.id)
    if status is not None:
        statement = statement.where(Application.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(Application.created_at.desc(), Application.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/applications/{application_id}")
def get_application(
    application_id: UUID, identity: CurrentIdentity, db: Database
) -> dict[str, Any]:
    application = _owned_application(db, application_id, identity.id, lock=False)
    data = serialize(application)
    if application.last_run_id is not None:
        run = db.get(AutomationRun, application.last_run_id)
        if run is not None:
            data["last_run"] = serialize(run)
    return data


class SubmitAuthorizationCreate(s.Contract):
    """Empty body; the explicit action itself is the authorization."""


class AutomationRunCreate(s.Contract):
    mode: Literal["fill_only", "submit"] = "fill_only"


@router.post("/applications/{application_id}/authorization", status_code=201)
def authorize(
    application_id: UUID,
    body: SubmitAuthorizationCreate,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
) -> dict[str, Any]:
    """Stamp explicit submission authorization; audited in the same transaction."""
    application = _owned_application(db, application_id, identity.id, lock=True)
    request_id = UUID(request.state.request_id)

    def change(record_id: UUID) -> dict[str, Any]:
        application.authorize(request_id=request_id)
        db.flush()
        return serialize(application)

    return write(
        db,
        identity.id,
        request_id,
        "POST:applications:authorization",
        body,
        change,
    )


@router.delete("/applications/{application_id}/authorization")
def revoke(
    application_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
) -> dict[str, Any]:
    application = _owned_application(db, application_id, identity.id, lock=True)
    application.revoke_authorization(request_id=UUID(request.state.request_id))
    db.flush()
    return serialize(application)


@router.post("/applications/{application_id}/runs", status_code=201)
def create_run(
    application_id: UUID,
    body: AutomationRunCreate,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
) -> dict[str, Any]:
    """Queue one automation run; submission mode requires an authorization stamp."""
    application = _owned_application(db, application_id, identity.id, lock=True)
    if application.status not in {"ready_to_run", "ready_for_review", "failed"}:
        raise HTTPException(409, "This application cannot start a run now")
    identity_value = posting_identity(application.job_url)
    if identity_value is None or identity_value["platform"] != "greenhouse":
        raise HTTPException(422, "Only Greenhouse postings are supported in this release")
    adapter = load_adapter_definition("greenhouse")
    try:
        run = AutomationRun.enqueue(
            db,
            application=application,
            mode=body.mode,
            adapter_platform="greenhouse",
            adapter_revision=adapter.revision,
            request_id=UUID(request.state.request_id),
        )
    except RecordConflict as exc:
        raise HTTPException(409, str(exc)) from None
    db.flush()
    return serialize(run)
