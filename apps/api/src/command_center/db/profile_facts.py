"""Actor-owned candidate facts with immutable proposal and review history."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
    text,
    update,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.career import decode_career
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict

FACT_FIELDS = frozenset(
    {
        "full_name",
        "first_name",
        "last_name",
        "address_line1",
        "address_line2",
        "city",
        "region",
        "postal_code",
        "country",
        "github",
        "email",
        "phone",
        "location",
        "headline",
        "website",
        "linkedin",
        "summary",
        "skill",
        "experience",
        "education",
        "certification",
        "project",
        "course",
        "language",
        "publication",
        "recommendation",
        "answer",
    }
)
SCALAR_FACT_FIELDS = frozenset(
    {
        "full_name",
        "email",
        "phone",
        "location",
        "headline",
        "website",
        "linkedin",
        "summary",
        "first_name",
        "last_name",
        "address_line1",
        "address_line2",
        "city",
        "region",
        "postal_code",
        "country",
        "github",
    }
)
TEXT_SOURCE_SCHEMAS = frozenset({"text.v1", "docling.document.v1"})
FactField = Literal[
    "full_name",
    "first_name",
    "last_name",
    "address_line1",
    "address_line2",
    "city",
    "region",
    "postal_code",
    "country",
    "github",
    "email",
    "phone",
    "location",
    "headline",
    "website",
    "linkedin",
    "summary",
    "skill",
    "experience",
    "education",
    "certification",
    "project",
    "course",
    "language",
    "publication",
    "recommendation",
    "answer",
]
ReviewState = Literal["proposed", "approved", "rejected", "revoked"]
ReviewDecision = Literal["approved", "rejected", "revoked"]


class ProfileFact(Base):
    """Mutable identity pointers over immutable candidate fact revisions."""

    __tablename__ = "profile_facts"
    __table_args__ = (
        CheckConstraint(
            "field IN ('full_name', 'email', 'phone', 'location', 'headline', 'website', "
            "'linkedin', 'summary', 'skill', 'experience', 'education', 'answer', "
            "'certification', 'project', 'course', 'language', 'publication', 'recommendation', "
            "'first_name', 'last_name', 'address_line1', 'address_line2', "
            "'city', 'region', 'postal_code', 'country', 'github')",
            name="field",
        ),
        CheckConstraint("row_version >= 1", name="row_version"),
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["current_revision_id", "id"],
            ["profile_fact_revisions.id", "profile_fact_revisions.fact_id"],
            name="fk_profile_facts_current_revision",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["active_revision_id", "id"],
            ["profile_fact_revisions.id", "profile_fact_revisions.fact_id"],
            name="fk_profile_facts_active_revision",
            use_alter=True,
        ),
        Index(
            "uq_profile_facts_active_scalar",
            "owner_id",
            "field",
            unique=True,
            postgresql_where=text(
                "active_revision_id IS NOT NULL AND field IN "
                "('full_name', 'email', 'phone', 'location', 'headline', 'website', "
                "'linkedin', 'summary', 'first_name', 'last_name', "
                "'address_line1', 'address_line2', "
                "'city', 'region', 'postal_code', 'country', 'github')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    field: Mapped[FactField] = mapped_column(String(30), index=True)
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    active_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def propose(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        field: FactField,
        value: str,
        context: str | None,
        source_version_id: UUID | None,
        source_excerpt: str | None,
        valid_until: datetime | None,
        agent_proposal: bool,
        request_id: UUID,
    ) -> "ProfileFact":
        cls._validate_content(field, value, context)
        artifact_id = cls._validate_source(
            session,
            owner_id=owner_id,
            source_version_id=source_version_id,
            source_excerpt=source_excerpt,
            required=agent_proposal,
        )
        fact = cls(id=record_id, owner_id=owner_id, field=field)
        session.add(fact)
        session.flush()
        revision = ProfileFactRevision(
            fact_id=fact.id,
            version=1,
            value=value,
            context=context,
            source_version_id=source_version_id,
            source_artifact_id=artifact_id,
            source_excerpt=source_excerpt,
            valid_until=valid_until,
        )
        session.add(revision)
        session.flush()
        # Initial pointer wiring is part of creation, not a later optimistic edit.
        session.execute(
            update(ProfileFact)
            .where(ProfileFact.id == fact.id)
            .values(current_revision_id=revision.id),
            execution_options={"synchronize_session": False},
        )
        session.refresh(fact)
        record_event(
            session,
            owner_id,
            request_id,
            "profile_fact.proposed",
            "profile_facts",
            fact.id,
            field=field,
            revision_id=str(revision.id),
            agent_proposal=agent_proposal,
        )
        return fact

    def append_revision(
        self,
        *,
        value: str,
        context: str | None,
        source_version_id: UUID | None,
        source_excerpt: str | None,
        valid_until: datetime | None,
        agent_proposal: bool,
        request_id: UUID,
    ) -> "ProfileFactRevision":
        session = object_session(self)
        if session is None or self.current_revision_id is None:
            raise ValueError("Revise a persisted fact")
        self._validate_content(self.field, value, context)
        artifact_id = self._validate_source(
            session,
            owner_id=self.owner_id,
            source_version_id=source_version_id,
            source_excerpt=source_excerpt,
            required=agent_proposal,
        )
        current = session.get(ProfileFactRevision, self.current_revision_id)
        if current is None:
            raise ValueError("Fact current revision is missing")
        revision = ProfileFactRevision(
            fact_id=self.id,
            version=current.version + 1,
            value=value,
            context=context,
            source_version_id=source_version_id,
            source_artifact_id=artifact_id,
            source_excerpt=source_excerpt,
            valid_until=valid_until,
        )
        session.add(revision)
        session.flush()
        self.current_revision_id = revision.id
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "profile_fact.revised",
            "profile_facts",
            self.id,
            field=self.field,
            revision_id=str(revision.id),
            version=revision.version,
            agent_proposal=agent_proposal,
        )
        return revision

    def review(
        self,
        *,
        revision_id: UUID,
        reviewer_id: UUID,
        reviewer_is_human: bool,
        decision: ReviewDecision,
        reason: str | None,
        request_id: UUID,
    ) -> "ProfileFactReview":
        if not reviewer_is_human:
            raise PermissionError("Only a human can review candidate facts")
        if reviewer_id != self.owner_id:
            raise PermissionError("Only the fact owner can review candidate facts")
        if decision not in {"approved", "rejected", "revoked"}:
            raise ValueError("Unknown fact review decision")
        if reason is not None and len(reason) > 2000:
            raise ValueError("Review reason is too long")
        session = object_session(self)
        if session is None:
            raise ValueError("Review a persisted fact")
        revision = session.scalar(
            select(ProfileFactRevision).where(
                ProfileFactRevision.id == revision_id,
                ProfileFactRevision.fact_id == self.id,
            )
        )
        if revision is None:
            raise ValueError("Revision does not belong to this fact")
        state = revision.review_state(session)
        if decision == "revoked":
            if self.active_revision_id != revision.id or state != "approved":
                raise RecordConflict("Only the active approved revision can be revoked")
            self.active_revision_id = None
        else:
            if self.current_revision_id != revision.id or state != "proposed":
                raise RecordConflict("Only the current proposal can be reviewed")
            if decision == "approved":
                self._prevent_scalar_conflict(session)
                self.active_revision_id = revision.id
        review = ProfileFactReview(
            fact_id=self.id,
            revision_id=revision.id,
            reviewer_id=reviewer_id,
            decision=decision,
            reason=reason,
        )
        session.add(review)
        self.updated_at = utc_now()
        record_event(
            session,
            reviewer_id,
            request_id,
            "profile_fact.reviewed",
            "profile_facts",
            self.id,
            field=self.field,
            revision_id=str(revision.id),
            decision=decision,
        )
        return review

    def _prevent_scalar_conflict(self, session: Session) -> None:
        if self.field not in SCALAR_FACT_FIELDS:
            return
        conflict = session.scalar(
            select(ProfileFact.id)
            .where(
                ProfileFact.owner_id == self.owner_id,
                ProfileFact.field == self.field,
                ProfileFact.active_revision_id.is_not(None),
                ProfileFact.id != self.id,
            )
            .with_for_update()
        )
        if conflict is not None:
            raise RecordConflict("Resolve the existing active scalar fact before approving another")

    @staticmethod
    def _validate_content(field: FactField, value: str, context: str | None) -> None:
        if field not in FACT_FIELDS:
            raise ValueError("Unknown candidate fact field")
        if not 1 <= len(value) <= 4000 or not value.strip():
            raise ValueError("Fact value must contain 1 to 4000 characters")
        if context is not None and len(context) > 1000:
            raise ValueError("Fact context is too long")
        if field == "answer" and (context is None or not context.strip()):
            raise ValueError("Contextual answers require an explicit question or context")
        career = decode_career(value)
        if career is not None:
            if career.kind != field:
                raise ValueError("Career entry kind must match the profile fact field")
            if context is not None:
                raise ValueError("Structured career entries require global context")

    @staticmethod
    def _validate_source(
        session: Session,
        *,
        owner_id: UUID,
        source_version_id: UUID | None,
        source_excerpt: str | None,
        required: bool,
    ) -> UUID | None:
        if required and (source_version_id is None or not source_excerpt):
            raise ValueError("Agent proposals require textual source evidence")
        if source_excerpt is not None and source_version_id is None:
            raise ValueError("A source excerpt requires an exact source version")
        if source_excerpt is not None and len(source_excerpt) > 4000:
            raise ValueError("Source excerpt must contain 1 to 4000 characters")
        if source_version_id is None:
            return None
        version = session.get(ArtifactVersion, source_version_id)
        artifact = session.get(Artifact, version.artifact_id) if version else None
        if (
            version is None
            or artifact is None
            or artifact.owner_id != owner_id
            or version.schema_key not in TEXT_SOURCE_SCHEMAS
            or not isinstance(version.payload, dict)
            or not isinstance(version.payload.get("text"), str)
        ):
            raise ValueError("Choose an owned textual source version")
        source_text = version.payload["text"]
        assert isinstance(source_text, str)
        if source_excerpt is not None and source_excerpt not in source_text:
            raise ValueError("Source excerpt must occur verbatim in the selected version")
        return artifact.id


class ProfileFactRevision(Base):
    """Immutable proposal content; decisions live in append-only review rows."""

    __tablename__ = "profile_fact_revisions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("length(value) BETWEEN 1 AND 4000", name="value_length"),
        CheckConstraint("context IS NULL OR length(context) <= 1000", name="context_length"),
        CheckConstraint(
            "source_excerpt IS NULL OR length(source_excerpt) BETWEEN 1 AND 4000",
            name="excerpt_length",
        ),
        CheckConstraint(
            "source_excerpt IS NULL OR source_version_id IS NOT NULL", name="excerpt_source"
        ),
        UniqueConstraint("fact_id", "version"),
        UniqueConstraint("id", "fact_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fact_id: Mapped[UUID] = mapped_column(ForeignKey("profile_facts.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    value: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    source_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifact_versions.id"), index=True
    )
    source_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    def review_state(self, session: Session | None = None) -> ReviewState:
        current_session = session or object_session(self)
        if current_session is None:
            raise ValueError("Read review state from a persisted revision")
        decision = current_session.scalar(
            select(ProfileFactReview.decision)
            .where(ProfileFactReview.revision_id == self.id)
            .order_by(ProfileFactReview.created_at.desc(), ProfileFactReview.id.desc())
            .limit(1)
        )
        if decision in {"approved", "rejected", "revoked"}:
            return decision
        return "proposed"


class ProfileFactReview(Base):
    """Immutable human decision about one exact revision."""

    __tablename__ = "profile_fact_reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected', 'revoked')", name="decision"),
        CheckConstraint("reason IS NULL OR length(reason) <= 2000", name="reason_length"),
        ForeignKeyConstraint(
            ["revision_id", "fact_id"],
            ["profile_fact_revisions.id", "profile_fact_revisions.fact_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fact_id: Mapped[UUID] = mapped_column(ForeignKey("profile_facts.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    decision: Mapped[ReviewDecision] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
