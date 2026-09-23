"""Save and revisit contact follow-ups; external delivery uses reviewed actions."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import EmailStr, Field, StringConstraints
from sqlalchemy import func, select

from command_center.api import schemas as s
from command_center.api.artifacts import artifact_data, version_data
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    WriteKey,
    check_version,
    owned,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.correspondence import FollowUp, plain_text
from command_center.db.crm import Contact

router = APIRouter(prefix="/api/v1", tags=["correspondence"])


class FollowUpCreate(s.Contract):
    channel: Literal["linkedin", "email"] = "linkedin"
    subject: str = Field(default="", max_length=300)
    text: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(max_length=50000)
    format: Literal["text", "html"] = "text"
    recipient_email: EmailStr | None = None
    source_version_ids: list[UUID] = Field(default_factory=list, max_length=20)


class FollowUpUpdate(FollowUpCreate, s.Revision):
    based_on_version_id: UUID


class FollowUpRead(s.ResponseContract):
    artifact: s.ArtifactRead
    version: s.VersionRead
    contact_id: UUID
    plain_text: Annotated[str, StringConstraints(strip_whitespace=False)]


class FollowUpSummary(s.ResponseContract):
    artifact_id: UUID
    title: str
    row_version: int
    version_id: UUID
    version: int
    channel: str
    subject: str
    preview: str
    updated_at: datetime


def read_follow_up(
    db: Database, artifact: Artifact, version: ArtifactVersion, contact_id: UUID
) -> dict[str, Any]:
    payload = version.payload or {}
    return {
        "artifact": artifact_data(db, artifact),
        "version": version_data(db, version),
        "contact_id": str(contact_id),
        "plain_text": plain_text(str(payload.get("text", "")), str(payload.get("format", "text"))),
    }


@router.get("/contacts/{contact_id}/follow-ups", response_model=s.Page[FollowUpSummary])
def follow_ups(
    contact_id: UUID, identity: CurrentIdentity, db: Database, limit: Limit = 20, offset: Offset = 0
) -> dict[str, Any]:
    owned(db, Contact, contact_id, identity.id)
    latest = (
        select(func.max(ArtifactVersion.version))
        .where(ArtifactVersion.artifact_id == Artifact.id)
        .correlate(Artifact)
        .scalar_subquery()
    )
    statement = (
        select(Artifact, ArtifactVersion)
        .join(FollowUp, FollowUp.artifact_id == Artifact.id)
        .join(
            ArtifactVersion,
            (ArtifactVersion.artifact_id == Artifact.id) & (ArtifactVersion.version == latest),
        )
        .where(
            FollowUp.owner_id == identity.id,
            FollowUp.contact_id == contact_id,
            Artifact.archived_at.is_(None),
        )
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.execute(
        statement.order_by(Artifact.updated_at.desc(), Artifact.id).limit(limit).offset(offset)
    ).all()
    return {
        "items": [
            {
                "artifact_id": artifact.id,
                "title": artifact.title,
                "row_version": artifact.row_version,
                "version_id": version.id,
                "version": version.version,
                "updated_at": artifact.updated_at,
                "channel": (version.payload or {}).get("channel", "linkedin"),
                "subject": (version.payload or {}).get("subject", ""),
                "preview": plain_text(
                    str((version.payload or {}).get("text", "")),
                    str((version.payload or {}).get("format", "text")),
                )[:240],
            }
            for artifact, version in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/contacts/{contact_id}/follow-ups", response_model=FollowUpRead, status_code=201)
def create_follow_up(
    contact_id: UUID,
    body: FollowUpCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    contact = owned(db, Contact, contact_id, identity.id)

    def change(record_id: UUID) -> dict[str, Any]:
        artifact, version = FollowUp.checkpoint(
            db,
            owner_id=identity.id,
            contact=contact,
            artifact=None,
            record_id=record_id,
            request_id=UUID(request.state.request_id),
            content=body.model_dump(mode="json", exclude={"source_version_ids"}),
            source_version_ids=body.source_version_ids,
        )
        return read_follow_up(db, artifact, version, contact.id)

    return write(db, identity.id, key, f"POST:contacts/{contact_id}/follow-ups", body, change)


@router.get("/follow-ups/{artifact_id}", response_model=FollowUpRead)
def get_follow_up(artifact_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    artifact = owned(db, Artifact, artifact_id, identity.id)
    facet = db.get(FollowUp, artifact_id)
    if facet is None:
        raise HTTPException(404, "Follow-up not found")
    version = db.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    )
    if version is None:
        raise HTTPException(404, "Follow-up version not found")
    return read_follow_up(db, artifact, version, facet.contact_id)


@router.patch("/follow-ups/{artifact_id}", response_model=FollowUpRead)
def update_follow_up(
    artifact_id: UUID,
    body: FollowUpUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        artifact = owned(db, Artifact, artifact_id, identity.id)
        check_version(artifact, body.expected_version)
        facet = db.get(FollowUp, artifact_id)
        if facet is None:
            raise HTTPException(404, "Follow-up not found")
        contact = owned(db, Contact, facet.contact_id, identity.id)
        artifact, version = FollowUp.checkpoint(
            db,
            owner_id=identity.id,
            contact=contact,
            artifact=artifact,
            record_id=record_id,
            request_id=UUID(request.state.request_id),
            based_on_version_id=body.based_on_version_id,
            content=body.model_dump(
                mode="json",
                exclude={"source_version_ids", "based_on_version_id", "expected_version"},
            ),
            source_version_ids=body.source_version_ids,
        )
        return read_follow_up(db, artifact, version, contact.id)

    return write(db, identity.id, key, f"PATCH:follow-ups/{artifact_id}", body, change)
