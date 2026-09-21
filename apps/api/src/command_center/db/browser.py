"""Revocable browser devices and explicit, site-bound fill proposals."""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class BrowserDevice(Base):
    __tablename__ = "browser_devices"
    __table_args__ = (UniqueConstraint("id", "owner_id"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    pairing_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    pairing_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    token_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    paired_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @classmethod
    def pair(
        cls, session: Session, *, device_id: UUID, owner_id: UUID, name: str, request_id: UUID
    ) -> tuple["BrowserDevice", str]:
        code = secrets.token_urlsafe(32)
        device = cls(
            id=device_id,
            owner_id=owner_id,
            name=name,
            pairing_digest=digest(code),
            pairing_expires_at=utc_now() + timedelta(minutes=5),
        )
        session.add(device)
        record_event(
            session, owner_id, request_id, "browser.pairing_created", "browser_devices", device_id
        )
        return device, code

    @classmethod
    def redeem(
        cls, session: Session, code: str, *, request_id: UUID
    ) -> tuple["BrowserDevice", str]:
        device = session.scalar(
            select(cls)
            .where(
                cls.pairing_digest == digest(code),
                cls.revoked_at.is_(None),
                cls.pairing_expires_at > utc_now(),
            )
            .with_for_update()
        )
        if device is None:
            raise ValueError("Pairing code is invalid, expired or already used")
        token = secrets.token_urlsafe(48)
        device.token_digest, device.pairing_digest, device.paired_at = (
            digest(token),
            None,
            utc_now(),
        )
        record_event(
            session, device.owner_id, request_id, "browser.paired", "browser_devices", device.id
        )
        return device, token

    def revoke(self, *, request_id: UUID) -> None:
        if self.revoked_at:
            return
        self.revoked_at, self.token_digest, self.pairing_digest = utc_now(), None, None
        session = object_session(self)
        if session:
            record_event(
                session, self.owner_id, request_id, "browser.revoked", "browser_devices", self.id
            )


class BrowserSnapshot(Base):
    __tablename__ = "browser_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "device_id", "owner_id"),
        ForeignKeyConstraint(
            ["device_id", "owner_id"], ["browser_devices.id", "browser_devices.owner_id"]
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    origin: Mapped[str] = mapped_column(String(500))
    page_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300))
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @classmethod
    def capture(
        cls,
        session: Session,
        device: BrowserDevice,
        *,
        snapshot_id: UUID,
        page_url: str,
        title: str,
        fields: list[dict[str, Any]],
        request_id: UUID,
    ) -> "BrowserSnapshot":
        parsed = urlsplit(page_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Share only the page origin and path")
        if len({field["id"] for field in fields}) != len(fields):
            raise ValueError("Field IDs must be unique")
        existing = session.get(cls, snapshot_id)
        if existing:
            if (
                existing.device_id != device.id
                or existing.fields != fields
                or existing.page_url != page_url
                or existing.title != title
            ):
                raise RecordConflict("Snapshot ID already exists")
            return existing
        snapshot = cls(
            id=snapshot_id,
            device_id=device.id,
            owner_id=device.owner_id,
            origin=f"{parsed.scheme}://{parsed.netloc}",
            page_url=page_url,
            title=title,
            fields=fields,
        )
        session.add(snapshot)
        record_event(
            session,
            device.owner_id,
            request_id,
            "browser.form_shared",
            "browser_snapshots",
            snapshot_id,
            field_count=len(fields),
            origin=snapshot.origin,
        )
        return snapshot

    def propose_fill(
        self,
        *,
        command_id: UUID,
        fields: dict[str, str],
        request_id: UUID,
    ) -> "BrowserCommand":
        session = object_session(self)
        if session is None:
            raise ValueError("Share a form first")
        device = session.get(BrowserDevice, self.device_id)
        if not device or device.revoked_at or self.created_at < utc_now() - timedelta(minutes=30):
            raise RecordConflict("Share a fresh form from a paired browser")
        known = {field["id"]: field for field in self.fields}
        for field_id, value in fields.items():
            field = known.get(field_id)
            if (
                not field
                or len(value) > 5000
                or (field["type"] == "select" and value not in field["options"])
            ):
                raise ValueError("Use valid values for fields in this snapshot")
        command = BrowserCommand(
            id=command_id,
            owner_id=self.owner_id,
            device_id=self.device_id,
            snapshot_id=self.id,
            fields=fields,
            expires_at=utc_now() + timedelta(minutes=10),
        )
        session.add(command)
        record_event(
            session,
            self.owner_id,
            request_id,
            "browser.fill_proposed",
            "browser_commands",
            command_id,
            origin=self.origin,
            field_count=len(fields),
        )
        return command


class BrowserCommand(Base):
    __tablename__ = "browser_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "device_id", "owner_id"],
            ["browser_snapshots.id", "browser_snapshots.device_id", "browser_snapshots.owner_id"],
        ),
        CheckConstraint(
            "state IN ('pending', 'claimed', 'applied', 'rejected', 'failed', 'outcome_unknown')",
            name="state",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    device_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid)
    fields: Mapped[dict[str, str]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    def expire(self, *, request_id: UUID) -> None:
        if self.state in {"pending", "claimed"} and self.expires_at <= utc_now():
            self._finish("outcome_unknown" if self.state == "claimed" else "rejected", request_id)

    def claim(self, *, request_id: UUID) -> None:
        if self.state != "pending" or self.expires_at <= utc_now():
            raise RecordConflict(
                "This command has already been claimed or expired; do not replay it"
            )
        self.state = "claimed"
        session = object_session(self)
        if session:
            record_event(
                session,
                self.owner_id,
                request_id,
                "browser.fill_claimed",
                "browser_commands",
                self.id,
            )

    def report(self, state: str, *, request_id: UUID) -> None:
        if state not in {"applied", "rejected", "failed", "outcome_unknown"}:
            raise ValueError("Invalid fill outcome")
        if self.state == state:
            return
        if self.state != "claimed":
            raise RecordConflict("Only a claimed command can receive an outcome")
        self._finish(state, request_id)

    def _finish(self, state: str, request_id: UUID) -> None:
        self.state, self.completed_at = state, utc_now()
        session = object_session(self)
        if session:
            record_event(
                session,
                self.owner_id,
                request_id,
                f"browser.fill_{state}",
                "browser_commands",
                self.id,
            )
