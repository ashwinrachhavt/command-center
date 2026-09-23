"""Provider evidence stays immutable; explicitly imported contacts remain user-editable."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.base import Base, utc_now
from command_center.db.crm import Company, Contact, record_event
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.models import Actor
from command_center.integrations.contact_discovery import (
    Prospect,
    ProspectPage,
    professional_domain,
)

SCHEMA = "contact_discovery.v1"


class ContactDiscoveryEvidence(Base):
    __tablename__ = "contact_discovery_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
        ForeignKeyConstraint(
            ["source_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        ForeignKeyConstraint(
            ["source_version_id", "source_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        UniqueConstraint("owner_id", "provider", "external_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    contact_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(320))
    source_artifact_id: Mapped[UUID] = mapped_column(Uuid)
    source_version_id: Mapped[UUID] = mapped_column(Uuid)

    @staticmethod
    def snapshot(
        db: Session,
        *,
        owner_id: UUID,
        record_id: UUID,
        request_id: UUID,
        query: dict[str, Any],
        cache_key: str,
        result: ProspectPage,
    ) -> dict[str, Any]:
        artifact = Artifact(
            id=record_id,
            owner_id=owner_id,
            created_by_id=owner_id,
            kind="source",
            title=f"{query['provider'].title()} contacts · {query['domain']}",
            sensitivity="private",
        )
        db.add(artifact)
        db.flush()
        version = ArtifactVersion.from_payload(
            artifact_id=artifact.id,
            version=1,
            payload={
                "query": query,
                "cache_key": cache_key,
                "result": result.model_dump(mode="json"),
            },
            schema_key=SCHEMA,
            created_by_id=owner_id,
        )
        version.id = uuid5(record_id, "version:1")
        db.add(version)
        db.flush()
        record_event(
            db,
            owner_id,
            request_id,
            "contacts.discovered",
            "artifacts",
            artifact.id,
            provider=query["provider"],
            operation=query["operation"],
            count=len(result.items),
        )
        return ContactDiscoveryEvidence.read_snapshot(version)

    @staticmethod
    def read_snapshot(version: ArtifactVersion, *, cached: bool = False) -> dict[str, Any]:
        payload = version.payload or {}
        return {
            "source_version_id": str(version.id),
            "source_artifact_id": str(version.artifact_id),
            "query": payload["query"],
            "result": payload["result"],
            "observed_at": version.created_at.isoformat(),
            "cached": cached,
        }

    @staticmethod
    def cached(db: Session, *, owner_id: UUID, cache_key: str) -> dict[str, Any] | None:
        version = db.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                Artifact.owner_id == owner_id,
                Artifact.archived_at.is_(None),
                ArtifactVersion.schema_key == SCHEMA,
                ArtifactVersion.payload["cache_key"].astext == cache_key,
                ArtifactVersion.created_at > utc_now() - timedelta(hours=1),
            )
            .order_by(ArtifactVersion.created_at.desc())
            .limit(1)
        )
        return ContactDiscoveryEvidence.read_snapshot(version, cached=True) if version else None

    @staticmethod
    def prospect(
        db: Session, *, owner_id: UUID, version_id: UUID, external_id: str
    ) -> tuple[ArtifactVersion, Prospect]:
        version = db.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                Artifact.owner_id == owner_id,
                Artifact.archived_at.is_(None),
                ArtifactVersion.id == version_id,
                ArtifactVersion.schema_key == SCHEMA,
            )
        )
        if version is None:
            raise RecordNotFound("Discovery result not found")
        result = ProspectPage.model_validate((version.payload or {}).get("result", {}))
        matches = [item for item in result.items if item.external_id == external_id]
        if len(matches) != 1:
            raise RecordNotFound("Choose a person from this discovery result")
        return version, matches[0]

    @classmethod
    def import_contact(
        cls,
        db: Session,
        *,
        owner_id: UUID,
        version_id: UUID,
        external_id: str,
        record_id: UUID,
        request_id: UUID,
        company_id: UUID | None,
    ) -> tuple[Contact, bool]:
        version, prospect = cls.prospect(
            db, owner_id=owner_id, version_id=version_id, external_id=external_id
        )
        if not prospect.name_complete:
            raise ValueError("Reveal a complete name before adding this contact")
        # Serialize explicit imports for this actor, including cross-provider duplicate matching.
        db.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
        existing_evidence = db.scalar(
            select(cls).where(
                cls.owner_id == owner_id,
                cls.provider == prospect.provider,
                cls.external_id == prospect.external_id,
            )
        )
        if existing_evidence:
            contact = db.get(Contact, existing_evidence.contact_id)
            if contact is None or contact.archived_at:
                raise RecordConflict("The previously imported contact is archived")
            return contact, False
        identifiers = []
        if prospect.email:
            identifiers.append(func.lower(Contact.email) == prospect.email.lower())
        if prospect.linkedin_url:
            identifiers.append(
                func.rtrim(
                    func.regexp_replace(
                        func.regexp_replace(
                            func.lower(Contact.linkedin_url), r"^https?://(www\.)?", ""
                        ),
                        r"[?#].*$",
                        "",
                    ),
                    "/",
                )
                == prospect.linkedin_url.lower()
                .split("://", 1)[-1]
                .removeprefix("www.")
                .split("?", 1)[0]
                .split("#", 1)[0]
                .rstrip("/")
            )
        matches = (
            list(db.scalars(select(Contact).where(Contact.owner_id == owner_id, or_(*identifiers))))
            if identifiers
            else []
        )
        if len(matches) > 1:
            raise RecordConflict(
                "Multiple contacts match these identifiers. Resolve them before importing."
            )
        if matches and matches[0].archived_at:
            raise RecordConflict("A contact with these identifiers is archived")
        contact = matches[0] if matches else None
        created = contact is None
        if contact is None:
            if company_id:
                company = db.scalar(
                    select(Company).where(
                        Company.id == company_id,
                        Company.owner_id == owner_id,
                        Company.archived_at.is_(None),
                    )
                )
                if company is None:
                    raise RecordNotFound("Company not found")
                if company.domain and professional_domain(company.domain) != prospect.domain:
                    raise ValueError("The selected company has a different domain")
            contact = Contact(
                id=record_id,
                owner_id=owner_id,
                name=prospect.name,
                email=prospect.email,
                title=prospect.title,
                linkedin_url=prospect.linkedin_url,
                company_id=company_id,
                relationship="new",
            )
            db.add(contact)
            db.flush()
        db.add(
            cls(
                id=uuid5(record_id, "discovery-evidence"),
                owner_id=owner_id,
                contact_id=contact.id,
                provider=prospect.provider,
                external_id=prospect.external_id,
                source_artifact_id=version.artifact_id,
                source_version_id=version.id,
            )
        )
        record_event(
            db,
            owner_id,
            request_id,
            "contacts.discovery_imported",
            "contacts",
            contact.id,
            provider=prospect.provider,
            source_version_id=str(version.id),
            created=created,
        )
        db.flush()
        return contact, created

    @classmethod
    def fill_missing(
        cls,
        db: Session,
        *,
        owner_id: UUID,
        contact_id: UUID,
        version_id: UUID,
        external_id: str,
        fields: Sequence[str],
        expected_version: int,
        request_id: UUID,
    ) -> Contact:
        version, prospect = cls.prospect(
            db, owner_id=owner_id, version_id=version_id, external_id=external_id
        )
        contact = db.scalar(
            select(Contact).where(Contact.id == contact_id, Contact.owner_id == owner_id)
        )
        evidence = db.scalar(
            select(cls).where(
                cls.owner_id == owner_id,
                cls.contact_id == contact_id,
                cls.provider == prospect.provider,
                cls.external_id == prospect.external_id,
            )
        )
        if contact is None or evidence is None:
            raise RecordNotFound("Add this provider result to Contacts before filling details")
        if contact.archived_at or contact.row_version != expected_version:
            raise RecordConflict("This contact changed. Reopen it before filling details.")
        if (
            not fields
            or len(set(fields)) != len(fields)
            or set(fields) - {"email", "title", "linkedin_url"}
        ):
            raise ValueError("Choose missing contact fields")
        changes = {}
        for field in fields:
            value = getattr(prospect, field)
            if getattr(contact, field) or not value:
                raise RecordConflict(
                    "A selected field already has a value or has no provider value"
                )
            changes[field] = value
        contact.revise(changes, request_id=request_id)
        record_event(
            db,
            owner_id,
            request_id,
            "contacts.discovery_applied",
            "contacts",
            contact.id,
            source_version_id=str(version.id),
            fields=list(fields),
        )
        db.flush()
        return contact
