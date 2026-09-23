"""Owned work conversations spanning durable agent runs."""

import hashlib
from datetime import timedelta
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
from sqlalchemy.dialects.postgresql import JSONB
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
        Index("ix_agent_sessions_owner_activity", "owner_id", "updated_at", "id"),
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
    context_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

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
        fresh_answer: bool = False,
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
        if fresh_answer:
            active.config_snapshot = {**active.config_snapshot, "fresh_answer": True}
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
        answer_cache: dict[str, Any] | None = None,
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
            answer_cache=answer_cache,
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

    def save_summary(
        self,
        *,
        run: "AgentRun",
        lease_id: UUID,
        expected_revision: int,
        summary: str,
        covered_ids: list[str],
    ) -> int:
        """Publish only a proven transcript prefix under the producing lease and CAS."""
        from command_center.agents.answer_cache import configuration_digest, digest

        session = object_session(self)
        if session is None:
            raise ValueError("Conversation must belong to a transaction")
        session.refresh(run, with_for_update={"key_share": True})
        if (
            run.owner_id != self.owner_id
            or run.session_id != self.id
            or run.state != "running"
            or run.lease_id != lease_id
            or run.lease_expires_at is None
            or run.lease_expires_at <= utc_now()
        ):
            raise RecordConflict("The producing run is no longer authorized")
        session.refresh(self, with_for_update=True)
        prior = self.context_summary or {}
        if int(prior.get("revision", 0)) != expected_revision:
            raise RecordConflict("Conversation summary changed")
        if not summary.strip() or len(summary) > 10000:
            raise ValueError("Summary must be nonempty and bounded")
        rows = session.scalars(
            select(AgentMessage)
            .where(AgentMessage.session_id == self.id, AgentMessage.owner_id == self.owner_id)
            .order_by(AgentMessage.sequence)
        ).all()
        config_digest = configuration_digest(run.config_snapshot)
        previous = (
            int(prior.get("covered_sequence", 0))
            if prior.get("configuration") == config_digest
            else 0
        )
        included = set(covered_ids)
        prefix = [row for row in rows if row.sequence <= previous]
        if prefix and prior.get("source_digest") != digest(
            [(str(row.id), row.sequence, row.content) for row in prefix]
        ):
            previous, prefix = 0, []
        for row in rows:
            if row.sequence <= previous:
                continue
            if str(row.id) not in included:
                break
            prefix.append(row)
        covered = prefix[-1].sequence if prefix else 0
        if covered <= previous:
            return expected_revision
        self.context_summary = {
            "revision": expected_revision + 1,
            "covered_sequence": covered,
            "source_digest": digest([(str(row.id), row.sequence, row.content) for row in prefix]),
            "configuration": config_digest,
            "summary": summary,
            "run_id": str(run.id),
            "created_at": utc_now().isoformat(),
        }
        record_event(
            session,
            self.owner_id,
            run.id,
            "agent_session.compacted",
            self.__tablename__,
            self.id,
            covered_sequence=covered,
            summary_revision=expected_revision + 1,
        )
        return expected_revision + 1

    def cache_candidate(self, run: "AgentRun") -> dict[str, Any] | None:
        """Proven first-exchange text-only answer; no mutable workspace dependencies."""
        from command_center.agents.answer_cache import (
            CACHE_REVISION,
            CACHE_TTL_SECONDS,
            cacheable_request,
            configuration_digest,
            digest,
            read_only_trace,
        )
        from command_center.db.agent_questions import AgentQuestion

        if (
            run.owner_id != self.owner_id
            or run.session_id != self.id
            or self.archived_at is not None
            or self.task_id is not None
            or self.opportunity_id is not None
            or self.context_summary is not None
            or run.archived_at is not None
            or run.state != "completed"
            or run.input_sequence != 1
            or run.consumed_sequence != 1
            or run.completed_at is None
            or not run.output
            or not cacheable_request(run.prompt)
            or not read_only_trace(run.checkpoint)
        ):
            return None
        session = object_session(self)
        if session is None:
            return None
        if session.scalar(select(AgentQuestion.id).where(AgentQuestion.run_id == run.id).limit(1)):
            return None
        rows = session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.session_id == self.id,
                AgentMessage.owner_id == self.owner_id,
                AgentMessage.sequence <= 2,
            )
            .order_by(AgentMessage.sequence)
        ).all()
        if len(rows) != 2:
            return None
        source, answer = rows
        if (
            source.author != "user"
            or answer.author != "assistant"
            or source.run_id != run.id
            or answer.run_id != run.id
            or source.content != run.prompt
            or answer.content != run.output
            or source.archived_at is not None
            or answer.archived_at is not None
        ):
            return None
        return {
            "policy": CACHE_REVISION,
            "owner_id": str(self.owner_id),
            "session_id": str(self.id),
            "source_run_id": str(run.id),
            "source_message_id": str(source.id),
            "source_digest": digest(source.content),
            "output_digest": digest(answer.content),
            "source_row_version": source.row_version,
            "answer_row_version": answer.row_version,
            "predecessor_digest": digest([]),
            "summary_revision": 0,
            "configuration": configuration_digest(run.config_snapshot),
            "source_completed_at": run.completed_at.isoformat(),
            "expires_at": (run.completed_at + timedelta(seconds=CACHE_TTL_SECONDS)).isoformat(),
        }

    def reuse_answer(self, run: "AgentRun") -> bool:
        """Finish an immediate duplicate under the normal worker lease, with zero usage."""
        from datetime import datetime

        from command_center.agents.answer_cache import configuration_digest
        from command_center.db.agent_questions import AgentQuestion
        from command_center.db.agents import AgentRun

        if (
            run.owner_id != self.owner_id
            or run.session_id != self.id
            or run.state != "running"
            or run.lease_id is None
            or run.lease_expires_at is None
            or run.lease_expires_at <= utc_now()
            or run.input_sequence != 3
            or run.config_snapshot.get("fresh_answer")
            or run.checkpoint
        ):
            return False
        session = object_session(self)
        if session is None:
            return False
        session.refresh(self, with_for_update=True)
        if self.last_sequence != 3:
            return False
        rows = session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.session_id == self.id,
                AgentMessage.owner_id == self.owner_id,
            )
            .order_by(AgentMessage.sequence)
        ).all()
        if len(rows) != 3:
            return False
        original, answer, repeated = rows
        if (
            original.author != "user"
            or answer.author != "assistant"
            or repeated.author != "user"
            or repeated.run_id != run.id
            or repeated.content.strip() != original.content.strip()
            or repeated.content != run.prompt
            or repeated.archived_at is not None
        ):
            return False
        source = session.get(AgentRun, original.run_id)
        if source is None or answer.run_id != source.id:
            return False
        entry = source.checkpoint.get("answer_cache_entry")
        if (
            not isinstance(entry, dict)
            or entry != self.cache_candidate(source)
            or entry["configuration"] != configuration_digest(run.config_snapshot)
            or datetime.fromisoformat(entry["expires_at"]) <= utc_now()
            or session.scalar(
                select(AgentQuestion.id).where(AgentQuestion.run_id == run.id).limit(1)
            )
        ):
            return False
        marker = {key: entry[key] for key in ("source_run_id", "source_completed_at", "expires_at")}
        run.consumed_sequence = repeated.sequence
        run.checkpoint = {
            "steps": 0,
            "tool_count": 0,
            "tools": [],
            "instruction_sequence": repeated.sequence,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "answer_cache": marker,
        }
        run.finish("completed", output=source.output)
        record_event(
            session,
            self.owner_id,
            run.id,
            "agent.answer_reused",
            "agent_runs",
            run.id,
            source_run_id=str(source.id),
        )
        return True


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
    answer_cache: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
