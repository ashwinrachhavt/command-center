"""Human-reported application progress, attached to the existing preparation task."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    Select,
    String,
    Uuid,
    func,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import Artifact, ArtifactVersion, TaskArtifact
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict
from command_center.db.evidence import SourceRecord
from command_center.db.models import Task

ApplicationStatus = Literal[
    "preparing", "submitted", "interviewing", "offer", "rejected", "withdrawn"
]


class ApplicationTrack(Base):
    __tablename__ = "application_tracks"
    __table_args__ = (
        ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        ForeignKeyConstraint(
            ["job_context_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        CheckConstraint(
            "status IN ('preparing', 'submitted', 'interviewing', 'offer', "
            "'rejected', 'withdrawn')",
            name="status",
        ),
        CheckConstraint("row_version >= 1", name="row_version"),
    )

    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    job_context_artifact_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="preparing", index=True)
    submission_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    def set_status(self, status: ApplicationStatus, *, request_id: UUID) -> None:
        session = object_session(self)
        if session is None:
            raise ValueError("Application must belong to a transaction")
        if status == self.status:
            return
        previous = self.status
        self.status = status
        self.updated_at = utc_now()
        if status == "submitted" and self.submission_recorded_at is None:
            self.submission_recorded_at = self.updated_at
        elif status == "preparing":
            # Returning to preparation corrects an earlier submission report.
            self.submission_recorded_at = None
        record_event(
            session,
            self.owner_id,
            request_id,
            "application.status_recorded",
            self.__tablename__,
            self.task_id,
            previous=previous,
            status=status,
            source="human_report",
        )

    @classmethod
    def query(cls, owner_id: UUID) -> Select[Any]:
        from command_center.db.application_preparations import ApplicationPreparation
        from command_center.db.browser import BrowserSnapshot

        latest = (
            select(ApplicationPreparation.id)
            .where(ApplicationPreparation.task_id == cls.task_id)
            .order_by(ApplicationPreparation.created_at.desc(), ApplicationPreparation.id.desc())
            .limit(1)
            .correlate(cls)
            .scalar_subquery()
        )
        count = (
            select(func.count(ApplicationPreparation.id))
            .where(ApplicationPreparation.task_id == cls.task_id)
            .correlate(cls)
            .scalar_subquery()
        )
        return (
            select(
                cls,
                Task,
                ApplicationPreparation.id.label("preparation_id"),
                BrowserSnapshot.id.label("snapshot_id"),
                BrowserSnapshot.page_url,
                BrowserSnapshot.title.label("page_title"),
                BrowserSnapshot.origin,
                count.label("preparation_count"),
                func.greatest(
                    cls.updated_at, Task.updated_at, ApplicationPreparation.updated_at
                ).label("last_activity_at"),
            )
            .select_from(cls)
            .join(Task, Task.id == cls.task_id)
            .join(ApplicationPreparation, ApplicationPreparation.id == latest)
            .join(BrowserSnapshot, BrowserSnapshot.id == ApplicationPreparation.snapshot_id)
            .where(cls.owner_id == owner_id)
        )

    def capture_context(
        self,
        db: Session,
        *,
        record_id: UUID,
        request_id: UUID,
        context: dict[str, Any],
        page_url: str,
    ) -> ArtifactVersion:
        """Attach the first description; later edits use artifact checkpoints."""
        db.refresh(self, with_for_update=True)
        if self.job_context_artifact_id is not None:
            raise RecordConflict(
                "This application already has a job description; edit its saved version"
            )
        text = str(context.get("text", "")).strip()
        if (not text and context["extraction_method"] != "manual") or len(text) > 30000:
            raise ValueError("Choose a job description of at most 30,000 characters")
        title = str(context.get("job_title", ""))[:300]
        artifact = Artifact(
            id=uuid5(record_id, "job-context"),
            owner_id=self.owner_id,
            created_by_id=self.owner_id,
            title=f"Job description · {title or 'Application'}"[:300],
            kind="source",
            sensitivity="private",
        )
        db.add(artifact)
        db.flush()
        version = artifact.append_payload(
            {
                "text": text,
                "job_title": title,
                "company_name": str(context.get("company_name", ""))[:200],
                "page_url": page_url,
                "extraction_method": context["extraction_method"],
                "truncated": bool(context.get("truncated", False)),
            },
            schema_key="application.job_context.v1",
            version_id=uuid5(record_id, "job-context-version"),
            request_id=request_id,
        )
        db.flush()
        self.job_context_artifact_id = artifact.id
        db.add(TaskArtifact(task_id=self.task_id, artifact_id=artifact.id))
        db.add(
            SourceRecord(
                id=uuid5(record_id, "job-context-source"),
                artifact_version_id=version.id,
                provider="browser_companion"
                if context["extraction_method"] != "manual"
                else "user",
                account_scope="application",
                locator=page_url,
                extraction_method=context["extraction_method"],
            )
        )
        record_event(
            db,
            self.owner_id,
            request_id,
            "application.job_context_captured",
            "application_tracks",
            self.task_id,
            artifact_id=str(artifact.id),
            version_id=str(version.id),
            method=context["extraction_method"],
        )
        return version

    def current_context_version(self, db: Session) -> ArtifactVersion | None:
        if self.job_context_artifact_id is None:
            return None
        return db.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                Artifact.id == self.job_context_artifact_id,
                Artifact.owner_id == self.owner_id,
                Artifact.archived_at.is_(None),
            )
            .order_by(ArtifactVersion.version.desc())
            .limit(1)
        )
