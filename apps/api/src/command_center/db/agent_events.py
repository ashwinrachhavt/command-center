"""Durable, owner-scoped public activity for one agent run."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Uuid,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.errors import RecordConflict

EVENT_TYPES = frozenset(
    {
        "text-delta",
        "tool-input-available",
        "tool-output-available",
        "tool-output-error",
        "usage",
        "run-status",
    }
)
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_SECRET_KEYS = ("authorization", "cookie", "password", "secret", "token", "api_key")


def public_input(value: Any, *, depth: int = 0) -> Any:
    """Keep event input JSON bounded and redact credential-shaped fields."""
    if depth >= 8:
        return "[nested input omitted]"
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:100]:
            name = str(key)[:200]
            result[name] = (
                "[redacted]"
                if any(secret in name.lower() for secret in _SECRET_KEYS)
                else public_input(item, depth=depth + 1)
            )
        return result
    if isinstance(value, list):
        return [public_input(item, depth=depth + 1) for item in value[:100]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:20_000]


def validate_event(event_type: str, role: str, data: dict[str, Any]) -> dict[str, Any]:
    if event_type not in EVENT_TYPES or not role.strip() or len(role) > 100:
        raise ValueError("Invalid agent event")
    required = {
        "text-delta": {"message_id", "delta"},
        "tool-input-available": {"tool_call_id", "tool_name", "input"},
        "tool-output-available": {"tool_call_id", "output"},
        "tool-output-error": {"tool_call_id", "error_text"},
        "usage": {"input_tokens", "output_tokens", "total_tokens"},
        "run-status": {"state"},
    }[event_type]
    allowed = required | ({"error_code"} if event_type == "run-status" else set())
    if set(data) != required and not (set(data) == allowed and data.get("error_code")):
        raise ValueError("Invalid agent event payload")
    if event_type == "text-delta":
        if not str(data["message_id"]).strip() or not isinstance(data["delta"], str):
            raise ValueError("Invalid text delta")
        if not data["delta"] or len(data["delta"]) > 8_000:
            raise ValueError("Invalid text delta")
    elif event_type.startswith("tool-"):
        if not str(data["tool_call_id"]).strip():
            raise ValueError("Invalid tool event")
        if event_type == "tool-input-available" and not str(data["tool_name"]).strip():
            raise ValueError("Invalid tool event")
    elif event_type == "usage":
        counts = [data[name] for name in ("input_tokens", "output_tokens", "total_tokens")]
        if any(not isinstance(count, int) or count < 0 for count in counts):
            raise ValueError("Invalid usage event")
        if data["total_tokens"] != data["input_tokens"] + data["output_tokens"]:
            raise ValueError("Invalid usage event")
    elif data["state"] not in {"running", *TERMINAL_STATES}:
        raise ValueError("Invalid run status")
    normalized = public_input(data)
    if len(json.dumps(normalized, separators=(",", ":"), default=str)) > 24_000:
        if event_type == "tool-input-available":
            normalized["input"] = {"summary": "Tool input omitted because it exceeded the limit"}
        else:
            raise ValueError("Agent event payload is too large")
    assert isinstance(normalized, dict)
    return normalized


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("sequence > 0", name="sequence"),
        CheckConstraint(
            "type IN ('text-delta', 'tool-input-available', 'tool-output-available', "
            "'tool-output-error', 'usage', 'run-status')",
            name="type",
        ),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="data_object"),
        Index("ix_agent_events_owner_run_sequence", "owner_id", "run_id", "sequence"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    type: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    def envelope(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "run_id": str(self.run_id),
            "type": self.type,
            "role": self.role,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def _append_locked(
        cls,
        session: Session,
        run: Any,
        events: list[tuple[str, str, dict[str, Any]]],
    ) -> list["AgentEvent"]:
        sequence = session.scalar(select(func.max(cls.sequence)).where(cls.run_id == run.id)) or 0
        rows = []
        for event_type, role, data in events:
            sequence += 1
            row = cls(
                run_id=run.id,
                owner_id=run.owner_id,
                sequence=sequence,
                type=event_type,
                role=role.strip(),
                data=validate_event(event_type, role, data),
            )
            session.add(row)
            rows.append(row)
        return rows

    @classmethod
    def append(
        cls,
        session: Session,
        *,
        run_id: UUID,
        lease_id: UUID,
        events: list[tuple[str, str, dict[str, Any]]],
    ) -> list["AgentEvent"]:
        """Serialize sequence allocation on the run and fence the exact worker lease."""
        from command_center.db.agents import AgentRun

        run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if (
            run is None
            or run.state != "running"
            or run.lease_id != lease_id
            or run.lease_expires_at is None
            or run.lease_expires_at <= utc_now()
        ):
            raise RecordConflict("The agent run lease is no longer active")
        return cls._append_locked(session, run, events)

    @classmethod
    def append_status(cls, session: Session, run: Any, state: str) -> "AgentEvent":
        data = {"state": state}
        if run.error_code:
            data["error_code"] = run.error_code
        return cls._append_locked(
            session,
            run,
            [("run-status", run.profile, data)],
        )[0]

    @classmethod
    def page(
        cls,
        session: Session,
        *,
        run_id: UUID,
        owner_id: UUID,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[list["AgentEvent"], bool]:
        from command_center.db.agents import AgentRun

        run = session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.owner_id == owner_id)
        )
        if run is None:
            return [], True
        rows = session.scalars(
            select(cls)
            .where(cls.run_id == run_id, cls.sequence > after_sequence)
            .order_by(cls.sequence)
            .limit(limit)
        ).all()
        return list(rows), run.state in TERMINAL_STATES and len(rows) < limit
