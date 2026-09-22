"""Reviewed reusable context, separate from facts, instructions, and authority."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    case,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session
from sqlalchemy.sql.elements import ColumnElement

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import Opportunity, OwnedRecord, record_event
from command_center.db.errors import RecordConflict
from command_center.db.models import Task

MemoryKind = Literal["note", "preference"]
MemoryScope = Literal["global", "task", "opportunity"]
MemorySource = Literal["human", "agent", "legacy_human", "legacy_agent"]
MemoryReviewState = Literal["proposed", "approved", "rejected", "revoked"]
MemoryReviewDecision = Literal["approved", "rejected", "revoked"]


class MemoryItem(OwnedRecord, Base):
    """Mutable pointers over immutable reusable-memory proposals."""

    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint("row_version >= 1", name="row_version"),
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["current_revision_id", "id"],
            ["memory_revisions.id", "memory_revisions.memory_id"],
            name="fk_memory_items_current_revision",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["active_revision_id", "id"],
            ["memory_revisions.id", "memory_revisions.memory_id"],
            name="fk_memory_items_active_revision",
            use_alter=True,
        ),
    )

    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    active_revision_id: Mapped[UUID | None] = mapped_column(Uuid)

    @classmethod
    def propose(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        title: str,
        content: str,
        kind: MemoryKind,
        scope_type: MemoryScope,
        scope_id: UUID | None,
        valid_until: datetime | None,
        source: Literal["human", "agent"],
        source_run_id: UUID | None,
        source_artifact_id: UUID | None,
        reason: str | None,
        request_id: UUID,
    ) -> "MemoryItem":
        cls._validate_revision(
            session,
            owner_id=owner_id,
            title=title,
            content=content,
            kind=kind,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_until=valid_until,
            source=source,
            source_run_id=source_run_id,
            source_artifact_id=source_artifact_id,
            reason=reason,
        )
        item = cls(id=record_id, owner_id=owner_id)
        session.add(item)
        session.flush()
        revision = MemoryRevision(
            memory_id=item.id,
            version=1,
            title=title.strip(),
            content=content.strip(),
            kind=kind,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_until=valid_until,
            source=source,
            source_run_id=source_run_id,
            source_artifact_id=source_artifact_id,
            reason=reason.strip() if reason else None,
        )
        session.add(revision)
        session.flush()
        session.execute(
            update(MemoryItem)
            .where(MemoryItem.id == item.id)
            .values(current_revision_id=revision.id),
            execution_options={"synchronize_session": False},
        )
        session.refresh(item)
        record_event(
            session,
            owner_id,
            request_id,
            "memory.proposed",
            "memory_items",
            item.id,
            revision_id=str(revision.id),
            source=source,
            scope_type=scope_type,
            scope_id=str(scope_id) if scope_id else None,
        )
        return item

    def append_revision(
        self,
        *,
        title: str,
        content: str,
        kind: MemoryKind,
        scope_type: MemoryScope,
        scope_id: UUID | None,
        valid_until: datetime | None,
        source: Literal["human", "agent"],
        source_run_id: UUID | None,
        source_artifact_id: UUID | None,
        reason: str | None,
        request_id: UUID,
    ) -> "MemoryRevision":
        session = object_session(self)
        if session is None or self.current_revision_id is None:
            raise ValueError("Revise a persisted memory")
        self._validate_revision(
            session,
            owner_id=self.owner_id,
            title=title,
            content=content,
            kind=kind,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_until=valid_until,
            source=source,
            source_run_id=source_run_id,
            source_artifact_id=source_artifact_id,
            reason=reason,
        )
        current = session.get(MemoryRevision, self.current_revision_id)
        if current is None:
            raise ValueError("Memory current revision is missing")
        revision = MemoryRevision(
            memory_id=self.id,
            version=current.version + 1,
            title=title.strip(),
            content=content.strip(),
            kind=kind,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_until=valid_until,
            source=source,
            source_run_id=source_run_id,
            source_artifact_id=source_artifact_id,
            reason=reason.strip() if reason else None,
        )
        session.add(revision)
        session.flush()
        self.current_revision_id = revision.id
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "memory.revised",
            "memory_items",
            self.id,
            revision_id=str(revision.id),
            version=revision.version,
            source=source,
        )
        return revision

    def review(
        self,
        *,
        revision_id: UUID,
        reviewer_id: UUID,
        reviewer_is_human: bool,
        decision: MemoryReviewDecision,
        reason: str | None,
        request_id: UUID,
    ) -> "MemoryReview":
        if not reviewer_is_human or reviewer_id != self.owner_id:
            raise PermissionError("Only the human owner can review reusable memory")
        if reason is not None and len(reason) > 2000:
            raise ValueError("Review reason is too long")
        session = object_session(self)
        if session is None:
            raise ValueError("Review a persisted memory")
        revision = session.scalar(
            select(MemoryRevision).where(
                MemoryRevision.id == revision_id,
                MemoryRevision.memory_id == self.id,
            )
        )
        if revision is None:
            raise ValueError("Revision does not belong to this memory")
        state = revision.review_state(session)
        if decision == "revoked":
            if self.active_revision_id != revision.id or state != "approved":
                raise RecordConflict("Only the active approved memory can be revoked")
            self.active_revision_id = None
        else:
            if self.current_revision_id != revision.id or state != "proposed":
                raise RecordConflict("Only the current proposal can be reviewed")
            if decision == "approved":
                self.active_revision_id = revision.id
        review = MemoryReview(
            memory_id=self.id,
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
            "memory.reviewed",
            "memory_items",
            self.id,
            revision_id=str(revision.id),
            decision=decision,
        )
        return review

    def archive(self, *, request_id: UUID) -> None:
        if self.archived_at is not None:
            raise RecordConflict("Memory is already archived")
        session = object_session(self)
        if session is None:
            raise ValueError("Archive a persisted memory")
        self.archived_at = utc_now()
        self.active_revision_id = None
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "memory.archived",
            "memory_items",
            self.id,
        )

    @classmethod
    def retrieve(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        query: str,
        task_id: UUID | None,
        opportunity_id: UUID | None,
        limit: int,
    ) -> list[tuple["MemoryItem", "MemoryRevision"]]:
        if task_id is not None:
            cls._owned_scope(session, owner_id, "task", task_id)
        if opportunity_id is not None:
            cls._owned_scope(session, owner_id, "opportunity", opportunity_id)
        revision = MemoryRevision
        search = query.strip()
        text_rank: ColumnElement[Any] = literal(0.0)
        filters = []
        if search:
            tsquery = func.websearch_to_tsquery("simple", search)
            filters.append(revision.search_vector.op("@@")(tsquery))
            text_rank = func.ts_rank_cd(revision.search_vector, tsquery)
        scopes = [revision.scope_type == "global"]
        if task_id is not None:
            scopes.append(and_(revision.scope_type == "task", revision.scope_id == task_id))
        if opportunity_id is not None:
            scopes.append(
                and_(
                    revision.scope_type == "opportunity",
                    revision.scope_id == opportunity_id,
                )
            )
        scope_rank = case(
            (and_(revision.scope_type == "task", revision.scope_id == task_id), 3),
            (
                and_(
                    revision.scope_type == "opportunity",
                    revision.scope_id == opportunity_id,
                ),
                2,
            ),
            else_=1,
        )
        statement = (
            select(cls, revision)
            .join(revision, revision.id == cls.active_revision_id)
            .where(
                cls.owner_id == owner_id,
                cls.archived_at.is_(None),
                or_(revision.valid_until.is_(None), revision.valid_until > utc_now()),
                or_(*scopes),
                *filters,
            )
            .order_by(scope_rank.desc(), text_rank.desc(), cls.updated_at.desc(), cls.id)
            .limit(limit)
        )
        return [(item, current) for item, current in session.execute(statement).all()]

    @staticmethod
    def _validate_revision(
        session: Session,
        *,
        owner_id: UUID,
        title: str,
        content: str,
        kind: str,
        scope_type: str,
        scope_id: UUID | None,
        valid_until: datetime | None,
        source: str,
        source_run_id: UUID | None,
        source_artifact_id: UUID | None,
        reason: str | None,
    ) -> None:
        if not title.strip() or len(title) > 200:
            raise ValueError("Memory title must contain 1 to 200 characters")
        if not content.strip() or len(content) > 10000:
            raise ValueError("Memory content must contain 1 to 10000 characters")
        if kind not in {"note", "preference"}:
            raise ValueError("Unknown memory kind")
        if scope_type not in {"global", "task", "opportunity"}:
            raise ValueError("Unknown memory scope")
        if (scope_type == "global") != (scope_id is None):
            raise ValueError("Scoped memory requires exactly one task or opportunity")
        if scope_id is not None:
            MemoryItem._owned_scope(session, owner_id, scope_type, scope_id)
        if valid_until is not None and valid_until <= utc_now():
            raise ValueError("Memory expiry must be in the future")
        if source == "agent":
            if source_run_id is None or reason is None or not reason.strip():
                raise ValueError("Agent memory proposals require their run and a reason")
        elif source != "human" or source_run_id is not None:
            raise ValueError("Invalid memory provenance")
        if reason is not None and len(reason) > 2000:
            raise ValueError("Memory proposal reason is too long")
        if source_run_id is not None:
            from command_center.db.agents import AgentRun

            run = session.scalar(
                select(AgentRun.id).where(
                    AgentRun.id == source_run_id,
                    AgentRun.owner_id == owner_id,
                )
            )
            if run is None:
                raise ValueError("Choose an owned source run")
        if source_artifact_id is not None:
            from command_center.db.artifacts import Artifact

            artifact = session.scalar(
                select(Artifact.id).where(
                    Artifact.id == source_artifact_id,
                    Artifact.owner_id == owner_id,
                    Artifact.archived_at.is_(None),
                )
            )
            if artifact is None:
                raise ValueError("Choose an owned active source artifact")

    @staticmethod
    def _owned_scope(session: Session, owner_id: UUID, scope_type: str, scope_id: UUID) -> None:
        if scope_type == "task":
            exists = session.scalar(
                select(Task.id).where(Task.id == scope_id, Task.owner_id == owner_id)
            )
        elif scope_type == "opportunity":
            exists = session.scalar(
                select(Opportunity.id).where(
                    Opportunity.id == scope_id,
                    Opportunity.owner_id == owner_id,
                )
            )
        else:
            raise ValueError("Unknown memory scope")
        if exists is None:
            raise ValueError("Choose an owned memory scope")


class MemoryRevision(Base):
    """Immutable exact wording, provenance, scope, and expiry."""

    __tablename__ = "memory_revisions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="title_length"),
        CheckConstraint("length(content) BETWEEN 1 AND 10000", name="content_length"),
        CheckConstraint("kind IN ('note', 'preference')", name="kind"),
        CheckConstraint("scope_type IN ('global', 'task', 'opportunity')", name="scope_type"),
        CheckConstraint("(scope_type = 'global') = (scope_id IS NULL)", name="scope_id"),
        CheckConstraint(
            "source IN ('human', 'agent', 'legacy_human', 'legacy_agent')", name="source"
        ),
        CheckConstraint("reason IS NULL OR length(reason) <= 2000", name="reason_length"),
        UniqueConstraint("memory_id", "version"),
        UniqueConstraint("id", "memory_id"),
        Index("ix_memory_revisions_scope", "scope_type", "scope_id"),
        Index("ix_memory_revisions_search", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    memory_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[MemoryKind] = mapped_column(String(20))
    scope_type: Mapped[MemoryScope] = mapped_column(String(20))
    scope_id: Mapped[UUID | None] = mapped_column(Uuid)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    source: Mapped[MemorySource] = mapped_column(String(20))
    source_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    source_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    def review_state(self, session: Session | None = None) -> MemoryReviewState:
        current_session = session or object_session(self)
        if current_session is None:
            raise ValueError("Read review state from a persisted memory revision")
        decision = current_session.scalar(
            select(MemoryReview.decision)
            .where(MemoryReview.revision_id == self.id)
            .order_by(MemoryReview.created_at.desc(), MemoryReview.id.desc())
            .limit(1)
        )
        if decision in {"approved", "rejected", "revoked"}:
            return decision
        return "proposed"


class MemoryReview(Base):
    """Immutable human decision about one exact reusable-memory revision."""

    __tablename__ = "memory_reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected', 'revoked')", name="decision"),
        CheckConstraint("reason IS NULL OR length(reason) <= 2000", name="reason_length"),
        ForeignKeyConstraint(
            ["revision_id", "memory_id"],
            ["memory_revisions.id", "memory_revisions.memory_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    memory_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    decision: Mapped[MemoryReviewDecision] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
