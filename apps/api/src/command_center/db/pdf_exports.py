"""Durable selected-version PDF derivatives with fenced renderer execution."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import (
    Artifact,
    ArtifactDerivation,
    ArtifactVersion,
    Blob,
    Document,
    TaskArtifact,
)
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.models import Task


class PdfExport(Base):
    __tablename__ = "pdf_exports"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="state",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 2", name="attempt_count"),
        CheckConstraint("max_attempts = 2", name="max_attempts"),
        CheckConstraint("row_version >= 1", name="row_version"),
        CheckConstraint(
            "(state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="lease_state",
        ),
        CheckConstraint(
            "(state = 'completed') = "
            "(output_artifact_id IS NOT NULL AND output_version_id IS NOT NULL)",
            name="output_state",
        ),
        CheckConstraint("error_code IS NULL OR state = 'failed'", name="error_state"),
        ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        ForeignKeyConstraint(
            ["source_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        ForeignKeyConstraint(
            ["source_version_id", "source_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        ForeignKeyConstraint(
            ["output_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        ForeignKeyConstraint(
            ["output_version_id", "output_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        Index(
            "uq_pdf_exports_active_source_renderer",
            "owner_id",
            "source_version_id",
            "renderer_revision",
            unique=True,
            postgresql_where=text("state IN ('queued', 'running')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    source_artifact_id: Mapped[UUID] = mapped_column(Uuid)
    source_version_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    output_artifact_id: Mapped[UUID | None] = mapped_column(Uuid)
    output_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    renderer_revision: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    container_lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cleanup_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error_code: Mapped[str | None] = mapped_column(String(100))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        artifact_id: UUID,
        version_id: UUID,
        renderer_revision: str,
        task_id: UUID | None,
        request_id: UUID,
    ) -> "PdfExport":
        if not renderer_revision or len(renderer_revision) > 200:
            raise ValueError("PDF renderer revision is unavailable")
        row = session.execute(
            select(ArtifactVersion, Artifact, Document)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .join(Document, Document.artifact_id == Artifact.id)
            .where(
                Artifact.id == artifact_id,
                ArtifactVersion.id == version_id,
                Artifact.owner_id == owner_id,
                Artifact.archived_at.is_(None),
            )
            .with_for_update()
        ).first()
        if row is None:
            raise RecordNotFound("Editable document version not found")
        version, _, _ = row
        if version.payload is None or not isinstance(version.payload.get("text"), str):
            raise ValueError("Choose an editable text version to export")
        if len(version.payload["text"]) > 100_000:
            raise ValueError("Document text exceeds the PDF export limit")
        if task_id is not None:
            task = session.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
            if task is None:
                raise RecordNotFound("Task not found")
        export = cls(
            id=record_id,
            owner_id=owner_id,
            task_id=task_id,
            source_artifact_id=artifact_id,
            source_version_id=version_id,
            renderer_revision=renderer_revision,
        )
        session.add(export)
        record_event(
            session,
            owner_id,
            request_id,
            "pdf.export_queued",
            "pdf_exports",
            export.id,
            source_version_id=str(version_id),
            renderer_revision=renderer_revision,
        )
        return export

    @classmethod
    def claim(cls, session: Session, export_id: UUID | None = None) -> "PdfExport | None":
        statement = select(cls).where(cls.state == "queued").order_by(cls.created_at, cls.id)
        if export_id is not None:
            statement = statement.where(cls.id == export_id)
        export = session.scalar(statement.with_for_update(skip_locked=True).limit(1))
        if export is None:
            return None
        if export.attempt_count >= export.max_attempts:
            export._finish_failed("attempt_limit", cleanup=True)
            return None
        source = session.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ArtifactVersion.id == export.source_version_id,
                Artifact.id == export.source_artifact_id,
                Artifact.owner_id == export.owner_id,
                Artifact.archived_at.is_(None),
            )
        )
        markdown = source.payload.get("text") if source and source.payload else None
        if not isinstance(markdown, str):
            export._finish_failed("validation_failed", cleanup=True)
            export._audit(export.id, "pdf.export_failed", error_code="validation_failed")
            return None
        export.state = "running"
        export.attempt_count += 1
        export.lease_id = uuid4()
        export.container_lease_id = export.lease_id
        export.lease_expires_at = utc_now() + timedelta(minutes=2)
        export.cleanup_confirmed_at = None
        export.error_code = None
        return export

    def accepts(self, lease_id: UUID | None) -> bool:
        return bool(
            lease_id
            and self.state == "running"
            and self.lease_id == lease_id
            and self.lease_expires_at
            and self.lease_expires_at > utc_now()
        )

    def renew(self, lease_id: UUID) -> None:
        if not self.accepts(lease_id):
            raise RecordConflict("PDF export lease was lost")
        self.lease_expires_at = utc_now() + timedelta(minutes=2)

    def cancel(self, *, request_id: UUID) -> None:
        if self.state not in {"queued", "running"}:
            raise RecordConflict("Only queued or running PDF exports can be cancelled")
        was_queued = self.state == "queued"
        self.state = "cancelled"
        self.cancellation_requested_at = utc_now()
        self.lease_id = None
        self.lease_expires_at = None
        if was_queued:
            self.cleanup_confirmed_at = utc_now()
        self.updated_at = utc_now()
        self._audit(request_id, "pdf.export_cancelled")

    def retry(self, *, request_id: UUID) -> None:
        if self.state not in {"failed", "cancelled"}:
            raise RecordConflict("Only failed or cancelled PDF exports can be retried")
        if self.cleanup_confirmed_at is None:
            raise RecordConflict("Wait for the previous renderer to stop before retrying")
        if self.attempt_count >= self.max_attempts:
            raise RecordConflict("This PDF export reached its attempt limit")
        self.state = "queued"
        self.error_code = None
        self.cancellation_requested_at = None
        self.container_lease_id = None
        self.updated_at = utc_now()
        self._audit(request_id, "pdf.export_retried")

    def mark_cleanup_confirmed(self, container_lease_id: UUID) -> bool:
        if self.container_lease_id != container_lease_id:
            return False
        self.cleanup_confirmed_at = utc_now()
        return True

    def fail(self, lease_id: UUID, error_code: str, *, cleanup: bool = True) -> bool:
        if not self.accepts(lease_id):
            return False
        self._finish_failed(error_code, cleanup=cleanup)
        self._audit(lease_id, "pdf.export_failed", error_code=error_code)
        return True

    def _finish_failed(self, error_code: str, *, cleanup: bool) -> None:
        self.state = "failed"
        self.error_code = error_code[:100]
        self.lease_id = None
        self.lease_expires_at = None
        self.cleanup_confirmed_at = utc_now() if cleanup else None
        self.updated_at = utc_now()

    def complete(
        self,
        lease_id: UUID,
        *,
        blob: Blob,
        request_id: UUID,
    ) -> ArtifactVersion:
        if not self.accepts(lease_id):
            raise RecordConflict("PDF export lease was lost")
        if blob.byte_size <= 4 or blob.byte_size > 10 * 1024 * 1024:
            raise ValueError("PDF output exceeds the supported size")
        session = object_session(self)
        assert session is not None
        source = session.execute(
            select(ArtifactVersion, Artifact, Document)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .join(Document, Document.artifact_id == Artifact.id)
            .where(
                ArtifactVersion.id == self.source_version_id,
                Artifact.id == self.source_artifact_id,
                Artifact.owner_id == self.owner_id,
                Artifact.archived_at.is_(None),
            )
        ).first()
        if source is None:
            raise RecordConflict("Source document version is unavailable")
        source_version, source_artifact, source_document = source
        output = Artifact(
            id=uuid5(self.id, "output-artifact"),
            owner_id=self.owner_id,
            created_by_id=self.owner_id,
            title=f"{source_artifact.title} — PDF (v{source_version.version})",
            kind="document",
            sensitivity=source_artifact.sensitivity,
        )
        session.add(output)
        session.flush()
        session.add(
            Document(artifact_id=output.id, document_type_id=source_document.document_type_id)
        )
        version = output.append_blob(
            blob,
            media_type="application/pdf",
            version_id=uuid5(self.id, "output-version"),
            request_id=request_id,
        )
        session.flush()
        session.add(
            ArtifactDerivation(
                output_version_id=version.id,
                input_version_id=source_version.id,
                method="pdf.weasyprint.v1",
            )
        )
        if self.task_id is not None:
            session.add(TaskArtifact(task_id=self.task_id, artifact_id=output.id))
        self.output_artifact_id = output.id
        self.output_version_id = version.id
        self.state = "completed"
        self.completed_at = utc_now()
        self.lease_id = None
        self.lease_expires_at = None
        self.cleanup_confirmed_at = utc_now()
        self.updated_at = utc_now()
        self._audit(request_id, "pdf.export_completed", output_version_id=str(version.id))
        return version

    @classmethod
    def expire_stale(cls, session: Session) -> int:
        rows = list(
            session.scalars(
                select(cls)
                .where(cls.state == "running", cls.lease_expires_at < utc_now())
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            row._finish_failed("worker_interrupted", cleanup=False)
            row._audit(
                row.container_lease_id or row.id,
                "pdf.export_failed",
                error_code="worker_interrupted",
            )
        return len(rows)

    def _audit(self, request_id: UUID, action: str, **details: object) -> None:
        session = object_session(self)
        if session is None:
            raise ValueError("PDF export must belong to a transaction")
        record_event(
            session,
            self.owner_id,
            request_id,
            action,
            "pdf_exports",
            self.id,
            **details,
        )
