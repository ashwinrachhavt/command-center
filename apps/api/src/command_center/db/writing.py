"""Mutable writing space; meaningful checkpoints use existing artifact/action versions."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    delete,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict


class WritingDraft(Base):
    """One current draft with optimistic edits and one retained save receipt.

    Clearing keeps a tombstone/revision: an old tab cannot recreate or erase a newer
    draft using a reused revision number. Autosaves do not accumulate whole-content
    receipt history or manufacture approved versions.
    """

    __tablename__ = "writing_drafts"
    __table_args__ = (
        UniqueConstraint("owner_id", "scope_key"),
        CheckConstraint("row_version >= 0", name="row_version"),
        CheckConstraint("length(scope_key) BETWEEN 1 AND 200", name="scope_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    scope_key: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    row_version: Mapped[int] = mapped_column(Integer, default=0)
    last_save_key: Mapped[UUID | None] = mapped_column(Uuid)
    last_save_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def save(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        scope_key: str,
        data: dict[str, Any] | None,
        expected_version: int,
        save_key: UUID,
        request_id: UUID,
    ) -> "WritingDraft":
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 1_000_000:
            raise ValueError("Draft is too large; keep it under 1 MB")
        digest = hashlib.sha256(f"{expected_version}:{encoded}".encode()).hexdigest()
        record_id = uuid5(owner_id, f"writing-draft:{scope_key}")
        session.execute(
            insert(cls)
            .values(
                id=record_id,
                owner_id=owner_id,
                scope_key=scope_key,
                data=None,
                row_version=0,
                updated_at=utc_now(),
            )
            .on_conflict_do_nothing(index_elements=["owner_id", "scope_key"])
        )
        draft = session.scalar(select(cls).where(cls.id == record_id).with_for_update())
        assert draft is not None
        if draft.last_save_key == save_key:
            if draft.last_save_hash != digest:
                raise RecordConflict("This save identity belongs to different draft content")
            return draft
        if draft.row_version != expected_version:
            raise RecordConflict(
                "The saved draft changed in another tab. Your local writing is still available."
            )
        starting = draft.data is None and data is not None
        if data is None:
            draft.keep_recovery(session, force=True)
        draft.data = data
        draft.last_save_key = save_key
        draft.last_save_hash = digest
        draft.updated_at = utc_now()
        session.flush()
        if data is not None:
            draft.keep_recovery(session, force=starting)
        if expected_version == 0 or data is None:
            record_event(
                session,
                owner_id,
                request_id,
                "writing_draft.cleared" if data is None else "writing_draft.started",
                "writing_drafts",
                draft.id,
                scope_key=scope_key,
            )
        return draft

    def keep_recovery(self, session: Session, *, force: bool = False) -> None:
        """Bounded working copies, never reviewed artifact/action checkpoints."""
        if self.data is None:
            return
        latest = session.scalar(
            select(WritingRecoveryCopy)
            .where(WritingRecoveryCopy.draft_id == self.id)
            .order_by(WritingRecoveryCopy.row_version.desc())
            .limit(1)
        )
        now = utc_now()
        if latest is not None and (
            latest.row_version == self.row_version
            or (not force and now - latest.created_at < timedelta(minutes=5))
        ):
            return
        session.add(
            WritingRecoveryCopy(
                id=uuid5(self.id, f"recovery:{self.row_version}"),
                draft_id=self.id,
                row_version=self.row_version,
                data=self.data,
                created_at=now,
            )
        )
        session.flush()
        oldest = (
            select(WritingRecoveryCopy.id)
            .where(WritingRecoveryCopy.draft_id == self.id)
            .order_by(WritingRecoveryCopy.row_version.desc())
            .offset(20)
        )
        session.execute(delete(WritingRecoveryCopy).where(WritingRecoveryCopy.id.in_(oldest)))


class WritingRecoveryCopy(Base):
    """The last twenty periodic working copies; source versions retain their own identity."""

    __tablename__ = "writing_recovery_copies"
    __table_args__ = (UniqueConstraint("draft_id", "row_version"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    draft_id: Mapped[UUID] = mapped_column(ForeignKey("writing_drafts.id"))
    row_version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
