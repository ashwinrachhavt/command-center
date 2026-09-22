"""Durable, fenced execution of immutable research scripts and selected inputs."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import (
    Artifact,
    ArtifactDerivation,
    ArtifactVersion,
    Document,
    DocumentType,
    TaskArtifact,
)
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.evidence import SourceRecord
from command_center.db.models import Task

MAX_SCRIPT_BYTES = 50 * 1024
MAX_INPUTS = 20
MAX_RESULT_CHARS = 100_000
MAX_CITATIONS = 50
TERMINAL_STATES = {"completed", "failed", "cancelled"}


class ResearchExecution(Base):
    __tablename__ = "research_executions"
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
            ["script_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        ForeignKeyConstraint(
            ["script_version_id", "script_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        ForeignKeyConstraint(
            ["output_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        ForeignKeyConstraint(
            ["output_version_id", "output_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    script_artifact_id: Mapped[UUID] = mapped_column(Uuid)
    script_version_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    output_title: Mapped[str] = mapped_column(String(300))
    document_type_id: Mapped[UUID] = mapped_column(ForeignKey("document_types.id"))
    output_artifact_id: Mapped[UUID | None] = mapped_column(Uuid)
    output_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
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
        task_id: UUID,
        script: str,
        input_version_ids: list[UUID],
        output_title: str,
        document_type_slug: str,
        policy_snapshot: dict[str, Any],
        request_id: UUID,
    ) -> "ResearchExecution":
        clean_title = output_title.strip()
        if not clean_title or len(clean_title) > 300:
            raise ValueError("Research output title is required")
        if not script.strip() or len(script.encode("utf-8")) > MAX_SCRIPT_BYTES:
            raise ValueError("Research script must contain at most 50 KiB")
        if not 1 <= len(input_version_ids) <= MAX_INPUTS or len(set(input_version_ids)) != len(
            input_version_ids
        ):
            raise ValueError("Choose 1 to 20 distinct immutable inputs")
        task = session.scalar(
            select(Task).where(Task.id == task_id, Task.owner_id == owner_id).with_for_update()
        )
        if task is None:
            raise RecordNotFound("Task not found")
        if task.state in {"done", "cancelled"}:
            raise RecordConflict("Choose an active task")
        document_type = session.scalar(
            select(DocumentType).where(DocumentType.slug == document_type_slug)
        )
        if document_type is None or document_type.slug not in {"research", "interview"}:
            raise ValueError("Choose a research or interview document type")
        selected = list(
            session.execute(
                select(ArtifactVersion, Artifact)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(
                    ArtifactVersion.id.in_(input_version_ids),
                    Artifact.owner_id == owner_id,
                    Artifact.archived_at.is_(None),
                )
            ).all()
        )
        if len(selected) != len(input_version_ids):
            raise RecordNotFound("One or more selected artifact versions are unavailable")
        sensitivity_order = {"public": 0, "private": 1, "restricted": 2}
        sensitivity = max(
            (artifact.sensitivity for _, artifact in selected),
            key=lambda value: sensitivity_order[value],
        )
        script_artifact = Artifact(
            id=uuid5(record_id, "script-artifact"),
            owner_id=owner_id,
            created_by_id=owner_id,
            title=f"Research script: {clean_title}",
            kind="source",
            sensitivity=sensitivity,
        )
        session.add(script_artifact)
        session.flush()
        script_version = script_artifact.append_payload(
            {"language": "python", "entrypoint": "main.py", "source": script},
            schema_key="research.python.v1",
            version_id=uuid5(record_id, "script-version"),
            request_id=request_id,
        )
        execution = cls(
            id=record_id,
            owner_id=owner_id,
            task_id=task.id,
            script_artifact_id=script_artifact.id,
            script_version_id=script_version.id,
            output_title=clean_title,
            document_type_id=document_type.id,
            policy_snapshot=policy_snapshot,
        )
        session.add(execution)
        session.flush()
        source_versions = set(
            session.scalars(
                select(SourceRecord.artifact_version_id).where(
                    SourceRecord.artifact_version_id.in_(input_version_ids)
                )
            )
        )
        for version, artifact in selected:
            session.add(
                ResearchExecutionInput(
                    execution_id=execution.id,
                    owner_id=owner_id,
                    artifact_id=artifact.id,
                    version_id=version.id,
                    role="public_source" if version.id in source_versions else "material",
                )
            )
        session.add(TaskArtifact(task_id=task.id, artifact_id=script_artifact.id))
        record_event(
            session,
            owner_id,
            request_id,
            "research.execution_queued",
            "research_executions",
            execution.id,
            task_id=str(task.id),
            script_version_id=str(script_version.id),
            input_count=len(selected),
        )
        return execution

    @classmethod
    def claim(
        cls, session: Session, execution_id: UUID | None = None
    ) -> "ResearchExecution | None":
        statement = select(cls).where(cls.state == "queued").order_by(cls.created_at, cls.id)
        if execution_id is not None:
            statement = statement.where(cls.id == execution_id)
        execution = session.scalar(statement.with_for_update(skip_locked=True).limit(1))
        if execution is None:
            return None
        if execution.attempt_count >= execution.max_attempts:
            execution._finish_failed("attempt_limit", cleanup=True)
            return None
        script_version = session.scalar(
            select(ArtifactVersion).where(
                ArtifactVersion.id == execution.script_version_id,
                ArtifactVersion.artifact_id == execution.script_artifact_id,
            )
        )
        source = (
            script_version.payload.get("source")
            if script_version is not None and script_version.payload is not None
            else None
        )
        image = execution.policy_snapshot.get("image")
        has_input = session.scalar(
            select(ResearchExecutionInput.execution_id)
            .where(ResearchExecutionInput.execution_id == execution.id)
            .limit(1)
        )
        if (
            not isinstance(source, str)
            or not source.strip()
            or not isinstance(image, str)
            or not image
            or not has_input
        ):
            execution._finish_failed("validation_failed", cleanup=True)
            execution._audit(
                execution.id, "research.execution_failed", error_code="validation_failed"
            )
            return None
        execution.state = "running"
        execution.attempt_count += 1
        execution.lease_id = uuid4()
        execution.container_lease_id = execution.lease_id
        execution.lease_expires_at = utc_now() + timedelta(minutes=3)
        execution.cleanup_confirmed_at = None
        execution.error_code = None
        return execution

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
            raise RecordConflict("Research execution lease was lost")
        self.lease_expires_at = utc_now() + timedelta(minutes=3)

    def cancel(self, *, request_id: UUID) -> None:
        if self.state not in {"queued", "running"}:
            raise RecordConflict("Only queued or running research can be cancelled")
        was_queued = self.state == "queued"
        self.state = "cancelled"
        self.cancellation_requested_at = utc_now()
        self.lease_id = None
        self.lease_expires_at = None
        if was_queued:
            self.cleanup_confirmed_at = utc_now()
        self.updated_at = utc_now()
        self._audit(request_id, "research.execution_cancelled")

    def retry(self, *, request_id: UUID) -> None:
        if self.state not in {"failed", "cancelled"}:
            raise RecordConflict("Only failed or cancelled research can be retried")
        if self.cleanup_confirmed_at is None:
            raise RecordConflict("Wait for the previous sandbox to stop before retrying")
        if self.attempt_count >= self.max_attempts:
            raise RecordConflict("This research execution reached its attempt limit")
        self.state = "queued"
        self.error_code = None
        self.cancellation_requested_at = None
        self.container_lease_id = None
        self.updated_at = utc_now()
        self._audit(request_id, "research.execution_retried")

    def mark_cleanup_confirmed(self, container_lease_id: UUID) -> bool:
        if self.container_lease_id != container_lease_id:
            return False
        self.cleanup_confirmed_at = utc_now()
        return True

    def fail(self, lease_id: UUID, error_code: str, *, cleanup: bool = True) -> bool:
        if not self.accepts(lease_id):
            return False
        self._finish_failed(error_code, cleanup=cleanup)
        self._audit(lease_id, "research.execution_failed", error_code=error_code)
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
        text: str,
        citations: list[dict[str, str]],
        request_id: UUID,
    ) -> ArtifactVersion:
        if not self.accepts(lease_id):
            raise RecordConflict("Research execution lease was lost")
        clean_text = text.strip()
        if not clean_text or len(clean_text) > MAX_RESULT_CHARS:
            raise ValueError("Research output must contain at most 100000 characters")
        if len(citations) > MAX_CITATIONS:
            raise ValueError("Research output has too many citations")
        session = object_session(self)
        assert session is not None
        inputs = list(
            session.scalars(
                select(ResearchExecutionInput).where(ResearchExecutionInput.execution_id == self.id)
            )
        )
        public_sources = {str(item.version_id) for item in inputs if item.role == "public_source"}
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for citation in citations:
            version_id = str(citation.get("source_version_id", ""))
            label = str(citation.get("label", "")).strip()
            if version_id not in public_sources or not label or len(label) > 300:
                raise ValueError("Citations must name selected public source versions")
            if version_id not in seen:
                normalized.append({"source_version_id": version_id, "label": label})
                seen.add(version_id)
        document_type = session.get(DocumentType, self.document_type_id)
        if document_type is None:
            raise ValueError("Research document type is unavailable")
        script_artifact = session.get(Artifact, self.script_artifact_id)
        if script_artifact is None or script_artifact.owner_id != self.owner_id:
            raise RecordConflict("Research script is unavailable")
        artifact = Artifact(
            id=uuid5(self.id, "output-artifact"),
            owner_id=self.owner_id,
            created_by_id=self.owner_id,
            title=self.output_title,
            kind="document",
            sensitivity=script_artifact.sensitivity,
        )
        session.add(artifact)
        session.flush()
        session.add(Document(artifact_id=artifact.id, document_type_id=document_type.id))
        version = artifact.append_payload(
            {"text": clean_text, "citations": normalized, "execution_id": str(self.id)},
            schema_key="research.document.v1",
            version_id=uuid5(self.id, "output-version"),
            request_id=request_id,
        )
        session.flush()
        for input_version_id in [self.script_version_id, *(item.version_id for item in inputs)]:
            session.add(
                ArtifactDerivation(
                    output_version_id=version.id,
                    input_version_id=input_version_id,
                    method="sandbox.research.v1",
                )
            )
        session.add(TaskArtifact(task_id=self.task_id, artifact_id=artifact.id))
        self.output_artifact_id = artifact.id
        self.output_version_id = version.id
        self.state = "completed"
        self.completed_at = utc_now()
        self.lease_id = None
        self.lease_expires_at = None
        self.cleanup_confirmed_at = utc_now()
        self.updated_at = utc_now()
        self._audit(request_id, "research.execution_completed", output_version_id=str(version.id))
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
                "research.execution_failed",
                error_code="worker_interrupted",
            )
        return len(rows)

    def _audit(self, request_id: UUID, action: str, **details: object) -> None:
        session = object_session(self)
        if session is None:
            raise ValueError("Research execution must belong to a transaction")
        record_event(
            session,
            self.owner_id,
            request_id,
            action,
            "research_executions",
            self.id,
            **details,
        )


class ResearchExecutionInput(Base):
    __tablename__ = "research_execution_inputs"
    __table_args__ = (
        CheckConstraint("role IN ('material', 'public_source')", name="role"),
        ForeignKeyConstraint(
            ["execution_id", "owner_id"],
            ["research_executions.id", "research_executions.owner_id"],
        ),
        ForeignKeyConstraint(["artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]),
        ForeignKeyConstraint(
            ["version_id", "artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
    )

    execution_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    artifact_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(20))
