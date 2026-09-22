"""Owned exact-version PDF export endpoints."""

import logging
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.api import schemas as s
from command_center.api.research_executions import enforce_task_scope
from command_center.api.workspace import Database, WriteKey, check_version, write
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.pdf_exports import PdfExport

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["pdf-exports"])


class PdfExportCreate(s.Contract):
    format: Literal["pdf"] = "pdf"
    task_id: UUID | None = None


class ExportVersionRead(s.ResponseContract):
    artifact_id: UUID
    artifact_title: str
    version_id: UUID
    version: int


class PdfExportRead(s.ResponseContract):
    id: UUID
    state: Literal["queued", "running", "completed", "failed", "cancelled"]
    source: ExportVersionRead
    output: ExportVersionRead | None
    renderer_revision: str
    attempt_count: int
    max_attempts: int
    error_code: str | None
    cleanup_pending: bool
    row_version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PdfExportRevision(s.Contract):
    expected_version: int = Field(ge=1)


def _version(db: Session, version_id: UUID) -> ExportVersionRead:
    row = db.execute(
        select(ArtifactVersion, Artifact)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(ArtifactVersion.id == version_id)
    ).first()
    if row is None:
        raise ValueError("PDF export version lineage is incomplete")
    version, artifact = row
    return ExportVersionRead(
        artifact_id=artifact.id,
        artifact_title=artifact.title,
        version_id=version.id,
        version=version.version,
    )


def export_read(db: Session, export: PdfExport) -> dict[str, Any]:
    return PdfExportRead(
        id=export.id,
        state=cast(Literal["queued", "running", "completed", "failed", "cancelled"], export.state),
        source=_version(db, export.source_version_id),
        output=_version(db, export.output_version_id) if export.output_version_id else None,
        renderer_revision=export.renderer_revision,
        attempt_count=export.attempt_count,
        max_attempts=export.max_attempts,
        error_code=export.error_code,
        cleanup_pending=(
            export.container_lease_id is not None and export.cleanup_confirmed_at is None
        ),
        row_version=export.row_version,
        created_at=export.created_at,
        updated_at=export.updated_at,
        completed_at=export.completed_at,
    ).model_dump(mode="json")


def owned_export(db: Session, export_id: UUID, owner_id: UUID, *, lock: bool = False) -> PdfExport:
    statement = select(PdfExport).where(PdfExport.id == export_id, PdfExport.owner_id == owner_id)
    if lock:
        statement = statement.with_for_update()
    export = db.scalar(statement)
    if export is None:
        raise HTTPException(404, "PDF export not found")
    return export


def dispatch_pdf_export(export_id: UUID) -> None:
    try:
        from command_center.agents import queue

        task = getattr(queue, "execute_pdf_export", None)
        if task is None:
            return
        task.apply_async(
            args=(str(export_id),),
            task_id=f"pdf-export:{export_id}",
            queue="execution",
            expires=300,
        )
    except Exception:
        logger.warning("PDF export %s remains queued for beat dispatch", export_id)


@router.post(
    "/artifacts/{artifact_id}/versions/{version_id}/exports",
    response_model=PdfExportRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_export(
    artifact_id: UUID,
    version_id: UUID,
    body: PdfExportCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    renderer = request.app.state.settings.pdf_renderer_image
    if not renderer:
        raise HTTPException(503, "PDF renderer is not configured")

    def change(export_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        if identity.run_id is not None:
            if body.task_id is None:
                raise HTTPException(403, "Agent PDF exports require their current task")
            enforce_task_scope(
                db,
                owner_id=identity.id,
                run_id=identity.run_id,
                task_id=body.task_id,
            )
        existing = db.scalar(
            select(PdfExport)
            .where(
                PdfExport.owner_id == identity.id,
                PdfExport.source_version_id == version_id,
                PdfExport.renderer_revision == renderer,
                PdfExport.state.in_(["queued", "running", "completed"]),
            )
            .order_by(PdfExport.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return export_read(db, existing)
        export = PdfExport.create(
            db,
            record_id=export_id,
            owner_id=identity.id,
            artifact_id=artifact_id,
            version_id=version_id,
            renderer_revision=renderer,
            task_id=body.task_id,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return export_read(db, export)

    result = write(
        db,
        identity.id,
        key,
        f"POST:pdf-export:{artifact_id}:{version_id}",
        body,
        change,
    )
    if result["state"] == "queued":
        background.add_task(dispatch_pdf_export, UUID(str(result["id"])))
    return result


@router.get("/pdf-exports/{export_id}", response_model=PdfExportRead)
def export_detail(export_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    return export_read(db, owned_export(db, export_id, identity.id))


def change_export(
    action: Literal["cancel", "retry"],
    export_id: UUID,
    body: PdfExportRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        export = owned_export(db, export_id, identity.id, lock=True)
        check_version(export, body.expected_version)
        getattr(export, action)(request_id=UUID(request.state.request_id))
        db.flush()
        return export_read(db, export)

    result = write(db, identity.id, key, f"POST:pdf-export:{export_id}:{action}", body, change)
    if action == "retry" and result["state"] == "queued":
        background.add_task(dispatch_pdf_export, export_id)
    return result


@router.post("/pdf-exports/{export_id}/cancel", response_model=PdfExportRead)
def cancel_export(
    export_id: UUID,
    body: PdfExportRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    return change_export("cancel", export_id, body, identity, db, key, request, background)


@router.post("/pdf-exports/{export_id}/retry", response_model=PdfExportRead)
def retry_export(
    export_id: UUID,
    body: PdfExportRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    return change_export("retry", export_id, body, identity, db, key, request, background)
