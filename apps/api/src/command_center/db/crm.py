"""Actor-owned CRM records. Models own changes; controllers own transactions."""

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    or_,
    select,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, declared_attr, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.models import AuditEvent

if TYPE_CHECKING:
    from command_center.db.evidence import SourceRecord


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
    if session.info.get("mcp_client_id"):
        details["mcp_client_id"] = str(session.info["mcp_client_id"])
        details["initiator"] = "local_mcp"
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


class ContactObservation(Base):
    """Immutable export evidence, separate from the person's editable CRM fields."""

    __tablename__ = "contact_observations"
    __table_args__ = (
        ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
        ForeignKeyConstraint(
            ["source_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        ForeignKeyConstraint(
            ["source_version_id", "source_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        UniqueConstraint("source_version_id", "source_row"),
        CheckConstraint("source_row > 0", name="source_row"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    contact_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    source_artifact_id: Mapped[UUID] = mapped_column(Uuid)
    source_version_id: Mapped[UUID] = mapped_column(Uuid)
    source_row: Mapped[int] = mapped_column(Integer)
    mapping_version: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text)
    linkedin_url: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text)
    position: Mapped[str] = mapped_column(Text)
    connected_on: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @classmethod
    def capture_linkedin(
        cls,
        session: Session,
        *,
        contact: Contact,
        source_version_id: UUID,
        source_row: int,
        row: dict[str, str],
        request_id: UUID,
    ) -> "ContactObservation":
        from command_center.db.artifacts import Artifact, ArtifactVersion

        version = session.get(ArtifactVersion, source_version_id)
        artifact = session.get(Artifact, version.artifact_id) if version else None
        if not version or not artifact or artifact.owner_id != contact.owner_id:
            raise ValueError("Contact evidence must belong to the same owner")
        if source_row < 1:
            raise ValueError("Source rows start at one")
        record_id = uuid5(source_version_id, f"linkedin-connection:{source_row}")
        existing = session.get(cls, record_id)
        if existing:
            return existing
        observation = cls(
            id=record_id,
            owner_id=contact.owner_id,
            contact_id=contact.id,
            source_artifact_id=artifact.id,
            source_version_id=version.id,
            source_row=source_row,
            mapping_version="linkedin-contacts-profile-v2",
            first_name=row.get("First Name", ""),
            last_name=row.get("Last Name", ""),
            linkedin_url=row.get("URL", ""),
            email=row.get("Email Address", ""),
            company=row.get("Company", ""),
            position=row.get("Position", ""),
            connected_on=row.get("Connected On", ""),
        )
        session.add(observation)
        record_event(
            session,
            contact.owner_id,
            request_id,
            "contact.source_imported",
            "contacts",
            contact.id,
            observation_id=str(record_id),
            source_version_id=str(version.id),
        )
        session.flush()
        return observation


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

    @classmethod
    def capture_lead(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        url: str,
        title: str,
        company_name: str,
        snippet: str,
        request_id: UUID,
    ) -> tuple["Opportunity", Job, Company, "SourceRecord", bool]:
        """Create or find the actor's lead aggregate for one canonical job URL."""
        from command_center.db.evidence import SourceRecord

        lock = int.from_bytes(
            hashlib.sha256(f"lead:{owner_id}:{url}".encode()).digest()[:8], signed=True
        )
        session.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})

        job = session.scalar(select(Job).where(Job.owner_id == owner_id, Job.source_url == url))
        created = False
        if job is None:
            matches = session.scalars(
                select(Company).where(
                    Company.owner_id == owner_id,
                    Company.archived_at.is_(None),
                    func.lower(func.btrim(Company.name)) == company_name.lower(),
                )
            ).all()
            if len(matches) == 1:
                company = matches[0]
            else:
                company = Company(
                    id=uuid5(record_id, "company"), owner_id=owner_id, name=company_name
                )
                session.add(company)
                record_event(
                    session,
                    owner_id,
                    request_id,
                    "companies.created",
                    "companies",
                    company.id,
                )
            job = Job(
                id=uuid5(record_id, "job"),
                owner_id=owner_id,
                company_id=company.id,
                title=title,
                source_url=url,
                status="unknown",
            )
            session.add(job)
            record_event(session, owner_id, request_id, "jobs.created", "jobs", job.id)
        else:
            existing_company = session.get(Company, job.company_id)
            if existing_company is None or existing_company.owner_id != owner_id:
                raise ValueError("The captured job has invalid company ownership")
            company = existing_company

        opportunity = session.scalar(
            select(cls).where(cls.owner_id == owner_id, cls.job_id == job.id)
        )
        if opportunity is None:
            opportunity = cls(
                id=record_id,
                owner_id=owner_id,
                company_id=company.id,
                job_id=job.id,
                title=title,
                stage="researching",
            )
            session.add(opportunity)
            record_event(
                session,
                owner_id,
                request_id,
                "opportunities.created",
                "opportunities",
                opportunity.id,
            )
            created = True
        session.flush()

        source = session.scalar(
            select(SourceRecord)
            .where(
                SourceRecord.opportunity_id == opportunity.id,
                SourceRecord.extraction_method == "user_snippet",
            )
            .order_by(SourceRecord.retrieved_at, SourceRecord.id)
            .limit(1)
        )
        if source is None:
            source = SourceRecord.capture_for_opportunity(
                session,
                record_id=uuid5(opportunity.id, "lead-capture-source"),
                opportunity_id=opportunity.id,
                owner_id=owner_id,
                title=title,
                url=url,
                text=snippet,
                provider="user",
                extraction_method="user_snippet",
                request_id=request_id,
            )
        return opportunity, job, company, source, created

    @classmethod
    def capture_content(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        data: dict[str, Any],
        request_id: UUID,
    ) -> tuple["Opportunity", Job | None, Company, Contact | None, "SourceRecord", dict[str, bool]]:
        """Capture a private lead without replacing existing human-authored CRM facts."""
        from command_center.core.public_urls import normalize_public_url
        from command_center.db.artifacts import Artifact, ArtifactVersion
        from command_center.db.conversations import AgentMessage
        from command_center.db.evidence import SourceRecord

        # Intake is small and owner-local. Serializing its identity matching prevents
        # overlapping requests with different receipts from creating duplicate people.
        lock = int.from_bytes(
            hashlib.sha256(f"intake:{owner_id}".encode()).digest()[:8], signed=True
        )
        session.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        created = dict.fromkeys(("company", "contact", "job", "opportunity", "source"), False)

        def owned_record(model: Any, value: str) -> Any:
            row = session.get(model, UUID(value))
            if row is None or row.owner_id != owner_id or row.archived_at is not None:
                raise RecordNotFound("The referenced record is unavailable in this workspace")
            return row

        def unique_match(rows: list[Any], entity: str) -> Any:
            if len(rows) > 1:
                raise RecordConflict(
                    f"Multiple {entity} records match; select an existing {entity}_id"
                )
            return rows[0] if rows else None

        def save_new(row: Any, entity: str) -> Any:
            session.add(row)
            record_event(
                session,
                owner_id,
                request_id,
                f"{row.__tablename__}.created",
                row.__tablename__,
                row.id,
            )
            created[entity] = True
            session.flush()
            return row

        source_version_id = (
            UUID(data["source_version_id"]) if data.get("source_version_id") else None
        )
        source_message_id = (
            UUID(data["source_message_id"]) if data.get("source_message_id") else None
        )
        text = data.get("source_text")
        if source_version_id:
            version = session.get(ArtifactVersion, source_version_id)
            artifact = session.get(Artifact, version.artifact_id) if version else None
            if artifact is None or artifact.owner_id != owner_id or artifact.archived_at:
                raise RecordNotFound("The source version is unavailable in this workspace")
            text = (version.payload or {}).get("text") if version else None
        if source_message_id:
            message = session.get(AgentMessage, source_message_id)
            if (
                message is None
                or message.owner_id != owner_id
                or message.author != "user"
                or message.archived_at is not None
            ):
                raise RecordNotFound("The source user message is unavailable in this workspace")
            text = message.content
        if not isinstance(text, str) or not text.strip() or len(text) > 50000:
            raise ValueError("Choose a text source between 1 and 50,000 characters")
        text_digest = hashlib.sha256(text.encode()).hexdigest()
        locator = data.get("source_url") or (
            f"urn:command-center:message:{source_message_id}"
            if source_message_id
            else f"urn:command-center:pasted:{text_digest}"
        )
        if data.get("source_url"):
            parsed = urlsplit(locator)
            if parsed.username or parsed.password:
                raise ValueError("Source URLs cannot contain credentials")
        title = str(data["title"]).strip()
        company_name = str(data.get("company_name") or "").strip()
        domain = str(data.get("company_domain") or "").lower().strip().rstrip(".") or None
        if domain:
            labels = domain.split(".")
            if len(labels) < 2 or any(
                not label
                or len(label) > 63
                or not label[0].isalnum()
                or not label[-1].isalnum()
                or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in label)
                for label in labels
            ):
                raise ValueError("Use a valid company domain, or omit it when unknown")
        if data.get("company_id"):
            company = owned_record(Company, data["company_id"])
        else:
            if not company_name:
                raise ValueError("A company name or existing company is required")
            conditions = [func.lower(func.btrim(Company.name)) == company_name.lower()]
            if domain:
                conditions.append(func.lower(Company.domain) == domain)
            matches = list(
                session.scalars(
                    select(Company).where(
                        Company.owner_id == owner_id,
                        Company.archived_at.is_(None),
                        or_(*conditions),
                    )
                )
            )
            company = unique_match(matches, "company")
            if (
                company is not None
                and domain
                and company.domain
                and company.domain.lower() != domain
            ):
                raise RecordConflict("The company name and domain conflict; select company_id")
            if company is None:
                company = save_new(
                    Company(
                        id=uuid5(record_id, "company"),
                        owner_id=owner_id,
                        name=company_name,
                        domain=domain,
                    ),
                    "company",
                )

        contact = None
        contact_data = data.get("contact") or {}
        if data.get("contact_id"):
            contact = owned_record(Contact, data["contact_id"])
        elif contact_data:
            name = str(contact_data["name"]).strip()
            email = str(contact_data.get("email") or "").strip().lower() or None
            linkedin = contact_data.get("linkedin_url")
            if linkedin:
                parsed = urlsplit(linkedin)
                host = (parsed.hostname or "").lower().removeprefix("www.")
                if (
                    host != "linkedin.com"
                    or not parsed.path.startswith("/in/")
                    or not parsed.path.removeprefix("/in/").strip("/")
                    or "/" in parsed.path.removeprefix("/in/").rstrip("/")
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("Use a LinkedIn /in/ profile URL for a contact")
                linkedin = urlunsplit(
                    ("https", "www.linkedin.com", parsed.path.rstrip("/").lower(), "", "")
                )
            identity_conditions = []
            if email:
                identity_conditions.append(func.lower(Contact.email) == email)
            if linkedin:
                saved_link = func.regexp_replace(
                    func.lower(
                        func.rtrim(
                            func.split_part(func.split_part(Contact.linkedin_url, "?", 1), "#", 1),
                            "/",
                        )
                    ),
                    r"^https?://(www\.)?",
                    "",
                )
                identity_conditions.append(saved_link == linkedin.removeprefix("https://www."))
            if identity_conditions:
                contact = unique_match(
                    list(
                        session.scalars(
                            select(Contact).where(
                                Contact.owner_id == owner_id,
                                Contact.archived_at.is_(None),
                                or_(*identity_conditions),
                            )
                        )
                    ),
                    "contact",
                )
            else:
                # An exact replay of an identifier-free source may reuse its own
                # deterministic contact; another same-named person is ambiguous.
                contact = session.get(
                    Contact, uuid5(owner_id, f"intake-contact:{text_digest}:{name.lower()}")
                )
                if contact is not None and contact.archived_at is not None:
                    raise RecordConflict("The captured contact was archived; select contact_id")
                names = list(
                    session.scalars(
                        select(Contact.id).where(
                            Contact.owner_id == owner_id,
                            Contact.archived_at.is_(None),
                            func.lower(func.btrim(Contact.name)) == name.lower(),
                        )
                    )
                )
                if contact is None and names:
                    raise RecordConflict(
                        "A same-named contact exists; supply email, LinkedIn URL or contact_id"
                    )
            if contact is not None:
                if email and contact.email and contact.email.lower() != email:
                    raise RecordConflict("Contact identifiers conflict; select contact_id")
                if linkedin and contact.linkedin_url:
                    parsed_saved = urlsplit(contact.linkedin_url)
                    if parsed_saved.path.rstrip("/").lower() != urlsplit(linkedin).path:
                        raise RecordConflict("Contact identifiers conflict; select contact_id")
            if contact is None:
                identity_key = (
                    f"intake-contact:{text_digest}:{name.lower()}:{email or ''}:{linkedin or ''}"
                    if identity_conditions
                    else f"intake-contact:{text_digest}:{name.lower()}"
                )
                contact_record_id = uuid5(owner_id, identity_key)
                if session.get(Contact, contact_record_id) is not None:
                    raise RecordConflict("The captured contact was archived; select contact_id")
                contact = save_new(
                    Contact(
                        id=contact_record_id,
                        owner_id=owner_id,
                        company_id=company.id,
                        name=name,
                        email=email,
                        linkedin_url=linkedin,
                        title=contact_data.get("title"),
                        notes=contact_data.get("notes"),
                    ),
                    "contact",
                )

        job = None
        job_data = data.get("job")
        if data.get("job_id"):
            if job_data:
                raise ValueError("Provide either job_id or job details")
            job = owned_record(Job, data["job_id"])
            if job.company_id != company.id:
                raise RecordConflict("The saved job belongs to another company")
        elif job_data:
            job_url = normalize_public_url(job_data["url"])
            job = unique_match(
                list(
                    session.scalars(
                        select(Job).where(
                            Job.owner_id == owner_id,
                            Job.archived_at.is_(None),
                            Job.source_url == job_url,
                        )
                    )
                ),
                "job",
            )
            if job is not None and job.company_id != company.id:
                raise RecordConflict(
                    "The saved job belongs to another company; select its company_id"
                )
            if job is None:
                job = save_new(
                    Job(
                        id=uuid5(record_id, "job"),
                        owner_id=owner_id,
                        company_id=company.id,
                        title=job_data["title"],
                        source_url=job_url,
                        location=job_data.get("location"),
                        status="unknown",
                    ),
                    "job",
                )

        contact_id = contact.id if contact else None
        job_id = job.id if job else None
        if data.get("opportunity_id"):
            opportunity = owned_record(cls, data["opportunity_id"])
            if (
                opportunity.company_id != company.id
                or opportunity.contact_id != contact_id
                or opportunity.job_id != job_id
            ):
                raise RecordConflict(
                    "The selected opportunity has different links; "
                    "supply its existing contact/job context"
                )
        else:
            conditions = [
                cls.owner_id == owner_id,
                cls.archived_at.is_(None),
                cls.company_id == company.id,
            ]
            if job:
                conditions.append(cls.job_id == job.id)
            else:
                conditions += [
                    cls.job_id.is_(None),
                    cls.contact_id == contact_id,
                    func.lower(func.btrim(cls.title)) == title.lower(),
                ]
            opportunity = unique_match(
                list(session.scalars(select(cls).where(*conditions).with_for_update())),
                "opportunity",
            )
            if (
                opportunity is not None
                and opportunity.contact_id is None
                and contact_id is not None
            ):
                opportunity.revise({"contact_id": contact_id}, request_id=request_id)
            if opportunity is not None and opportunity.contact_id != contact_id:
                raise RecordConflict(
                    "The saved opportunity has a different contact; select its existing contact_id"
                )
            if opportunity is None:
                opportunity = save_new(
                    cls(
                        id=record_id,
                        owner_id=owner_id,
                        company_id=company.id,
                        job_id=job_id,
                        contact_id=contact_id,
                        title=title,
                        notes=data.get("notes"),
                        stage="researching",
                    ),
                    "opportunity",
                )

        source_identity = hashlib.sha256(
            f"{locator}\n{text}\n{source_version_id or ''}\n{source_message_id or ''}".encode()
        ).hexdigest()
        source_id = uuid5(opportunity.id, f"private-lead-source:{source_identity}")
        source = session.get(SourceRecord, source_id)
        if source is None:
            source = SourceRecord.capture_for_opportunity(
                session,
                record_id=source_id,
                opportunity_id=opportunity.id,
                owner_id=owner_id,
                title=title,
                url=locator,
                text=text,
                provider="user",
                extraction_method="private_lead_intake",
                request_id=request_id,
                sensitivity="private",
                account_scope="private",
                source_version_ids=[source_version_id] if source_version_id else None,
                source_message_id=source_message_id,
            )
            created["source"] = True
        return opportunity, job, company, contact, source, created

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
    default_resume_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifact_versions.id")
    )
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

    def select_default_resume(self, version_id: UUID | None, *, request_id: UUID) -> None:
        """Pin one exact owned original resume version, or clear the selection."""
        from command_center.db.artifacts import Artifact, ArtifactVersion, Document, DocumentType

        session = object_session(self)
        if session is None:
            raise ValueError("Profile must belong to a transaction")
        if version_id is not None:
            version = session.scalar(
                select(ArtifactVersion)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .join(Document, Document.artifact_id == Artifact.id)
                .join(DocumentType, DocumentType.id == Document.document_type_id)
                .where(
                    ArtifactVersion.id == version_id,
                    ArtifactVersion.blob_id.is_not(None),
                    Artifact.owner_id == self.actor_id,
                    Artifact.archived_at.is_(None),
                    DocumentType.slug == "resume",
                )
            )
            if version is None:
                raise ValueError("Choose an owned blob-backed resume version")
        self.default_resume_version_id = version_id
        record_event(
            session,
            self.actor_id,
            request_id,
            "profile.default_resume_selected",
            "profile",
            self.actor_id,
            version_id=str(version_id) if version_id else None,
        )
