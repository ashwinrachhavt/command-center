"""Thin HTTP controllers for reviewed candidate profile facts."""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import func, or_, select

from command_center.api import schemas as s
from command_center.api.workspace import Database, Limit, Offset, WriteKey, check_version
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity
from command_center.db.base import utc_now
from command_center.db.idempotency import RequestReceipt
from command_center.db.profile_facts import (
    FactField,
    ProfileFact,
    ProfileFactRevision,
    ReviewDecision,
    ReviewState,
)

router = APIRouter(prefix="/api/v1", tags=["profile"])


class FactProposalFields(s.Contract):
    value: str = Field(min_length=1, max_length=4000)
    context: str | None = Field(default=None, max_length=1000)
    source_version_id: UUID | None = None
    source_excerpt: str | None = Field(default=None, min_length=1, max_length=4000)
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_evidence_pair(self) -> "FactProposalFields":
        if self.source_excerpt is not None and self.source_version_id is None:
            raise ValueError("A source excerpt requires an exact source version")
        return self


class FactCreate(FactProposalFields):
    field: FactField


class FactVersionCreate(FactProposalFields):
    expected_version: int = Field(ge=1)


class FactReviewCreate(s.Revision):
    revision_id: UUID
    decision: ReviewDecision
    reason: str | None = Field(default=None, max_length=2000)


class FactRevisionRead(s.ResponseContract):
    id: UUID
    version: int
    value: str
    context: str | None
    source_version_id: UUID | None
    source_artifact_id: UUID | None
    source_excerpt: str | None
    valid_until: datetime | None
    review_state: ReviewState
    created_at: datetime


class FactRead(s.ResponseContract):
    id: UUID
    row_version: int
    field: FactField
    current: FactRevisionRead
    active: FactRevisionRead | None


class ApprovedFactRead(FactRevisionRead):
    fact_id: UUID
    field: FactField


def owned_fact(db: Database, fact_id: UUID, owner_id: UUID, *, lock: bool = False) -> ProfileFact:
    statement = select(ProfileFact).where(
        ProfileFact.id == fact_id, ProfileFact.owner_id == owner_id
    )
    if lock:
        statement = statement.with_for_update()
    fact = db.scalar(statement)
    if fact is None:
        raise HTTPException(404, "Fact not found")
    return fact


def revision_read(db: Database, revision: ProfileFactRevision) -> FactRevisionRead:
    return FactRevisionRead(
        id=revision.id,
        version=revision.version,
        value=revision.value,
        context=revision.context,
        source_version_id=revision.source_version_id,
        source_artifact_id=revision.source_artifact_id,
        source_excerpt=revision.source_excerpt,
        valid_until=revision.valid_until,
        review_state=revision.review_state(db),
        created_at=revision.created_at,
    )


def fact_read(db: Database, fact: ProfileFact) -> FactRead:
    current = db.get(ProfileFactRevision, fact.current_revision_id)
    active = (
        db.get(ProfileFactRevision, fact.active_revision_id) if fact.active_revision_id else None
    )
    if current is None:
        raise ValueError("Fact current revision is missing")
    return FactRead(
        id=fact.id,
        row_version=fact.row_version,
        field=fact.field,
        current=revision_read(db, current),
        active=revision_read(db, active) if active else None,
    )


def execute(
    db: Database,
    *,
    actor_id: UUID,
    key: UUID,
    operation: str,
    payload: dict[str, Any],
    change: Callable[[UUID], dict[str, Any]],
) -> dict[str, Any]:
    return RequestReceipt.execute(
        db,
        actor_id=actor_id,
        key=key,
        operation=operation,
        payload=payload,
        change=change,
    )


