"""Actor-owned CRM records. Models own changes; controllers own transactions."""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, declared_attr, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.models import AuditEvent


def record_event(
    session: Session,
    actor_id: UUID,
    request_id: UUID,
    action: str,
    subject: str,
    subject_id: UUID,
    **details: object,
) -> None:
    if session.info.get("agent_run_id"):
        details["agent_run_id"] = str(session.info["agent_run_id"])
    session.add(
        AuditEvent(
            actor_id=actor_id,
            request_id=request_id,
            action=action,
            subject_type=subject,
            subject_id=subject_id,
            details=details,
        )
    )


class OwnedRecord:
    __tablename__: str
    editable: ClassVar[frozenset[str]] = frozenset()
    required_text: ClassVar[frozenset[str]] = frozenset()

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.row_version}

    def revise(self, changes: dict[str, Any], *, request_id: UUID) -> None:
        if changes.keys() - self.editable:
            raise ValueError("Unsupported record fields")
        for key in self.required_text & changes.keys():
            if not isinstance(changes[key], str) or not changes[key].strip():
                raise ValueError(f"{key} cannot be blank")
        session = object_session(self)
        if session is None:
            raise ValueError("Record must belong to a transaction")
        for key, value in changes.items():
            setattr(self, key, value)
        if changes:
            self.updated_at = utc_now()
            record_event(
                session,
                self.owner_id,
                request_id,
                f"{self.__tablename__}.updated",
                self.__tablename__,
                self.id,
                fields=sorted(changes),
            )

    def archive(self, *, request_id: UUID) -> None:
        self.archived_at = utc_now()
        session = object_session(self)
        if session is None:
            raise ValueError("Record must belong to a transaction")
        record_event(
            session,
            self.owner_id,
            request_id,
            f"{self.__tablename__}.archived",
            self.__tablename__,
            self.id,
        )


class Company(OwnedRecord, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        CheckConstraint("length(trim(name)) > 0", name="name"),
    )
    editable = frozenset({"name", "domain", "industry", "location", "description"})
    required_text = frozenset({"name"})

    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(253))
    industry: Mapped[str | None] = mapped_column(String(150))
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)


class Contact(OwnedRecord, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(["company_id", "owner_id"], ["companies.id", "companies.owner_id"]),
        CheckConstraint(
            "relationship IN ('new', 'connected', 'warm', 'advocate')", name="relationship"
        ),
        CheckConstraint("length(trim(name)) > 0", name="name"),
    )
    editable = frozenset(
        {"name", "email", "title", "company_id", "linkedin_url", "relationship", "notes"}
    )
    required_text = frozenset({"name", "relationship"})

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    title: Mapped[str | None] = mapped_column(String(200))
    company_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    relationship: Mapped[str] = mapped_column(String(20), default="new")
    notes: Mapped[str | None] = mapped_column(Text)


class Job(OwnedRecord, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_jobs_id_owner"),
        UniqueConstraint("id", "company_id", "owner_id", name="uq_jobs_id_company_owner"),
        UniqueConstraint("owner_id", "source_url"),
        ForeignKeyConstraint(["company_id", "owner_id"], ["companies.id", "companies.owner_id"]),
        CheckConstraint(
            "work_mode IN ('remote', 'hybrid', 'onsite', 'unspecified')", name="work_mode"
        ),
        CheckConstraint("status IN ('open', 'closed', 'unknown')", name="status"),
        CheckConstraint("salary_min IS NULL OR salary_min >= 0", name="salary_min"),
        CheckConstraint(
            "salary_max IS NULL OR salary_max >= COALESCE(salary_min, 0)", name="salary_max"
        ),
    )
    editable = frozenset(
        {
            "title",
            "location",
            "work_mode",
            "source_url",
            "salary_min",
            "salary_max",
            "currency",
            "status",
            "description",
        }
    )
    required_text = frozenset({"title", "work_mode", "currency", "status"})

    company_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(200))
    work_mode: Mapped[str] = mapped_column(String(20), default="unspecified")
    source_url: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="open")
    description: Mapped[str | None] = mapped_column(Text)


class Opportunity(OwnedRecord, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        UniqueConstraint("owner_id", "job_id"),
        ForeignKeyConstraint(["company_id", "owner_id"], ["companies.id", "companies.owner_id"]),
        ForeignKeyConstraint(
            ["job_id", "company_id", "owner_id"], ["jobs.id", "jobs.company_id", "jobs.owner_id"]
        ),
        ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
        CheckConstraint(
            "stage IN ('researching', 'preparing', 'applied', 'interviewing', 'offer', 'closed')",
            name="stage",
        ),
        CheckConstraint("priority BETWEEN 0 AND 3", name="priority"),
    )
    editable = frozenset({"title", "contact_id", "stage", "priority", "notes"})
    required_text = frozenset({"title", "stage"})

    company_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    job_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(300))
    stage: Mapped[str] = mapped_column(String(20), default="researching", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text)

    def revise(self, changes: dict[str, Any], *, request_id: UUID) -> None:
        previous = self.stage
        super().revise(changes, request_id=request_id)
        if self.stage != previous:
            session = object_session(self)
            assert session is not None
            record_event(
                session,
                self.owner_id,
                request_id,
                "opportunity.stage_changed",
                "opportunities",
                self.id,
                from_stage=previous,
                to_stage=self.stage,
                source="manual",
            )


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), default="My workspace")
    headline: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": row_version}

    def revise(self, changes: dict[str, Any], *, request_id: UUID) -> None:
        if set(changes) - {"display_name", "headline", "location", "timezone", "preferences"}:
            raise ValueError("Unknown profile field")
        if any(value is None for value in changes.values()):
            raise ValueError("Profile fields cannot be null")
        for field, value in changes.items():
            setattr(self, field, value)
        session = object_session(self)
        if session:
            record_event(
                session, self.actor_id, request_id, "profile.updated", "profile", self.actor_id
            )
