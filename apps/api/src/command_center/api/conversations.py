"""HTTP boundaries for task and opportunity work conversations."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import func, select

from command_center.api import schemas as s
from command_center.api.agents import RunRead, available_profile
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    WriteKey,
    owned,
    serialize,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.agents import AgentRun
from command_center.db.conversations import AgentMessage, AgentSession

router = APIRouter(prefix="/api/v1", tags=["agent-sessions"])


class SessionCreate(s.Contract):
    title: str = Field(default="New conversation", min_length=1, max_length=300)
    task_id: UUID | None = None
    opportunity_id: UUID | None = None

    @model_validator(mode="after")
    def one_scope(self) -> "SessionCreate":
        if self.task_id is not None and self.opportunity_id is not None:
            raise ValueError("Choose at most one conversation scope")
        return self


class SessionRead(s.RecordRead):
    title: str
    task_id: UUID | None
    opportunity_id: UUID | None
    last_sequence: int


class MessageCreate(s.Contract):
    content: str = Field(min_length=1, max_length=20000)
    profile: str = Field(default="lead", min_length=1, max_length=100)
    provider: Literal["openai", "gemini", "mistral", "cohere"] | None = None
    model: str | None = Field(default=None, max_length=100)
    fresh_answer: bool = False


class AnswerCacheRead(s.Contract):
    source_run_id: UUID
    source_completed_at: datetime
    expires_at: datetime


class MessageRead(s.RecordRead):
    session_id: UUID
    run_id: UUID | None
    sequence: int
    author: Literal["user", "assistant"]
    profile: str
    content: str
    answer_cache: AnswerCacheRead | None = None


AfterSequence = Annotated[int, Query(ge=0)]


@router.post("/agent-sessions", response_model=SessionRead, status_code=201)
def create_session(
    body: SessionCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        if body.task_id is None and body.opportunity_id is None:
            return serialize(
                AgentSession.open_chat(
                    db,
                    record_id=record_id,
                    owner_id=identity.id,
                    title=body.title,
                    request_id=UUID(request.state.request_id),
                )
            )
        conversation = AgentSession.open(
            db,
            record_id=record_id,
            owner_id=identity.id,
            task_id=body.task_id,
            opportunity_id=body.opportunity_id,
            request_id=UUID(request.state.request_id),
        )
        return serialize(conversation)

    return write(db, identity.id, key, "POST:agent-sessions", body, change)


@router.get("/agent-sessions", response_model=s.Page[SessionRead])
def sessions(
    identity: CurrentIdentity,
    db: Database,
    task_id: UUID | None = None,
    opportunity_id: UUID | None = None,
    q: Annotated[str, Query(max_length=300)] = "",
    standalone: bool = False,
    limit: Limit = 30,
    offset: Offset = 0,
) -> dict[str, Any]:
    statement = select(AgentSession).where(
        AgentSession.owner_id == identity.id, AgentSession.archived_at.is_(None)
    )
    if task_id is not None:
        statement = statement.where(AgentSession.task_id == task_id)
    if opportunity_id is not None:
        statement = statement.where(AgentSession.opportunity_id == opportunity_id)
    if standalone:
        statement = statement.where(
            AgentSession.task_id.is_(None), AgentSession.opportunity_id.is_(None)
        )
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(AgentSession.title.ilike(f"%{escaped}%", escape="\\"))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/agent-sessions/{record_id}", response_model=SessionRead)
def session_detail(record_id: UUID, identity: CurrentIdentity, db: Database) -> AgentSession:
    return owned(db, AgentSession, record_id, identity.id)


@router.get("/agent-sessions/{record_id}/messages", response_model=s.Page[MessageRead])
def messages(
    record_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    after_sequence: AfterSequence = 0,
    limit: Limit = 30,
    offset: Offset = 0,
) -> dict[str, Any]:
    owned(db, AgentSession, record_id, identity.id)
    statement = select(AgentMessage).where(
        AgentMessage.owner_id == identity.id,
        AgentMessage.session_id == record_id,
        AgentMessage.sequence > after_sequence,
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(AgentMessage.sequence.asc()).limit(limit).offset(offset)
    ).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/agent-sessions/{record_id}/messages",
    response_model=MessageRead,
    status_code=201,
)
def receive_message(
    record_id: UUID,
    body: MessageCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        conversation = owned(db, AgentSession, record_id, identity.id)
        profile, revision = available_profile(request, body.profile, body.provider, body.model)
        message = conversation.receive(
            content=body.content,
            fresh_answer=body.fresh_answer,
            profile=body.profile,
            configuration=profile.model_dump(mode="json"),
            revision=revision,
            request_id=UUID(request.state.request_id),
        )
        return serialize(message)

    return write(db, identity.id, key, f"POST:agent-sessions:{record_id}:messages", body, change)


@router.get("/agent-sessions/{record_id}/runs", response_model=s.Page[RunRead])
def session_runs(
    record_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 30,
    offset: Offset = 0,
) -> dict[str, Any]:
    owned(db, AgentSession, record_id, identity.id)
    statement = select(AgentRun).where(
        AgentRun.owner_id == identity.id,
        AgentRun.session_id == record_id,
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(AgentRun.created_at.desc(), AgentRun.id).limit(limit).offset(offset)
    ).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
