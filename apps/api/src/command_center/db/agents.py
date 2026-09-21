"""Durable execution records, separate from human tasks."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, String, Text, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import OwnedRecord, record_event
from command_center.db.errors import RecordConflict


class AgentRun(OwnedRecord, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="state"
        ),
    )
    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    profile: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    def tool_steps(self) -> list[dict[str, Any]]:
        """Public execution evidence, without system instructions or hidden model reasoning."""
        steps: dict[str, dict[str, Any]] = {}
        for message in self.checkpoint.get("messages", []):
            data = message.get("data", {})
            if message.get("type") == "ai":
                for call in data.get("tool_calls", []):
                    call_id = call.get("id")
                    if call_id:
                        steps[call_id] = {
                            "id": call_id,
                            "name": call["name"],
                            "state": "input-available",
                            "output": None,
                        }
            elif message.get("type") == "tool" and data.get("tool_call_id") in steps:
                step = steps[data["tool_call_id"]]
                output = str(data.get("content", ""))[:20000]
                step["output"] = output
                step["state"] = (
                    "output-error"
                    if output.startswith(("Denied:", "Tool unavailable"))
                    else "output-available"
                )
        return list(steps.values())

    @classmethod
    def enqueue(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        prompt: str,
        profile: str,
        configuration: dict[str, Any],
        revision: str,
        request_id: UUID,
    ) -> "AgentRun":
        run = cls(
            id=record_id,
            owner_id=owner_id,
            title=prompt[:100],
            prompt=prompt,
            profile=profile,
            config_snapshot={"profile": configuration, "revision": revision},
        )
        session.add(run)
        record_event(
            session,
            owner_id,
            request_id,
            "agent.queued",
            "agent_runs",
            record_id,
            profile=profile,
            revision=revision,
        )
        return run

    @classmethod
    def expire_stale(cls, session: Session) -> None:
        stale = session.scalars(
            select(cls)
            .where(cls.state == "running", cls.lease_expires_at < utc_now())
            .with_for_update(skip_locked=True)
        ).all()
        for expired in stale:
            expired.finish("failed", error_code="worker_interrupted")

    @classmethod
    def claim(cls, session: Session, run_id: UUID | None = None) -> "AgentRun | None":
        cls.expire_stale(session)
        statement = (
            select(cls)
            .where(cls.state == "queued")
            .order_by(cls.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run_id:
            statement = statement.where(cls.id == run_id)
        run = session.scalar(statement)
        if run:
            run.state = "running"
            run.lease_id = uuid4()
            run.lease_expires_at = utc_now() + timedelta(minutes=5)
            record_event(
                session,
                run.owner_id,
                run.id,
                "agent.started",
                "agent_runs",
                run.id,
                profile=run.profile,
            )
        return run

    def finish(
        self, state: str, *, output: str | None = None, error_code: str | None = None
    ) -> None:
        if state not in {"completed", "failed", "cancelled"}:
            raise ValueError("Invalid terminal agent state")
        if self.state not in {"queued", "running"}:
            raise RecordConflict("This run has already finished")
        self.state, self.output, self.error_code = state, output, error_code
        self.completed_at, self.lease_id, self.lease_expires_at = utc_now(), None, None
        session = object_session(self)
        if session:
            record_event(
                session,
                self.owner_id,
                self.id,
                f"agent.{state}",
                "agent_runs",
                self.id,
                error_code=error_code,
            )
