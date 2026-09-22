"""Thin HTTP boundary for reviewed, scoped reusable memory."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import func, or_, select

from command_center.api import schemas as s
from command_center.api.workspace import Database, Limit, Offset, Search, WriteKey, check_version
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity, Identity
from command_center.db.agents import AgentRun
from command_center.db.conversations import AgentSession
from command_center.db.idempotency import RequestReceipt
from command_center.db.memory import (
    MemoryItem,
    MemoryKind,
    MemoryReviewDecision,
    MemoryReviewState,
    MemoryRevision,
    MemoryScope,
    MemorySource,
)
from command_center.db.models import Task

router = APIRouter(prefix="/api/v1/memories", tags=["memory"])


class MemoryFields(s.Contract):
    title: s.Name
    content: str = Field(min_length=1, max_length=10000)
    kind: MemoryKind = "note"
    scope_type: MemoryScope = "global"
    scope_id: UUID | None = None
    valid_until: AwareDatetime | None = None
    source_artifact_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=2000)
    confirm: bool = False

    @model_validator(mode="after")
    def validate_scope(self) -> "MemoryFields":
        if self.scope_type == "global" and self.scope_id is not None:
            raise ValueError("Global memory cannot name a task or opportunity")
        return self


class MemoryCreate(MemoryFields):
    pass


class MemoryUpdate(MemoryFields, s.Revision):
    pass


class MemoryReviewCreate(s.Revision):
    revision_id: UUID
    decision: MemoryReviewDecision
    reason: str | None = Field(default=None, max_length=2000)


class MemoryRevisionRead(s.ResponseContract):
    id: UUID
    version: int
    title: str
    content: str
    kind: MemoryKind
    scope_type: MemoryScope
    scope_id: UUID | None
    valid_until: datetime | None
    source: MemorySource
    source_run_id: UUID | None
    source_artifact_id: UUID | None
    reason: str | None
    review_state: MemoryReviewState
    created_at: datetime


class MemoryRead(s.ResponseContract):
    id: UUID
    row_version: int
    title: str
    content: str
    kind: MemoryKind
    source: MemorySource
    updated_at: datetime
    current: MemoryRevisionRead
    active: MemoryRevisionRead | None


class RetrievedMemoryRead(MemoryRevisionRead):
    memory_id: UUID


def human_only(identity: Identity) -> None:
    if identity.run_id is not None:
        raise HTTPException(403, "Reusable memory review requires the human owner")


def owned_memory(
    db: Database, memory_id: UUID, owner_id: UUID, *, lock: bool = False
) -> MemoryItem:
    statement = select(MemoryItem).where(
        MemoryItem.id == memory_id,
        MemoryItem.owner_id == owner_id,
    )
    if lock:
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(404, "Memory not found")
    return item


def revision_read(db: Database, revision: MemoryRevision) -> MemoryRevisionRead:
    return MemoryRevisionRead(
        id=revision.id,
        version=revision.version,
        title=revision.title,
        content=revision.content,
        kind=revision.kind,
        scope_type=revision.scope_type,
        scope_id=revision.scope_id,
        valid_until=revision.valid_until,
        source=revision.source,
        source_run_id=revision.source_run_id,
        source_artifact_id=revision.source_artifact_id,
        reason=revision.reason,
        review_state=revision.review_state(db),
        created_at=revision.created_at,
    )


def memory_read(db: Database, item: MemoryItem) -> MemoryRead:
    current = db.get(MemoryRevision, item.current_revision_id)
    active = db.get(MemoryRevision, item.active_revision_id) if item.active_revision_id else None
    if current is None:
        raise ValueError("Memory current revision is missing")
    current_read = revision_read(db, current)
    return MemoryRead(
        id=item.id,
        row_version=item.row_version,
        title=current.title,
        content=current.content,
        kind=current.kind,
        source=current.source,
        updated_at=item.updated_at,
        current=current_read,
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


def run_scope(db: Database, identity: Identity) -> tuple[UUID | None, UUID | None]:
    if identity.run_id is None:
        return None, None
    row = db.execute(
        select(AgentSession.task_id, AgentSession.opportunity_id)
        .join(AgentRun, AgentRun.session_id == AgentSession.id)
        .where(
            AgentRun.id == identity.run_id,
            AgentRun.owner_id == identity.id,
            AgentSession.owner_id == identity.id,
        )
    ).one_or_none()
    if row is None:
        return None, None
    task_id, opportunity_id = row
    if task_id is not None:
        task_opportunity_id = db.scalar(
            select(Task.opportunity_id).where(
                Task.id == task_id,
                Task.owner_id == identity.id,
            )
        )
        return task_id, task_opportunity_id
    return None, opportunity_id


def write_scope(
    db: Database,
    identity: Identity,
    scope_type: MemoryScope,
    scope_id: UUID | None,
) -> tuple[MemoryScope, UUID | None]:
    if identity.run_id is None or scope_type == "global":
        return scope_type, scope_id
    task_id, opportunity_id = run_scope(db, identity)
    derived = task_id if scope_type == "task" else opportunity_id
    if derived is None or (scope_id is not None and scope_id != derived):
        raise HTTPException(403, "Agent memory scope must match its current run")
    return scope_type, derived


@router.get("/retrieve", response_model=s.Page[RetrievedMemoryRead])
def retrieve_memories(
    identity: CurrentIdentity,
    db: Database,
    q: Search = "",
    task_id: UUID | None = None,
    opportunity_id: UUID | None = None,
    limit: int = Query(default=10, ge=1, le=20),
) -> dict[str, Any]:
    if identity.run_id is not None:
        derived_task, derived_opportunity = run_scope(db, identity)
        if task_id is not None and task_id != derived_task:
            raise HTTPException(403, "Agent memory scope must match its current run")
        if opportunity_id is not None and opportunity_id != derived_opportunity:
            raise HTTPException(403, "Agent memory scope must match its current run")
        task_id, opportunity_id = derived_task, derived_opportunity
    rows = MemoryItem.retrieve(
        db,
        owner_id=identity.id,
        query=q,
        task_id=task_id,
        opportunity_id=opportunity_id,
        limit=limit,
    )
    return {
        "items": [
            RetrievedMemoryRead(
                **revision_read(db, revision).model_dump(),
                memory_id=item.id,
            )
            for item, revision in rows
        ],
        "total": len(rows),
        "limit": limit,
        "offset": 0,
    }


@router.get("", response_model=s.Page[MemoryRead])
def memories(
    identity: CurrentIdentity,
    db: Database,
    q: Search = "",
    limit: Limit = 30,
    offset: Offset = 0,
) -> dict[str, Any]:
    human_only(identity)
    statement = (
        select(MemoryItem)
        .join(MemoryRevision, MemoryRevision.id == MemoryItem.current_revision_id)
        .where(MemoryItem.owner_id == identity.id, MemoryItem.archived_at.is_(None))
    )
    if q:
        pattern = f"%{q}%"
        statement = statement.where(
            or_(MemoryRevision.title.ilike(pattern), MemoryRevision.content.ilike(pattern))
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(
        statement.order_by(MemoryItem.updated_at.desc(), MemoryItem.id).limit(limit).offset(offset)
    ).all()
    return {
        "items": [memory_read(db, item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def remember(
    body: MemoryCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    if identity.run_id is not None and body.confirm:
        raise HTTPException(403, "Agents can only propose reusable memory")
    request_id = UUID(request.state.request_id)

    def change(record_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        source: Literal["human", "agent"] = "agent" if identity.run_id else "human"
        scope_type, scope_id = write_scope(db, identity, body.scope_type, body.scope_id)
        item = MemoryItem.propose(
            db,
            record_id=record_id,
            owner_id=identity.id,
            title=body.title,
            content=body.content,
            kind=body.kind,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_until=body.valid_until,
            source=source,
            source_run_id=identity.run_id,
            source_artifact_id=body.source_artifact_id,
            reason=body.reason,
            request_id=request_id,
        )
        if body.confirm:
            assert item.current_revision_id is not None
            item.review(
                revision_id=item.current_revision_id,
                reviewer_id=identity.id,
                reviewer_is_human=True,
                decision="approved",
                reason="Confirmed by the owner when saved.",
                request_id=request_id,
            )
        db.flush()
        return memory_read(db, item).model_dump(mode="json")

    return execute(
        db,
        actor_id=identity.id,
        key=key,
        operation="POST:/api/v1/memories",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.patch("/{memory_id}", response_model=MemoryRead)
def edit_memory(
    memory_id: UUID,
    body: MemoryUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    if identity.run_id is not None and body.confirm:
        raise HTTPException(403, "Agents can only propose reusable memory")
    request_id = UUID(request.state.request_id)

    def change(_: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        item = owned_memory(db, memory_id, identity.id, lock=True)
        check_version(item, body.expected_version)
        source: Literal["human", "agent"] = "agent" if identity.run_id else "human"
        scope_type, scope_id = write_scope(db, identity, body.scope_type, body.scope_id)
        revision = item.append_revision(
            title=body.title,
            content=body.content,
            kind=body.kind,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_until=body.valid_until,
            source=source,
            source_run_id=identity.run_id,
            source_artifact_id=body.source_artifact_id,
            reason=body.reason,
            request_id=request_id,
        )
        if body.confirm:
            item.review(
                revision_id=revision.id,
                reviewer_id=identity.id,
                reviewer_is_human=True,
                decision="approved",
                reason="Confirmed by the owner when saved.",
                request_id=request_id,
            )
        db.flush()
        return memory_read(db, item).model_dump(mode="json")

    return execute(
        db,
        actor_id=identity.id,
        key=key,
        operation=f"PATCH:/api/v1/memories/{memory_id}",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.get("/{memory_id}/versions", response_model=s.Page[MemoryRevisionRead])
def memory_versions(
    memory_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict[str, Any]:
    human_only(identity)
    owned_memory(db, memory_id, identity.id)
    statement = select(MemoryRevision).where(MemoryRevision.memory_id == memory_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    revisions = db.scalars(
        statement.order_by(MemoryRevision.version.desc()).limit(limit).offset(offset)
    ).all()
    return {
        "items": [revision_read(db, revision) for revision in revisions],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/{memory_id}/reviews", response_model=MemoryRead)
def review_memory(
    memory_id: UUID,
    body: MemoryReviewCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_only(identity)
    request_id = UUID(request.state.request_id)

    def change(_: UUID) -> dict[str, Any]:
        item = owned_memory(db, memory_id, identity.id, lock=True)
        check_version(item, body.expected_version)
        item.review(
            revision_id=body.revision_id,
            reviewer_id=identity.id,
            reviewer_is_human=True,
            decision=body.decision,
            reason=body.reason,
            request_id=request_id,
        )
        db.flush()
        return memory_read(db, item).model_dump(mode="json")

    return execute(
        db,
        actor_id=identity.id,
        key=key,
        operation=f"POST:/api/v1/memories/{memory_id}/reviews",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.post("/{memory_id}/archive", response_model=MemoryRead)
def forget(
    memory_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_only(identity)
    request_id = UUID(request.state.request_id)

    def change(_: UUID) -> dict[str, Any]:
        item = owned_memory(db, memory_id, identity.id, lock=True)
        check_version(item, body.expected_version)
        item.archive(request_id=request_id)
        db.flush()
        return memory_read(db, item).model_dump(mode="json")

    return execute(
        db,
        actor_id=identity.id,
        key=key,
        operation=f"POST:/api/v1/memories/{memory_id}/archive",
        payload=body.model_dump(mode="json"),
        change=change,
    )
