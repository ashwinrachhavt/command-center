"""Identity, business commitments and audit, independent of machine work."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now


class Actor(Base):
    __tablename__ = "actors"
    __table_args__ = (CheckConstraint("kind IN ('human', 'agent', 'service')", name="kind"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(200))
    auth_subject: Mapped[str | None] = mapped_column(String(500), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class Task(Base):
    """Business commitment; worker lease/retry state must never live here."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["opportunity_id", "owner_id"], ["opportunities.id", "opportunities.owner_id"]
        ),
        CheckConstraint(
            "state IN ('open', 'in_progress', 'waiting', 'snoozed', 'done', 'cancelled')",
            name="state",
        ),
        CheckConstraint("priority BETWEEN 0 AND 3", name="priority"),
        CheckConstraint("row_version >= 1", name="row_version"),
        CheckConstraint("NOT (due_date IS NOT NULL AND due_at IS NOT NULL)", name="due_semantics"),
        CheckConstraint("(state = 'done') = (completed_at IS NOT NULL)", name="completion"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    rationale: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    def revise(self, changes: dict[str, Any], *, request_id: UUID) -> None:
        allowed = {
            "title",
            "state",
            "priority",
            "rationale",
            "due_date",
            "due_at",
            "opportunity_id",
        }
        if changes.keys() - allowed:
            raise ValueError("Unsupported task fields")
        if "title" in changes and not str(changes["title"] or "").strip():
            raise ValueError("Task title cannot be blank")
        changed_fields = sorted(changes)
        state = changes.pop("state", self.state)
        if state != self.state:
            if state == "done":
                self.complete(actor_id=self.owner_id, request_id=request_id)
            elif self.state in {"done", "cancelled"}:
                if state != "open":
                    raise ValueError("Reopen a finished task before changing its state")
                self.reopen(actor_id=self.owner_id, request_id=request_id)
            else:
                self.state = state
        for key, value in changes.items():
            setattr(self, key, value)
        if self.due_date and self.due_at:
            raise ValueError("Choose a due date or an exact due time")
        self.updated_at = utc_now()
        session = object_session(self)
        if session is None:
            raise ValueError("Task must belong to a transaction")
        session.add(
            AuditEvent(
                actor_id=self.owner_id,
                action="task.updated",
                subject_type="tasks",
                subject_id=self.id,
                request_id=request_id,
                details={"fields": changed_fields},
            )
        )

    def complete(self, *, actor_id: UUID, request_id: UUID) -> None:
        """Enqueue state and redacted audit in the caller's transaction; never commit here."""
        if self.state not in {"open", "in_progress", "waiting", "snoozed"}:
            raise ValueError("Only an active task can be completed")
        session = object_session(self)
        if session is None or self.id is None:
            raise ValueError("Persist the task in a session before completing it")
        previous_state = self.state
        self.state = "done"
        self.completed_at = utc_now()
        session.add(
            AuditEvent(
                actor_id=actor_id,
                action="task.completed",
                subject_type="task",
                subject_id=self.id,
                request_id=request_id,
                details={"from_state": previous_state, "to_state": "done"},
            )
        )

    def reopen(self, *, actor_id: UUID, request_id: UUID) -> None:
        if self.state not in {"done", "cancelled"}:
            raise ValueError("Only a finished task can be reopened")
        session = object_session(self)
        if session is None or self.id is None:
            raise ValueError("Persist the task in a session before reopening it")
        previous_state = self.state
        self.state = "open"
        self.completed_at = None
        session.add(
            AuditEvent(
                actor_id=actor_id,
                action="task.reopened",
                subject_type="task",
                subject_id=self.id,
                request_id=request_id,
                details={"from_state": previous_state, "to_state": "open"},
            )
        )


class AuditEvent(Base):
    """Append-only through future services; retain subject IDs independently of deletion."""

    __tablename__ = "audit_events"
    __table_args__ = (CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    subject_type: Mapped[str] = mapped_column(String(100))
    subject_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    request_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, index=True)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
