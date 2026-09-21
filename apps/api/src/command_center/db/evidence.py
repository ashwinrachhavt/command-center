"""Source observations and claims are evidence, not automatically approved facts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    artifact_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifact_versions.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100))
    account_scope: Mapped[str] = mapped_column(String(200))
    locator: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    extraction_method: Mapped[str] = mapped_column(String(100))


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"
    __table_args__ = (
        CheckConstraint("confidence IN ('unknown', 'low', 'medium', 'high')", name="confidence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_record_id: Mapped[UUID] = mapped_column(ForeignKey("source_records.id"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    source_span: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="unknown")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class TaskEvidence(Base):
    __tablename__ = "task_evidence"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    evidence_claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_claims.id"), primary_key=True, index=True
    )
