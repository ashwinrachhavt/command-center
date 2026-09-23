"""Start CRM work explicitly; scoped agents attach a draft or cited company brief."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StringConstraints
from sqlalchemy import select

from command_center.api import schemas as s
from command_center.api.agents import available_profile
from command_center.api.research_executions import enforce_task_scope
from command_center.api.reviewed_actions import _human
from command_center.api.workspace import Database, WriteKey, write
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity
from command_center.db.agents import AgentRun
from command_center.db.artifacts import Artifact
from command_center.db.contact_research import ContactResearch
from command_center.db.conversations import AgentSession
from command_center.db.models import Task
from command_center.db.record_work import RecordResource, RecordWork
from command_center.db.spending import ensure_default_spending_policy

router = APIRouter(prefix="/api/v1", tags=["record work"])


class WorkCreate(s.Contract):
    research_requested: bool = False
    connection_note: bool = False
    instructions: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        default="", max_length=3000
    )
    channel: Literal["linkedin", "email"] = "linkedin"


class WorkOutput(s.Contract):
    contact_research: ContactResearch | None = None
    text: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1, max_length=30000
    )
    subject: str = Field(default="", max_length=300)
    source_version_ids: list[UUID] = Field(default_factory=list, max_length=20)


class WorkRead(s.ResponseContract):
    task_id: UUID
    session_id: UUID
    run_id: UUID
    state: str
    channel: str
    error_code: str | None
    contact_id: UUID | None
    company_id: UUID | None
    output_artifact_id: UUID | None
    output_version_id: UUID | None
    output_archived: bool
    created_at: datetime


def work_read(db: Database, work: RecordWork) -> dict[str, Any]:
    row = db.execute(
        select(AgentSession, AgentRun, Task)
        .join(AgentRun, AgentRun.session_id == AgentSession.id)
        .join(Task, Task.id == AgentSession.task_id)
        .where(AgentSession.owner_id == work.owner_id, AgentSession.task_id == work.task_id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id)
        .limit(1)
    ).one_or_none()
    if row is None:
        raise HTTPException(409, "The work conversation is unavailable")
    conversation, run, task = row
    artifact = db.get(Artifact, work.output_artifact_id) if work.output_artifact_id else None
    return WorkRead(
        task_id=work.task_id,
        session_id=conversation.id,
        run_id=run.id,
        state=run.state,
        channel=work.channel,
        error_code=run.error_code,
        contact_id=work.contact_id,
        company_id=work.company_id,
        output_artifact_id=work.output_artifact_id,
        output_version_id=work.output_version_id,
        output_archived=bool(artifact and artifact.archived_at),
        created_at=task.created_at,
    ).model_dump(mode="json")


def owned_work(db: Database, identity: CurrentIdentity, task_id: UUID) -> RecordWork:
    enforce_task_scope(db, owner_id=identity.id, run_id=identity.run_id, task_id=task_id)
    work = db.scalar(
        select(RecordWork).where(RecordWork.task_id == task_id, RecordWork.owner_id == identity.id)
    )
    if work is None:
        raise HTTPException(404, "Record work not found")
    return work


@router.post("/record-work/{resource}/{target_id}", response_model=WorkRead, status_code=201)
def start_work(
    resource: RecordResource,
    target_id: UUID,
    body: WorkCreate,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
    key: WriteKey,
) -> dict[str, Any]:
    _human(identity)

    def change(record_id: UUID) -> dict[str, Any]:
        profile_slug = (
            "connection"
            if resource == "contacts" and body.connection_note and not body.research_requested
            else "outreach"
            if resource == "contacts"
            else "research"
        )
        profile, revision = available_profile(request, profile_slug)
        if not {"record_work_context", "save_record_work"}.issubset(profile.tools):
            raise HTTPException(503, "The selected agent profile needs record-work tools enabled")
        if body.research_requested and not {
            "research_search",
            "capture_research_source",
            "document_read",
            "approved_profile",
        }.issubset(profile.tools):
            raise HTTPException(503, "The outreach profile needs public research and profile tools")
        ensure_default_spending_policy(db, identity.id)
        work = RecordWork.start(
            db,
            owner_id=identity.id,
            resource=resource,
            target_id=target_id,
            record_id=record_id,
            request_id=UUID(request.state.request_id),
            instructions=body.instructions,
            channel=body.channel,
            profile=profile_slug,
            configuration=profile.model_dump(mode="json"),
            revision=revision,
            research_requested=body.research_requested,
            connection_note=body.connection_note,
        )
        return work_read(db, work)

    return write(db, identity.id, key, f"POST:record-work/{resource}/{target_id}", body, change)


@router.get("/record-work/{resource}/{target_id}", response_model=list[WorkRead])
def list_work(
    resource: RecordResource, target_id: UUID, identity: CurrentIdentity, db: Database
) -> list[dict[str, Any]]:
    _human(identity)
    RecordWork.target(db, owner_id=identity.id, resource=resource, target_id=target_id)
    rows = RecordWork.recent(db, owner_id=identity.id, resource=resource, target_id=target_id)
    return [work_read(db, work) for work in rows]


@router.get("/tasks/{task_id}/record-work/context")
def work_context(task_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    return owned_work(db, identity, task_id).context(db)


@router.post("/tasks/{task_id}/record-work/output", response_model=WorkRead)
def save_work(
    task_id: UUID,
    body: WorkOutput,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
    key: WriteKey,
) -> dict[str, Any]:
    work = owned_work(db, identity, task_id)
    if identity.run_id is None:
        raise HTTPException(403, "Agent outputs require the scoped work conversation")

    def change(record_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        work.save_output(
            db,
            record_id=record_id,
            request_id=UUID(request.state.request_id),
            text=body.text,
            subject=body.subject,
            source_version_ids=body.source_version_ids,
            contact_research=body.contact_research,
        )
        return work_read(db, work)

    return write(db, identity.id, key, f"POST:tasks/{task_id}/record-work/output", body, change)
