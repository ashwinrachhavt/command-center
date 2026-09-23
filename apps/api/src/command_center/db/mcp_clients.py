"""Individually revocable credentials for local MCP clients, never human sessions."""

import hashlib
import secrets
from datetime import datetime, timedelta
from hmac import compare_digest
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.models import Actor


class MCPClientCredential(Base):
    __tablename__ = "mcp_client_credentials"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @classmethod
    def provision(
        cls, session: Session, owner_id: UUID, name: str, expires_in_days: int, request_id: UUID
    ) -> tuple["MCPClientCredential", str]:
        if not name.strip() or not 1 <= expires_in_days <= 365:
            raise ValueError("A client name and expiry from 1 to 365 days are required")
        record_id = uuid4()
        token = f"cc_local.{record_id}.{secrets.token_urlsafe(32)}"
        record = cls(
            id=record_id,
            owner_id=owner_id,
            name=name.strip(),
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=utc_now() + timedelta(days=expires_in_days),
        )
        session.add(record)
        session.flush()
        record_event(
            session, owner_id, request_id, "mcp_client.created", cls.__tablename__, record_id
        )
        return record, token

    @classmethod
    def active(
        cls, session: Session, client_id: UUID, *, lock: bool = False
    ) -> "MCPClientCredential":
        statement = select(cls).where(cls.id == client_id)
        if lock:
            statement = statement.with_for_update(read=True)
        record = session.scalar(statement)
        if record is None or record.revoked_at is not None or record.expires_at <= utc_now():
            raise ValueError("Local MCP credential is invalid, expired or revoked")
        actor = session.get(Actor, record.owner_id)
        if actor is None or not actor.active:
            raise ValueError("Workspace is inactive")
        return record

    @classmethod
    def authenticate(cls, session: Session, token: str) -> "MCPClientCredential":
        try:
            prefix, client_id, secret = token.split(".")
            if prefix != "cc_local" or len(secret) < 32:
                raise ValueError("Invalid credential")
            record = cls.active(session, UUID(client_id))
            if not compare_digest(record.token_hash, hashlib.sha256(token.encode()).hexdigest()):
                raise ValueError("Invalid credential")
            return record
        except (ValueError, AttributeError) as exc:
            raise ValueError("Local MCP credential is invalid, expired or revoked") from exc

    def revoke(self, session: Session, request_id: UUID) -> None:
        if self.revoked_at is None:
            self.revoked_at = utc_now()
            record_event(
                session,
                self.owner_id,
                request_id,
                "mcp_client.revoked",
                self.__tablename__,
                self.id,
            )
