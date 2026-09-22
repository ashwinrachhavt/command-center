"""Durable, fenced conversion jobs for original document versions."""

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, Text, Uuid, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict, RecordNotFound


class DocumentImport(Base):
    __tablename__ = "document_imports"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="state"
        ),
        CheckConstraint("byte_size BETWEEN 1 AND 20971520", name="byte_size"),
        CheckConstraint("row_version >= 1", name="row_version"),
        CheckConstraint(
            "(state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="lease_state",
        ),
        CheckConstraint(
            "(state = 'completed') = "
            "(extraction_artifact_id IS NOT NULL AND extraction_version_id IS NOT NULL)",
            name="output_state",
        ),
        CheckConstraint("error IS NULL OR state = 'failed'", name="error_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    source_version_id: Mapped[UUID] = mapped_column(ForeignKey("artifact_versions.id"), unique=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(200))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    extraction_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    extraction_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifact_versions.id"))
    error: Mapped[str | None] = mapped_column(Text)
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def create_from_upload(
        cls,
        session: Session,
        *,
        import_id: UUID,
        owner_id: UUID,
        title: str,
        document_type_id: UUID,
        blob_sha256: str,
        blob_storage_key: str,
        byte_size: int,
        filename: str,
        media_type: str,
        artifact_id: UUID | None,
        expected_version: int | None,
        request_id: UUID,
    ) -> "DocumentImport":
        """Create one original version, acquisition, review task and conversion job."""
        from command_center.db.artifacts import (
            Artifact,
            Blob,
            Document,
            DocumentType,
            TaskArtifact,
        )
        from command_center.db.evidence import SourceRecord
        from command_center.db.models import Task

        clean_title = title.strip()
        if not clean_title or len(clean_title) > 300:
            raise ValueError("Document title is required")
        if bool(artifact_id) != bool(expected_version):
            raise ValueError("Appending a document requires its current version")
        document_type = session.get(DocumentType, document_type_id)
        if document_type is None:
            raise ValueError("Choose a known document type")
        session.execute(
            insert(Blob)
            .values(
                id=uuid5(NAMESPACE_URL, "command-center:blob:" + blob_sha256),
                sha256=blob_sha256,
                storage_key=blob_storage_key,
                byte_size=byte_size,
            )
            .on_conflict_do_nothing(index_elements=[Blob.sha256])
        )
        persisted_blob = session.scalar(select(Blob).where(Blob.sha256 == blob_sha256))
        if persisted_blob is None:
            raise ValueError("Stored document metadata is unavailable")

        target: Artifact
        if artifact_id is None:
            target = Artifact(
                id=uuid5(import_id, "artifact"),
                owner_id=owner_id,
                created_by_id=owner_id,
                title=clean_title,
                kind="document",
                sensitivity="private",
            )
            session.add(target)
            session.flush()
            session.add(Document(artifact_id=target.id, document_type_id=document_type.id))
        else:
            existing = session.scalar(
                select(Artifact)
                .where(Artifact.id == artifact_id, Artifact.owner_id == owner_id)
                .with_for_update()
            )
            if existing is None:
                raise RecordNotFound("Document not found")
            target = existing
            if target.archived_at:
                raise RecordConflict("Archived documents cannot receive versions")
            if target.row_version != expected_version:
                raise RecordConflict("Refresh the document before appending a version")
            facet = session.get(Document, target.id)
            if target.kind != "document" or facet is None:
                raise ValueError("Choose a document artifact")
            if facet.document_type_id != document_type.id:
                raise ValueError("A document's type cannot change between versions")

        version = target.append_blob(
            persisted_blob,
            media_type=media_type,
            version_id=uuid5(import_id, "source-version"),
            request_id=request_id,
        )
        source = SourceRecord(
            id=uuid5(import_id, "source-record"),
            artifact_version_id=version.id,
            provider="user",
            account_scope="private",
            locator=f"upload:{filename}",
            extraction_method="upload",
        )
        task = Task(
            id=uuid5(import_id, "review-task"),
            owner_id=owner_id,
            title=f"Review extracted text: {clean_title}",
            state="open",
            priority=1,
            rationale="Confirm the extracted document before using it as profile evidence.",
        )
        session.add_all([source, task])
        session.flush()
        session.add(TaskArtifact(task_id=task.id, artifact_id=target.id))
        job = cls.queued(
            session,
            import_id=import_id,
            owner_id=owner_id,
            artifact_id=target.id,
            source_version_id=version.id,
            task_id=task.id,
            filename=filename,
            media_type=media_type,
            byte_size=byte_size,
            request_id=request_id,
        )
        session.flush()
        return job

    @classmethod
    def queued(
        cls,
        session: Session,
        *,
        import_id: UUID,
        owner_id: UUID,
        artifact_id: UUID,
        source_version_id: UUID,
        task_id: UUID,
        filename: str,
        media_type: str,
        byte_size: int,
        request_id: UUID,
    ) -> "DocumentImport":
        if not filename.strip() or not media_type.strip() or not 0 < byte_size <= 20 * 1024 * 1024:
            raise ValueError("Document metadata is invalid")
        job = cls(
            id=import_id,
            owner_id=owner_id,
            artifact_id=artifact_id,
            source_version_id=source_version_id,
            task_id=task_id,
            filename=filename,
            media_type=media_type,
            byte_size=byte_size,
            state="queued",
        )
        session.add(job)
        record_event(
            session,
            owner_id,
            request_id,
            "document.import_queued",
            "document_imports",
            import_id,
            artifact_id=str(artifact_id),
            source_version_id=str(source_version_id),
            task_id=str(task_id),
        )
        return job

    @classmethod
    def claim(cls, session: Session, import_id: UUID | None = None) -> "DocumentImport | None":
        statement = select(cls).where(cls.state == "queued").order_by(cls.created_at, cls.id)
        if import_id is not None:
            statement = statement.where(cls.id == import_id)
        job = session.scalar(statement.with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        job.state = "running"
        job.lease_id = uuid4()
        job.lease_expires_at = utc_now() + timedelta(minutes=5)
        job.error = None
        return job

    def accepts(self, lease_id: UUID | None) -> bool:
        return bool(
            lease_id
            and self.state == "running"
            and self.lease_id == lease_id
            and self.lease_expires_at is not None
            and self.lease_expires_at > utc_now()
        )

    def renew(self, lease_id: UUID) -> None:
        if not self.accepts(lease_id):
            raise ValueError("Document conversion lease was lost")
        self.lease_expires_at = utc_now() + timedelta(minutes=5)

    def cancel(self, *, request_id: UUID) -> None:
        if self.state not in {"queued", "running"}:
            raise ValueError("Only queued or running document conversions can be cancelled")
        self.state = "cancelled"
        self.lease_id = None
        self.lease_expires_at = None
        self.updated_at = utc_now()
        session = object_session(self)
        if session is None:
            raise ValueError("Document import must belong to a transaction")
        record_event(
            session,
            self.owner_id,
            request_id,
            "document.import_cancelled",
            "document_imports",
            self.id,
        )

    def retry(self, *, request_id: UUID) -> None:
        if self.state not in {"failed", "cancelled"}:
            raise ValueError("Only failed or cancelled document conversions can be retried")
        self.state = "queued"
        self.error = None
        self.lease_id = None
        self.lease_expires_at = None
        self.updated_at = utc_now()
        session = object_session(self)
        if session is None:
            raise ValueError("Document import must belong to a transaction")
        record_event(
            session,
            self.owner_id,
            request_id,
            "document.import_retried",
            "document_imports",
            self.id,
        )

    def complete(
        self,
        lease_id: UUID,
        *,
        extraction_artifact_id: UUID,
        extraction_version_id: UUID,
        request_id: UUID,
    ) -> None:
        if not self.accepts(lease_id):
            raise ValueError("Document conversion lease was lost")
        self.state = "completed"
        self.extraction_artifact_id = extraction_artifact_id
        self.extraction_version_id = extraction_version_id
        self.lease_id = None
        self.lease_expires_at = None
        self.updated_at = utc_now()
        session = object_session(self)
        assert session is not None
        record_event(
            session,
            self.owner_id,
            request_id,
            "document.import_completed",
            "document_imports",
            self.id,
            extraction_artifact_id=str(extraction_artifact_id),
            extraction_version_id=str(extraction_version_id),
        )

    def fail(self, lease_id: UUID, *, error: str, request_id: UUID) -> bool:
        if not self.accepts(lease_id):
            return False
        self.state = "failed"
        self.error = error[:1000]
        self.lease_id = None
        self.lease_expires_at = None
        self.updated_at = utc_now()
        session = object_session(self)
        assert session is not None
        record_event(
            session,
            self.owner_id,
            request_id,
            "document.import_failed",
            "document_imports",
            self.id,
            error=self.error,
        )
        return True

    @classmethod
    def expire_stale(cls, session: Session) -> int:
        rows = list(
            session.scalars(
                select(cls)
                .where(
                    cls.state == "running",
                    cls.lease_expires_at.is_not(None),
                    cls.lease_expires_at <= utc_now(),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for job in rows:
            lease_id = job.lease_id
            assert lease_id is not None
            job.state = "failed"
            job.error = "conversion_lease_expired"
            job.lease_id = None
            job.lease_expires_at = None
            job.updated_at = utc_now()
            record_event(
                session,
                job.owner_id,
                uuid4(),
                "document.import_failed",
                "document_imports",
                job.id,
                error=job.error,
            )
        return len(rows)
