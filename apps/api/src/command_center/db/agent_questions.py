"""Durable, branch-specific questions and exact graph-resume intents."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import OwnedRecord, record_event
from command_center.db.errors import RecordConflict


class AgentQuestion(OwnedRecord, Base):
    """One LangGraph interrupt surfaced to the owner of its work conversation."""

    __tablename__ = "agent_questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["agent_sessions.id", "agent_sessions.owner_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "owner_id"),
        UniqueConstraint("run_id", "interrupt_id"),
        CheckConstraint("state IN ('open', 'answered', 'resumed', 'cancelled')", name="state"),
        CheckConstraint("length(trim(prompt)) BETWEEN 1 AND 10000", name="prompt_length"),
        CheckConstraint("length(interrupt_id) BETWEEN 1 AND 100", name="interrupt_length"),
        CheckConstraint("length(branch_id) BETWEEN 1 AND 100", name="branch_length"),
        CheckConstraint("length(role) BETWEEN 1 AND 100", name="role_length"),
        CheckConstraint("length(tool_call_id) BETWEEN 1 AND 200", name="tool_call_length"),
        CheckConstraint(
            "(state = 'open' AND answer IS NULL AND answered_at IS NULL) OR "
            "(state IN ('answered', 'resumed') AND answer IS NOT NULL AND answered_at IS NOT NULL) "
            "OR state = 'cancelled'",
            name="answer_state",
        ),
        Index("ix_agent_questions_owner_run_state", "owner_id", "run_id", "state"),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    interrupt_id: Mapped[str] = mapped_column(String(100))
    branch_id: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(100))
    tool_call_id: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="open", index=True)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @classmethod
    def capture_checkpoint(
        cls,
        session: Session,
        *,
        run: Any,
        lease_id: UUID,
        interruptions: list[dict[str, str]],
        request_id: UUID,
        recovering: bool = False,
    ) -> list["AgentQuestion"]:
        """Bind trusted saver interrupts before releasing the worker lease."""
        from command_center.db.agent_events import AgentEvent

        now = utc_now()
        if run.state != "running" or run.lease_id != lease_id:
            raise RecordConflict("The agent run lease is no longer active")
        if recovering:
            if run.lease_expires_at is None or run.lease_expires_at > now:
                raise RecordConflict("Only an expired question checkpoint can be recovered")
        elif run.lease_expires_at is None or run.lease_expires_at <= now:
            raise RecordConflict("The agent run lease is no longer active")
        if run.session_id is None or not interruptions:
            raise ValueError("Questions require a work conversation and checkpoint interrupts")

        normalized: dict[str, dict[str, str]] = {}
        for item in interruptions:
            interrupt_id = str(item.get("interrupt_id", "")).strip()
            branch_id = str(item.get("branch_id", "")).strip()
            role = str(item.get("role", "")).strip()
            tool_call_id = str(item.get("tool_call_id", "")).strip()
            prompt = str(item.get("prompt", "")).strip()
            if (
                not interrupt_id
                or len(interrupt_id) > 100
                or not branch_id
                or len(branch_id) > 100
                or not role
                or len(role) > 100
                or not tool_call_id
                or len(tool_call_id) > 200
                or not prompt
                or len(prompt) > 10000
            ):
                raise ValueError("Invalid durable question checkpoint")
            value = {
                "interrupt_id": interrupt_id,
                "branch_id": branch_id,
                "role": role,
                "tool_call_id": tool_call_id,
                "prompt": prompt,
            }
            if interrupt_id in normalized and normalized[interrupt_id] != value:
                raise ValueError("A checkpoint interrupt identity changed")
            normalized[interrupt_id] = value

        existing = {
            question.interrupt_id: question
            for question in session.scalars(
                select(cls).where(cls.run_id == run.id).with_for_update()
            )
        }
        questions: list[AgentQuestion] = []
        for interrupt_id, value in normalized.items():
            question = existing.get(interrupt_id)
            if question is None:
                question = cls(
                    id=uuid5(run.id, f"question:{interrupt_id}"),
                    owner_id=run.owner_id,
                    run_id=run.id,
                    session_id=run.session_id,
                    **value,
                )
                session.add(question)
                session.flush([question])
                record_event(
                    session,
                    run.owner_id,
                    request_id,
                    "agent_question.opened",
                    cls.__tablename__,
                    question.id,
                    run_id=str(run.id),
                    session_id=str(run.session_id),
                    interrupt_id=interrupt_id,
                    branch_id=value["branch_id"],
                    role=value["role"],
                )
            elif any(getattr(question, key) != value[key] for key in value):
                raise RecordConflict("A checkpoint interrupt identity changed")
            questions.append(question)

        cls._apply_resumed_intents(session, run.id, set(normalized), request_id=request_id)
        run.state = "waiting_for_user"
        run.lease_id = None
        run.lease_expires_at = None
        run.completed_at = None
        AgentEvent.append_status(session, run, "waiting_for_user")
        record_event(
            session,
            run.owner_id,
            request_id,
            "agent.waiting_for_user",
            "agent_runs",
            run.id,
            question_ids=[str(question.id) for question in questions],
        )
        return questions

    @classmethod
    def _apply_resumed_intents(
        cls,
        session: Session,
        run_id: UUID,
        current_interrupts: set[str],
        *,
        request_id: UUID,
    ) -> None:
        intents = session.scalars(
            select(AgentResumeIntent)
            .where(AgentResumeIntent.run_id == run_id, AgentResumeIntent.state == "pending")
            .with_for_update()
        ).all()
        for intent in intents:
            if intent.interrupt_id in current_interrupts:
                continue
            intent.state = "applied"
            intent.applied_at = utc_now()
            question = session.get(cls, intent.question_id)
            if question is not None and question.state == "answered":
                question.state = "resumed"
                question.updated_at = utc_now()
                record_event(
                    session,
                    question.owner_id,
                    request_id,
                    "agent_question.resumed",
                    cls.__tablename__,
                    question.id,
                    run_id=str(run_id),
                    interrupt_id=question.interrupt_id,
                )

    @classmethod
    def complete_resume(cls, session: Session, *, run_id: UUID, request_id: UUID) -> None:
        cls._apply_resumed_intents(session, run_id, set(), request_id=request_id)

    @classmethod
    def requeue_interrupted_resume(
        cls,
        session: Session,
        *,
        run: Any,
        lease_id: UUID,
        request_id: UUID,
    ) -> None:
        """Recover a crashed delivery whose answer may already be in the saver."""
        from command_center.db.agent_events import AgentEvent

        if (
            run.state != "running"
            or run.lease_id != lease_id
            or run.lease_expires_at is None
            or run.lease_expires_at > utc_now()
        ):
            raise RecordConflict("Only an expired resume delivery can be recovered")
        pending = session.scalar(
            select(AgentResumeIntent.id).where(
                AgentResumeIntent.run_id == run.id,
                AgentResumeIntent.state == "pending",
            )
        )
        if pending is None:
            raise RecordConflict("The run has no pending resume intent")
        run.state = "queued"
        run.lease_id = None
        run.lease_expires_at = None
        AgentEvent.append_status(session, run, "queued")
        record_event(
            session,
            run.owner_id,
            request_id,
            "agent.resume_recovered",
            "agent_runs",
            run.id,
        )

    def answer_once(
        self,
        session: Session,
        *,
        answer: str,
        expected_version: int,
        request_id: UUID,
    ) -> "AgentQuestion":
        """Record one exact answer and atomically queue only its interrupt."""
        from command_center.db.agent_events import AgentEvent
        from command_center.db.agents import AgentRun

        clean = answer.strip()
        if not clean or len(clean) > 20000:
            raise ValueError("Question answers must contain 1 to 20000 characters")
        if self.state != "open":
            if self.answer == clean and self.state in {"answered", "resumed"}:
                return self
            raise RecordConflict("This question is no longer open")
        if self.row_version != expected_version:
            raise RecordConflict("This question changed; refresh before answering")
        run = session.scalar(select(AgentRun).where(AgentRun.id == self.run_id).with_for_update())
        if run is None or run.owner_id != self.owner_id or run.session_id != self.session_id:
            raise RecordConflict("The question run is unavailable")
        if run.state != "waiting_for_user":
            raise RecordConflict("This run is not waiting for an answer")
        pending = session.scalar(
            select(AgentResumeIntent.id).where(
                AgentResumeIntent.run_id == run.id,
                AgentResumeIntent.state == "pending",
            )
        )
        if pending is not None:
            raise RecordConflict("Another answer is already resuming this run")
        self.state = "answered"
        self.answer = clean
        self.answered_at = utc_now()
        self.updated_at = utc_now()
        session.add(
            AgentResumeIntent(
                id=uuid5(self.id, "resume-intent"),
                owner_id=self.owner_id,
                run_id=self.run_id,
                question_id=self.id,
                interrupt_id=self.interrupt_id,
                answer=clean,
            )
        )
        run.state = "queued"
        run.lease_id = None
        run.lease_expires_at = None
        run.completed_at = None
        AgentEvent.append_status(session, run, "queued")
        record_event(
            session,
            self.owner_id,
            request_id,
            "agent_question.answered",
            self.__tablename__,
            self.id,
            run_id=str(self.run_id),
            interrupt_id=self.interrupt_id,
        )
        return self

    @classmethod
    def cancel_for_run(cls, session: Session, run_id: UUID, *, request_id: UUID) -> None:
        for question in session.scalars(
            select(cls).where(cls.run_id == run_id, cls.state.in_(("open", "answered")))
        ):
            question.state = "cancelled"
            question.updated_at = utc_now()
            record_event(
                session,
                question.owner_id,
                request_id,
                "agent_question.cancelled",
                cls.__tablename__,
                question.id,
                run_id=str(run_id),
                interrupt_id=question.interrupt_id,
            )
        for intent in session.scalars(
            select(AgentResumeIntent).where(
                AgentResumeIntent.run_id == run_id,
                AgentResumeIntent.state == "pending",
            )
        ):
            intent.state = "cancelled"
            intent.applied_at = utc_now()


class AgentResumeIntent(Base):
    """Immutable answer plus mutable delivery state for one exact saver interrupt."""

    __tablename__ = "agent_resume_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["question_id", "owner_id"],
            ["agent_questions.id", "agent_questions.owner_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("question_id"),
        CheckConstraint("state IN ('pending', 'applied', 'cancelled')", name="state"),
        Index("ix_agent_resume_intents_run_state", "run_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    question_id: Mapped[UUID] = mapped_column(Uuid)
    interrupt_id: Mapped[str] = mapped_column(String(100))
    answer: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
