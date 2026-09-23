"""Owned work conversations spanning durable agent runs."""

import hashlib
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.base import Base, utc_now
from command_center.db.crm import Opportunity, OwnedRecord, record_event
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.models import Task

if TYPE_CHECKING:
    from command_center.db.agents import AgentRun


class AgentSession(OwnedRecord, Base):
    """Canonical conversation identity, optionally attached to one work scope."""

    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            ["tasks.id", "tasks.owner_id"],
        ),
        ForeignKeyConstraint(
            ["opportunity_id", "owner_id"],
            ["opportunities.id", "opportunities.owner_id"],
        ),
        CheckConstraint(
            "num_nonnulls(task_id, opportunity_id) <= 1",
            name="one_scope",
        ),
        CheckConstraint("last_sequence >= 0", name="last_sequence"),
        Index(
            "uq_agent_sessions_owner_task",
            "owner_id",
            "task_id",
            unique=True,
            postgresql_where=text("task_id IS NOT NULL"),
        ),
        Index(
            "uq_agent_sessions_owner_opportunity",
            "owner_id",
            "opportunity_id",
            unique=True,
            postgresql_where=text("opportunity_id IS NOT NULL"),
        ),
    )

    title: Mapped[str] = mapped_column(String(300))
    task_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)

    @classmethod
    def open_chat(
        cls, session: Session, *, record_id: UUID, owner_id: UUID, title: str, request_id: UUID
    ) -> "AgentSession":
        conversation = cls(
            id=record_id, owner_id=owner_id, title=title[:300], task_id=None, opportunity_id=None
        )
        session.add(conversation)
        session.flush()
        record_event(
            session,
            owner_id,
            request_id,
            "agent_session.created",
            cls.__tablename__,
            conversation.id,
        )
        return conversation

    @classmethod
    def for_run(cls, session: Session, *, run: "AgentRun", request_id: UUID) -> "AgentSession":
        """Adopt a legacy one-shot run once, keeping its visible transcript intact."""
        session.refresh(run, with_for_update=True)
        if run.session_id is not None:
            conversation = session.get(cls, run.session_id)
            assert conversation is not None and conversation.owner_id == run.owner_id
            return conversation
        conversation = cls.open_chat(
            session,
            record_id=uuid5(run.id, "conversation"),
            owner_id=run.owner_id,
            title=run.title,
            request_id=request_id,
        )
        run.session_id = conversation.id
        run.input_sequence = 1
        run.consumed_sequence = 1
        conversation.last_sequence = 1
        session.add(
            AgentMessage(
                owner_id=run.owner_id,
                session_id=conversation.id,
                run_id=run.id,
                sequence=1,
                author="user",
                profile=run.profile,
                content=run.prompt,
            )
        )
        session.flush()
        if run.state == "completed" and run.output:
            conversation.append_assistant(
                run_id=run.id, profile=run.profile, content=run.output, request_id=request_id
            )
        record_event(
            session,
            run.owner_id,
            request_id,
            "agent_session.run_attached",
            cls.__tablename__,
            conversation.id,
            run_id=str(run.id),
        )
        return conversation

    @classmethod
    def open(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        task_id: UUID | None,
        opportunity_id: UUID | None,
        request_id: UUID,
    ) -> "AgentSession":
        if (task_id is None) == (opportunity_id is None):
            raise ValueError("Choose exactly one conversation scope")
        target: Task | Opportunity | None
        if task_id is not None:
            target = session.scalar(
                select(Task).where(Task.id == task_id, Task.owner_id == owner_id).with_for_update()
            )
            if target is None:
                raise RecordNotFound("Record not found")
            if target.state not in {"open", "in_progress", "snoozed"}:
                raise ValueError("Conversation targets must be active")
            scope_name, scope_id = "task_id", task_id
        else:
            assert opportunity_id is not None
            target = session.scalar(
                select(Opportunity)
                .where(
                    Opportunity.id == opportunity_id,
                    Opportunity.owner_id == owner_id,
                )
                .with_for_update()
            )
            if target is None:
                raise RecordNotFound("Record not found")
            if target.archived_at is not None or target.stage == "closed":
                raise ValueError("Conversation targets must be active")
            scope_name, scope_id = "opportunity_id", opportunity_id

        lock = int.from_bytes(
            hashlib.sha256(f"agent-session:{owner_id}:{scope_name}:{scope_id}".encode()).digest()[
                :8
            ],
            signed=True,
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        existing = session.scalar(
            select(cls).where(cls.owner_id == owner_id, getattr(cls, scope_name) == scope_id)
        )
        if existing is not None:
            return existing

        conversation = cls(
            id=record_id,
            owner_id=owner_id,
            title=target.title,
            task_id=task_id,
            opportunity_id=opportunity_id,
        )
        session.add(conversation)
        session.flush()
        record_event(
            session,
            owner_id,
            request_id,
            "agent_session.created",
            cls.__tablename__,
            conversation.id,
            task_id=str(task_id) if task_id else None,
            opportunity_id=str(opportunity_id) if opportunity_id else None,
        )
        return conversation

    def receive(
        self,
        *,
        content: str,
        profile: str,
        configuration: dict[str, Any],
        revision: str,
        request_id: UUID,
    ) -> "AgentMessage":
        """Persist one instruction and attach it to the sole active root run."""
        from command_center.db.agents import AgentRun

        if not content.strip():
            raise ValueError("Message content cannot be blank")
        if len(content) > 20000:
            raise ValueError("Message content exceeds the supported length")
        if not profile.strip():
            raise ValueError("Message profile cannot be blank")
        if len(profile) > 100:
            raise ValueError("Message profile exceeds the supported length")
        session = object_session(self)
        if session is None:
            raise ValueError("Conversation must belong to a transaction")
        session.refresh(self, with_for_update=True)
        active = session.scalar(
            select(AgentRun).where(
                AgentRun.session_id == self.id,
                AgentRun.state.in_(("queued", "running", "waiting_for_user")),
            )
        )
        if active is not None and active.profile != profile:
            raise RecordConflict("Finish or cancel active work before changing profiles")

        self.last_sequence += 1
        self.updated_at = utc_now()
        if active is None:
            active = AgentRun.enqueue(
                session,
                record_id=uuid4(),
                owner_id=self.owner_id,
                prompt=content,
                profile=profile,
                configuration=configuration,
                revision=revision,
                request_id=request_id,
                session_id=self.id,
                input_sequence=self.last_sequence,
            )
        message = AgentMessage(
            owner_id=self.owner_id,
            session_id=self.id,
            run_id=active.id,
            sequence=self.last_sequence,
            author="user",
            profile=profile,
            content=content,
        )
        session.add(message)
        session.flush()
        record_event(
            session,
            self.owner_id,
            request_id,
            "agent_message.created",
            AgentMessage.__tablename__,
            message.id,
            session_id=str(self.id),
            run_id=str(active.id),
            sequence=message.sequence,
            author=message.author,
        )
        return message

    def append_assistant(
        self,
        *,
        run_id: UUID,
        profile: str,
        content: str,
        request_id: UUID,
    ) -> "AgentMessage":
        session = object_session(self)
        if session is None:
            raise ValueError("Conversation must belong to a transaction")
        self.last_sequence += 1
        self.updated_at = utc_now()
        message = AgentMessage(
            owner_id=self.owner_id,
            session_id=self.id,
            run_id=run_id,
            sequence=self.last_sequence,
            author="assistant",
            profile=profile,
            content=content,
        )
        session.add(message)
        session.flush()
        record_event(
            session,
            self.owner_id,
            request_id,
            "agent_message.created",
            AgentMessage.__tablename__,
            message.id,
            session_id=str(self.id),
            run_id=str(run_id),
            sequence=message.sequence,
            author=message.author,
        )
        return message


class AgentMessage(OwnedRecord, Base):
    """Visible conversation content; private model reasoning never belongs here."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence"),
        ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["agent_sessions.id", "agent_sessions.owner_id"],
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
        ),
        CheckConstraint("sequence > 0", name="sequence"),
        CheckConstraint("author IN ('user', 'assistant')", name="author"),
        CheckConstraint("length(trim(profile)) > 0", name="profile"),
        CheckConstraint("length(trim(content)) > 0", name="content"),
    )

    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    run_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    author: Mapped[str] = mapped_column(String(20))
    profile: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
