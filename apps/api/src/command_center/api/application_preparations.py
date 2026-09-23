"""Owned application preparation endpoints; slow generation remains a durable agent job."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select

from command_center.api import schemas as s
from command_center.api.agents import available_profile
from command_center.api.browser import Device
from command_center.api.browser_contracts import FieldId, FieldValue, HistoryTargets, ResumeFile
from command_center.api.workspace import Database, WriteKey, serialize, write
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity, Identity
from command_center.db.agents import AgentRun
from command_center.db.application_preparations import ApplicationPreparation
from command_center.db.applications import ApplicationTrack
from command_center.db.artifacts import ArtifactVersion
from command_center.db.browser import BrowserSnapshot
from command_center.db.conversations import AgentSession
from command_center.db.idempotency import RequestReceipt

router = APIRouter(prefix="/api/v1/browser", tags=["application-preparation"])


class JobContextCreate(s.Contract):
    job_title: str = Field(default="", max_length=300)
    company_name: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=30000)
    extraction_method: Literal["json_ld", "semantic_dom", "manual"]
    truncated: bool = False


class PreparationCreate(s.Contract):
    cover_letter_version_id: UUID | None = None
    opportunity_id: UUID | None = None
    resume_version_id: UUID | None = None
    continue_preparation_id: UUID | None = None
    continue_on_new_page: bool = False
    job_context: JobContextCreate | None = None


class PreparationRevision(s.Contract):
    cover_letter_version_id: UUID | None = None
    cover_letter_upload_fields: list[FieldId] = Field(default_factory=list, max_length=10)
    expected_version_id: UUID
    fields: dict[FieldId, FieldValue] = Field(default_factory=dict, max_length=100)
    resume_version_id: UUID | None
    replace_fields: list[FieldId] = Field(default_factory=list, max_length=100)
    upload_fields: list[FieldId] = Field(default_factory=list, max_length=10)
    remember_fields: list[FieldId] = Field(default_factory=list, max_length=100)


class AutofillRequest(s.Contract):
    expected_version_id: UUID
    attach_resume: bool = True
    attach_cover_letter: bool = False


class PreparationAnswer(s.Contract):
    field_id: FieldId
    value: str = Field(min_length=1, max_length=5000)
    fact_revision_ids: list[UUID] = Field(min_length=1, max_length=20)
    source_version_ids: list[UUID] = Field(default_factory=list, max_length=20)


class PreparationSuggestions(s.Contract):
    expected_version_id: UUID
    answers: list[PreparationAnswer] = Field(min_length=1, max_length=20)


class ApplicationEvidenceRead(s.Contract):
    fact_id: UUID
    revision_id: UUID
    value: str
    context: str | None
    source_version_id: UUID | None


class PreparedFieldRead(s.Contract):
    field_id: str
    status: Literal["suggested", "needs_input", "preserved", "unsupported"]
    value: str | None
    reason: str
    evidence: list[ApplicationEvidenceRead]


class ApplicationPreparationRead(s.Contract):
    id: UUID
    snapshot_id: UUID
    task_id: UUID
    opportunity_id: UUID | None
    artifact_id: UUID
    version_id: UUID
    version: int
    resume: ResumeFile | None
    cover_letter: ResumeFile | None = None
    cover_letter_upload_fields: list[str] = Field(default_factory=list)
    replace_fields: list[str]
    upload_fields: list[str]
    history_targets: HistoryTargets = Field(default_factory=HistoryTargets)
    fields: list[PreparedFieldRead]
    created_at: datetime


class PreparationGenerationRead(s.Contract):
    conversation_id: UUID
    run_id: UUID


class PreparationGenerationStatus(s.Contract):
    conversation_id: UUID | None
    run_id: UUID | None
    state: Literal["idle", "queued", "running", "completed", "failed", "cancelled"]
    error_code: str | None


def preparation_request_payload(body: s.Contract) -> dict[str, Any]:
    """Keep earlier receipt hashes stable when no additive choice is made."""
    payload = body.model_dump(mode="json")
    for name in (
        "cover_letter_version_id",
        "cover_letter_upload_fields",
        "attach_cover_letter",
        "continue_on_new_page",
    ):
        if not payload.get(name):
            payload.pop(name, None)
    return payload


def human_only(identity: Identity) -> None:
    if identity.run_id is not None:
        raise HTTPException(403, "Application review and generation require the human owner")


@router.get("/snapshots/{snapshot_id}")
def snapshot_detail(snapshot_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    human_only(identity)
    snapshot = db.scalar(
        select(BrowserSnapshot).where(
            BrowserSnapshot.id == snapshot_id,
            BrowserSnapshot.owner_id == identity.id,
        )
    )
    if snapshot is None:
        raise HTTPException(404, "Form snapshot not found")
    return serialize(snapshot)


@router.get(
    "/snapshots/{snapshot_id}/preparation", response_model=ApplicationPreparationRead | None
)
def snapshot_preparation(
    snapshot_id: UUID,
    identity: CurrentIdentity,
    db: Database,
) -> ApplicationPreparationRead | None:
    snapshot_detail(snapshot_id, identity, db)
    preparation = db.scalar(
        select(ApplicationPreparation)
        .where(
            ApplicationPreparation.snapshot_id == snapshot_id,
            ApplicationPreparation.owner_id == identity.id,
        )
        .order_by(ApplicationPreparation.created_at.desc(), ApplicationPreparation.id.desc())
        .limit(1)
    )
    return preparation_read(preparation) if preparation else None


def preparation_read(
    preparation: ApplicationPreparation,
    version: ArtifactVersion | None = None,
) -> ApplicationPreparationRead:
    version = version or preparation.current_version()
    payload: dict[str, Any] | None = version.payload
    assert payload is not None
    return ApplicationPreparationRead.model_validate(
        {
            "id": preparation.id,
            "snapshot_id": preparation.snapshot_id,
            "task_id": preparation.task_id,
            "opportunity_id": preparation.opportunity_id,
            "artifact_id": preparation.artifact_id,
            "version_id": version.id,
            "version": version.version,
            "resume": payload["resume"],
            "cover_letter": payload.get("cover_letter"),
            "cover_letter_upload_fields": payload.get("cover_letter_upload_fields", []),
            "replace_fields": payload["replace_fields"],
            "upload_fields": payload["upload_fields"],
            "history_targets": payload.get("history_targets", {}),
            "fields": [
                {key: field[key] for key in PreparedFieldRead.model_fields}
                for field in payload["fields"]
            ],
            "created_at": preparation.created_at,
        }
    )


def owned_preparation(
    db: Database,
    record_id: UUID,
    owner_id: UUID,
    *,
    device_id: UUID | None = None,
    run_id: UUID | None = None,
) -> ApplicationPreparation:
    statement = select(ApplicationPreparation).where(
        ApplicationPreparation.id == record_id, ApplicationPreparation.owner_id == owner_id
    )
    if device_id:
        statement = statement.join(
            BrowserSnapshot, BrowserSnapshot.id == ApplicationPreparation.snapshot_id
        ).where(BrowserSnapshot.device_id == device_id)
    preparation = db.scalar(statement)
    if preparation is None:
        raise HTTPException(404, "Application preparation not found")
    if run_id:
        scoped = db.scalar(
            select(AgentRun.id)
            .join(AgentSession, AgentSession.id == AgentRun.session_id)
            .where(
                AgentRun.id == run_id,
                AgentRun.owner_id == owner_id,
                AgentSession.task_id == preparation.task_id,
            )
        )
        if scoped is None:
            raise HTTPException(403, "This preparation is outside the agent's task conversation")
    return preparation


def create_preparation(
    snapshot_id: UUID,
    body: PreparationCreate,
    owner_id: UUID,
    db: Database,
    key: UUID,
    request: Request,
    device_id: UUID | None = None,
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        snapshot = db.scalar(
            select(BrowserSnapshot).where(
                BrowserSnapshot.id == snapshot_id, BrowserSnapshot.owner_id == owner_id
            )
        )
        if snapshot is None or (device_id and snapshot.device_id != device_id):
            raise HTTPException(404, "Form snapshot not found")
        preparation = ApplicationPreparation.create(
            db,
            record_id=record_id,
            owner_id=owner_id,
            snapshot=snapshot,
            opportunity_id=body.opportunity_id,
            resume_version_id=body.resume_version_id,
            cover_letter_version_id=body.cover_letter_version_id,
            use_default_resume="resume_version_id" not in body.model_fields_set,
            request_id=UUID(request.state.request_id),
            continue_preparation_id=body.continue_preparation_id,
            continue_on_new_page=body.continue_on_new_page,
            job_context=body.job_context.model_dump() if body.job_context else None,
        )
        db.flush()
        return preparation_read(preparation).model_dump(mode="json")

    # Omitted resume selection differs from an explicitly empty selection.
    selection_mode = "explicit" if "resume_version_id" in body.model_fields_set else "default"
    return RequestReceipt.execute(
        db,
        actor_id=owner_id,
        key=key,
        operation=(
            f"POST:application-preparation:{snapshot_id}:{device_id or 'human'}:{selection_mode}"
        ),
        payload=preparation_request_payload(body),
        change=change,
    )


@router.post(
    "/snapshots/{snapshot_id}/preparations",
    response_model=ApplicationPreparationRead,
    status_code=201,
)
def prepare(
    snapshot_id: UUID,
    body: PreparationCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_only(identity)
    return create_preparation(snapshot_id, body, identity.id, db, key, request)


@router.post(
    "/device/snapshots/{snapshot_id}/preparations",
    response_model=ApplicationPreparationRead,
    status_code=201,
)
def device_prepare(
    snapshot_id: UUID,
    body: PreparationCreate,
    device: Device,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return create_preparation(snapshot_id, body, device.owner_id, db, key, request, device.id)


@router.get("/preparations/{record_id}", response_model=ApplicationPreparationRead)
def preparation_detail(
    record_id: UUID, identity: CurrentIdentity, db: Database
) -> ApplicationPreparationRead:
    human_only(identity)
    return preparation_read(owned_preparation(db, record_id, identity.id))


@router.get("/device/preparations/{record_id}", response_model=ApplicationPreparationRead)
def device_preparation_detail(
    record_id: UUID, device: Device, db: Database
) -> ApplicationPreparationRead:
    return preparation_read(owned_preparation(db, record_id, device.owner_id, device_id=device.id))


def revise_preparation(
    record_id: UUID,
    body: PreparationRevision,
    owner_id: UUID,
    db: Database,
    key: UUID,
    request: Request,
    device_id: UUID | None = None,
) -> dict[str, Any]:
    def change(version_id: UUID) -> dict[str, Any]:
        preparation = owned_preparation(db, record_id, owner_id, device_id=device_id)
        preparation.revise(
            expected_version_id=body.expected_version_id,
            fields=body.fields,
            resume_version_id=body.resume_version_id,
            cover_letter_version_id=body.cover_letter_version_id,
            replace_fields=body.replace_fields,
            upload_fields=body.upload_fields,
            cover_letter_upload_fields=body.cover_letter_upload_fields,
            remember_fields=body.remember_fields,
            version_id=version_id,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return preparation_read(preparation).model_dump(mode="json")

    return RequestReceipt.execute(
        db,
        actor_id=owner_id,
        key=key,
        operation=f"POST:application-revision:{record_id}:{device_id or 'human'}",
        payload=preparation_request_payload(body),
        change=change,
    )


@router.post(
    "/preparations/{record_id}/revisions",
    response_model=ApplicationPreparationRead,
    status_code=201,
)
def revise(
    record_id: UUID,
    body: PreparationRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_only(identity)
    return revise_preparation(record_id, body, identity.id, db, key, request)


@router.post(
    "/device/preparations/{record_id}/revisions",
    response_model=ApplicationPreparationRead,
    status_code=201,
)
def device_revise(
    record_id: UUID,
    body: PreparationRevision,
    device: Device,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return revise_preparation(record_id, body, device.owner_id, db, key, request, device.id)


@router.post(
    "/device/preparations/{record_id}/autofill",
    response_model=ApplicationPreparationRead,
    status_code=201,
)
def device_autofill(
    record_id: UUID,
    body: AutofillRequest,
    device: Device,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(version_id: UUID) -> dict[str, Any]:
        preparation = owned_preparation(db, record_id, device.owner_id, device_id=device.id)
        preparation.autofill(
            expected_version_id=body.expected_version_id,
            attach_resume=body.attach_resume,
            attach_cover_letter=body.attach_cover_letter,
            version_id=version_id,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return preparation_read(preparation).model_dump(mode="json")

    return RequestReceipt.execute(
        db,
        actor_id=device.owner_id,
        key=key,
        operation=f"POST:application-autofill:{record_id}:{device.id}",
        payload=preparation_request_payload(body),
        change=change,
    )


def generate_answers(
    record_id: UUID,
    owner_id: UUID,
    db: Database,
    key: UUID,
    request: Request,
    device_id: UUID | None = None,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        preparation = owned_preparation(db, record_id, owner_id, device_id=device_id)
        profile, revision = available_profile(request, "application")
        conversation_id, run_id = preparation.request_generation(
            configuration=profile.model_dump(mode="json"),
            revision=revision,
            request_id=UUID(request.state.request_id),
        )
        return {"conversation_id": str(conversation_id), "run_id": str(run_id)}

    return write(
        db,
        owner_id,
        key,
        f"POST:application-generate:{record_id}:{device_id or 'human'}",
        s.Contract(),
        change,
    )


@router.post(
    "/preparations/{record_id}/generate", response_model=PreparationGenerationRead, status_code=202
)
def generate(
    record_id: UUID, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    human_only(identity)
    return generate_answers(record_id, identity.id, db, key, request)


@router.post(
    "/device/preparations/{record_id}/generate",
    response_model=PreparationGenerationRead,
    status_code=202,
)
def device_generate(
    record_id: UUID, device: Device, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    return generate_answers(record_id, device.owner_id, db, key, request, device.id)


@router.get("/preparations/{record_id}/context")
def context(
    record_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> dict[str, Any]:
    preparation = owned_preparation(db, record_id, identity.id, run_id=identity.run_id)
    snapshot = db.get(BrowserSnapshot, preparation.snapshot_id)
    assert snapshot is not None
    version = preparation.current_version()
    payload: dict[str, Any] = version.payload or {}
    application = db.get(ApplicationTrack, preparation.task_id)
    job_version = application.current_context_version(db) if application else None
    job_payload = (job_version.payload or {}) if job_version else {}
    answers = {field["field_id"]: field for field in payload["fields"]}
    items = []
    for field in snapshot.fields[offset : offset + limit]:
        answer = answers[field["id"]]
        items.append(
            {
                "field": {
                    **field,
                    "options": field["options"][:20],
                    "option_labels": {
                        value: field.get("option_labels", {}).get(value, value)
                        for value in field["options"][:20]
                    },
                    "options_complete": len(field["options"]) <= 20,
                },
                "answer": {
                    key: answer[key] for key in ("field_id", "status", "value", "reason", "origin")
                },
                "fact_revision_ids": [evidence["revision_id"] for evidence in answer["evidence"]],
            }
        )
    return {
        "preparation_id": str(preparation.id),
        "version_id": str(version.id),
        "task_id": str(preparation.task_id),
        "opportunity_id": str(preparation.opportunity_id) if preparation.opportunity_id else None,
        "page_url": snapshot.page_url,
        "title": snapshot.title,
        "job_context": {
            "artifact_id": str(job_version.artifact_id),
            "version_id": str(job_version.id),
            "version": job_version.version,
            "job_title": job_payload["job_title"],
            "company_name": job_payload["company_name"],
            "text_length": len(str(job_payload["text"])),
            "truncated": job_payload["truncated"],
        }
        if job_version
        else None,
        "items": items,
        "offset": offset,
        "limit": limit,
        "total": len(snapshot.fields),
        "next_offset": offset + len(items) if offset + len(items) < len(snapshot.fields) else None,
    }


def generation_status(db: Database, preparation: ApplicationPreparation) -> dict[str, Any]:
    run = db.scalar(
        select(AgentRun)
        .join(AgentSession, AgentSession.id == AgentRun.session_id)
        .where(
            AgentSession.task_id == preparation.task_id, AgentRun.owner_id == preparation.owner_id
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    return {
        "conversation_id": run.session_id if run else None,
        "run_id": run.id if run else None,
        "state": run.state if run else "idle",
        "error_code": run.error_code if run else None,
    }


@router.get("/preparations/{record_id}/generation", response_model=PreparationGenerationStatus)
def generation_detail(record_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    human_only(identity)
    return generation_status(db, owned_preparation(db, record_id, identity.id))


@router.get(
    "/device/preparations/{record_id}/generation", response_model=PreparationGenerationStatus
)
def device_generation_detail(record_id: UUID, device: Device, db: Database) -> dict[str, Any]:
    return generation_status(
        db, owned_preparation(db, record_id, device.owner_id, device_id=device.id)
    )


@router.post(
    "/preparations/{record_id}/suggestions",
    response_model=ApplicationPreparationRead,
    status_code=201,
)
def suggest(
    record_id: UUID,
    body: PreparationSuggestions,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    if identity.run_id is None:
        raise HTTPException(403, "Use human review for manual answers")

    def change(version_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        preparation = owned_preparation(db, record_id, identity.id, run_id=identity.run_id)
        preparation.suggest(
            expected_version_id=body.expected_version_id,
            proposals=[answer.model_dump(mode="json") for answer in body.answers],
            version_id=version_id,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return preparation_read(preparation).model_dump(mode="json")

    return write(db, identity.id, key, f"POST:application-suggestions:{record_id}", body, change)
