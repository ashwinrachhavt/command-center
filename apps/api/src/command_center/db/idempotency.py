"""Persist request identity and results atomically with domain changes."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import ForeignKey, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now


class IdempotencyConflict(ValueError):
    pass


class RequestReceipt(Base):
    __tablename__ = "request_receipts"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), primary_key=True)
    key: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    operation: Mapped[str] = mapped_column(String(300))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @classmethod
    def execute(
        cls,
        session: Session,
        *,
        actor_id: UUID,
        key: UUID,
        operation: str,
        payload: dict[str, Any],
        change: Callable[[UUID], dict[str, Any]],
    ) -> dict[str, Any]:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        lock = int.from_bytes(
            hashlib.sha256(f"{actor_id}:{key}".encode()).digest()[:8], signed=True
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        receipt = session.get(cls, (actor_id, key))
        if receipt:
            if receipt.operation != operation or receipt.request_hash != digest:
                raise IdempotencyConflict(
                    "This idempotency key was already used with different input"
                )
            return receipt.response
        row_id = uuid5(NAMESPACE_URL, f"command-center:{actor_id}:{operation}:{key}")
        result = change(row_id)
        session.flush()
        session.add(
            cls(
                actor_id=actor_id,
                key=key,
                operation=operation,
                request_hash=digest,
                response=result,
            )
        )
        session.flush()
        return result
