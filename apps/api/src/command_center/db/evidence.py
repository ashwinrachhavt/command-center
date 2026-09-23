"""Source observations and claims are evidence, not automatically approved facts."""

from datetime import datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), index=True)
    artifact_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifact_versions.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100))
    account_scope: Mapped[str] = mapped_column(String(200))
    locator: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    extraction_method: Mapped[str] = mapped_column(String(100))

    @classmethod
    def capture_for_opportunity(
        cls,
        session: Session,
        *,
        record_id: UUID,
        opportunity_id: UUID,
        owner_id: UUID,
        title: str,
        url: str,
        text: str,
        provider: str,
        extraction_method: str,
        request_id: UUID,
        sensitivity: str = "public",
        account_scope: str = "public",
        source_version_ids: list[UUID] | None = None,
        source_message_id: UUID | None = None,
    ) -> "SourceRecord":
        """Persist an immutable source acquisition with its exact content and provenance."""
        from command_center.db.artifacts import Artifact
        from command_center.db.crm import record_event

        if (
            not title.strip()
            or not url.strip()
            or not provider.strip()
            or not extraction_method.strip()
        ):
            raise ValueError("Source provenance fields cannot be blank")
        artifact_id = uuid5(record_id, "artifact")
        artifact = Artifact.draft(
            session,
            record_id=artifact_id,
            owner_id=owner_id,
            title=title,
            kind="source",
            sensitivity=sensitivity,
            text=text,
            document_type_id=None,
            request_id=request_id,
            source_version_ids=source_version_ids,
        )
        source = cls(
            id=record_id,
            opportunity_id=opportunity_id,
            artifact_version_id=uuid5(artifact.id, "version:1"),
            provider=provider,
            account_scope=account_scope,
            locator=url,
            extraction_method=extraction_method,
        )
        session.add(source)
        record_event(
            session,
            owner_id,
            request_id,
            "opportunity.source_captured",
            "opportunities",
            opportunity_id,
            source_record_id=str(record_id),
            artifact_id=str(artifact_id),
            provider=provider,
            source_message_id=str(source_message_id) if source_message_id else None,
        )
        session.flush()
        return source


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