@router.post("/profile/facts", response_model=FactRead, status_code=status.HTTP_201_CREATED)
def create_fact(
    body: FactCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    request_id = UUID(request.state.request_id)

    def change(record_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        fact = ProfileFact.propose(
            db,
            record_id=record_id,
            owner_id=identity.id,
            field=body.field,
            value=body.value,
            context=body.context,
            source_version_id=body.source_version_id,
            source_excerpt=body.source_excerpt,
            valid_until=body.valid_until,
            agent_proposal=identity.run_id is not None,
            request_id=request_id,
        )
        db.flush()
        return fact_read(db, fact).model_dump(mode="json")

    return execute(
        db,
        actor_id=identity.id,
        key=key,
        operation="POST:/api/v1/profile/facts",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.get("/profile/facts/approved", response_model=s.Page[ApprovedFactRead])
def approved_facts(
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict[str, Any]:
    now = utc_now()
    statement = (
        select(ProfileFact, ProfileFactRevision)
        .join(ProfileFactRevision, ProfileFactRevision.id == ProfileFact.active_revision_id)
        .where(
            ProfileFact.owner_id == identity.id,
            or_(ProfileFactRevision.valid_until.is_(None), ProfileFactRevision.valid_until > now),
        )
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.execute(
        statement.order_by(ProfileFact.updated_at.desc(), ProfileFact.id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = []
    for fact, revision in rows:
        read = revision_read(db, revision)
        if read.review_state != "approved":
            continue
        items.append(
            ApprovedFactRead(
                **read.model_dump(),
                fact_id=fact.id,
                field=fact.field,
            )
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/profile/facts", response_model=s.Page[FactRead])
def list_facts(
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict[str, Any]:
    statement = select(ProfileFact).where(ProfileFact.owner_id == identity.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    facts = db.scalars(
        statement.order_by(ProfileFact.updated_at.desc(), ProfileFact.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [fact_read(db, fact) for fact in facts],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/profile/facts/{fact_id}/versions",
    response_model=FactRead,
    status_code=status.HTTP_201_CREATED,
)
def create_fact_version(
    fact_id: UUID,
    body: FactVersionCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    request_id = UUID(request.state.request_id)

    def change(_: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        fact = owned_fact(db, fact_id, identity.id, lock=True)
        check_version(fact, body.expected_version)
        fact.append_revision(
            value=body.value,
            context=body.context,
            source_version_id=body.source_version_id,
            source_excerpt=body.source_excerpt,
            valid_until=body.valid_until,
            agent_proposal=identity.run_id is not None,
            request_id=request_id,
        )
        db.flush()
        return fact_read(db, fact).model_dump(mode="json")

    return execute(
        db,
        actor_id=identity.id,
        key=key,
        operation=f"POST:/api/v1/profile/facts/{fact_id}/versions",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.get("/profile/facts/{fact_id}/versions", response_model=s.Page[FactRevisionRead])
def list_fact_versions(
    fact_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict[str, Any]:
    owned_fact(db, fact_id, identity.id)
    statement = select(ProfileFactRevision).where(ProfileFactRevision.fact_id == fact_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    revisions = db.scalars(
        statement.order_by(ProfileFactRevision.version.desc()).limit(limit).offset(offset)
    ).all()
    return {
        "items": [revision_read(db, revision) for revision in revisions],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/profile/facts/{fact_id}/reviews", response_model=FactRead)
def review_fact(
    fact_id: UUID,
    body: FactReviewCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    if identity.run_id is not None:
        raise HTTPException(403, "Only a human can review candidate facts")
    request_id = UUID(request.state.request_id)

    def change(_: UUID) -> dict[str, Any]:
        fact = owned_fact(db, fact_id, identity.id, lock=True)
        check_version(fact, body.expected_version)
        fact.review(
            revision_id=body.revision_id,
            reviewer_id=identity.id,
            reviewer_is_human=True,
            decision=body.decision,
            reason=body.reason,
            request_id=request_id,
        )
        db.flush()
        return fact_read(db, fact).model_dump(mode="json")

    return execute(
        db,
        actor_id=identity.id,
        key=key,
        operation=f"POST:/api/v1/profile/facts/{fact_id}/reviews",
        payload=body.model_dump(mode="json"),
        change=change,
    )
