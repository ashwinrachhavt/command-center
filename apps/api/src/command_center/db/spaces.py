"""Persistent work contexts that link to canonical, actor-owned records."""

from datetime import datetime
from typing import Any, Literal
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
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import Artifact
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import Company, Contact, Opportunity, OwnedRecord, record_event
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.models import Task

SpaceRecordType = Literal["task", "artifact", "contact", "company", "opportunity"]
SpaceRecord = Task | Artifact | Contact | Company | Opportunity
LINK_MODELS: dict[SpaceRecordType, type[SpaceRecord]] = {
    "task": Task,
    "artifact": Artifact,
    "contact": Contact,
    "company": Company,
    "opportunity": Opportunity,
}


class Space(OwnedRecord, Base):
    __tablename__ = "spaces"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        CheckConstraint("state IN ('active', 'archived')", name="state"),
        CheckConstraint("(state = 'archived') = (archived_at IS NOT NULL)", name="archive"),
        CheckConstraint("row_version >= 1", name="row_version"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
    )
    editable = frozenset({"title", "purpose"})
    required_text = frozenset({"title"})

    title: Mapped[str] = mapped_column(String(300))
    purpose: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="active", index=True)

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        title: str,
        purpose: str | None,
        request_id: UUID,
    ) -> "Space":
        if not title.strip():
            raise ValueError("Space title cannot be blank")
        space = cls(id=record_id, owner_id=owner_id, title=title, purpose=purpose)
        session.add(space)
        session.flush()
        record_event(session, owner_id, request_id, "spaces.created", "spaces", space.id)
        return space

    def active_session(self) -> Session:
        session = object_session(self)
        if session is None:
            raise ValueError("Space must belong to a transaction")
        if self.state != "active" or self.archived_at is not None:
            raise RecordConflict("Archived Spaces cannot be edited. Restore this Space first.")
        return session

    def revise(self, changes: dict[str, Any], *, request_id: UUID) -> None:
        self.active_session()
        super().revise(changes, request_id=request_id)

    def archive(self, *, request_id: UUID) -> None:
        self.active_session()
        self.state = "archived"
        super().archive(request_id=request_id)

    def restore(self, *, request_id: UUID) -> None:
        session = object_session(self)
        if session is None:
            raise ValueError("Space must belong to a transaction")
        if self.state != "archived":
            raise RecordConflict("This Space is already active")
        self.state = "active"
        self.archived_at = None
        self.updated_at = utc_now()
        record_event(session, self.owner_id, request_id, "spaces.restored", "spaces", self.id)

    def link(
        self, record_type: SpaceRecordType, record_id: UUID, *, request_id: UUID
    ) -> "SpaceLink":
        session = self.active_session()
        model = LINK_MODELS[record_type]
        target = session.scalar(
            select(model)
            .where(model.id == record_id, model.owner_id == self.owner_id)
            .with_for_update(key_share=True)
        )
        if target is None:
            raise RecordNotFound("Record not found")
        if getattr(target, "archived_at", None) is not None:
            raise ValueError("Choose an active linked record")
        column = getattr(SpaceLink, f"{record_type}_id")
        existing = session.scalar(
            select(SpaceLink).where(
                SpaceLink.space_id == self.id,
                SpaceLink.owner_id == self.owner_id,
                column == record_id,
            )
        )
        if existing is not None:
            return existing
        link = SpaceLink(
            space_id=self.id,
            owner_id=self.owner_id,
            **{f"{record_type}_id": record_id},
        )
        session.add(link)
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "spaces.linked",
            "spaces",
            self.id,
            record_type=record_type,
            record_id=str(record_id),
        )
        return link

    def unlink(self, link_id: UUID, *, request_id: UUID) -> None:
        session = self.active_session()
        link = session.scalar(
            select(SpaceLink).where(
                SpaceLink.id == link_id,
                SpaceLink.space_id == self.id,
                SpaceLink.owner_id == self.owner_id,
            )
        )
        if link is None:
            raise RecordNotFound("Record not found")
        record_event(
            session,
            self.owner_id,
            request_id,
            "spaces.unlinked",
            "spaces",
            self.id,
            record_type=link.record_type,
            record_id=str(link.record_id),
        )
        session.delete(link)
        self.updated_at = utc_now()

    def create_task(self, *, task_id: UUID, request_id: UUID, **fields: Any) -> Task:
        """Capture one ordinary task and its membership in the caller's transaction."""
        session = self.active_session()
        if fields.get("opportunity_id"):
            opportunity = session.scalar(
                select(Opportunity)
                .where(
                    Opportunity.id == fields["opportunity_id"],
                    Opportunity.owner_id == self.owner_id,
                )
                .with_for_update(key_share=True)
            )
            if opportunity is None:
                raise RecordNotFound("Record not found")
            if opportunity.archived_at is not None:
                raise ValueError("Choose an active opportunity")
        task = Task(id=task_id, owner_id=self.owner_id, **fields)
        session.add(task)
        session.flush()
        self.link("task", task.id, request_id=request_id)
        record_event(
            session,
            self.owner_id,
            request_id,
            "tasks.created",
            "tasks",
            task.id,
            space_id=str(self.id),
        )
        return task


class SpaceLink(Base):
    __tablename__ = "space_links"
    __table_args__ = (
        ForeignKeyConstraint(["space_id", "owner_id"], ["spaces.id", "spaces.owner_id"]),
        ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        ForeignKeyConstraint(["artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]),
        ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
        ForeignKeyConstraint(["company_id", "owner_id"], ["companies.id", "companies.owner_id"]),
        ForeignKeyConstraint(
            ["opportunity_id", "owner_id"], ["opportunities.id", "opportunities.owner_id"]
        ),
        CheckConstraint(
            "num_nonnulls(task_id, artifact_id, contact_id, company_id, opportunity_id) = 1",
            name="one_record",
        ),
        UniqueConstraint("space_id", "task_id", name="uq_space_links_space_task"),
        UniqueConstraint("space_id", "artifact_id", name="uq_space_links_space_artifact"),
        UniqueConstraint("space_id", "contact_id", name="uq_space_links_space_contact"),
        UniqueConstraint("space_id", "company_id", name="uq_space_links_space_company"),
        UniqueConstraint("space_id", "opportunity_id", name="uq_space_links_space_opportunity"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    artifact_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    company_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @property
    def record_type(self) -> SpaceRecordType:
        for record_type in LINK_MODELS:
            if getattr(self, f"{record_type}_id") is not None:
                return record_type
        raise ValueError("Space link has no record")

    @property
    def record_id(self) -> UUID:
        return UUID(str(getattr(self, f"{self.record_type}_id")))
