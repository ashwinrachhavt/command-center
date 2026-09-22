"""Owned research-source capture and isolated script execution endpoints."""

import logging
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.api import schemas as s
from command_center.api.workspace import Database, WriteKey, check_version, owned, write
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity
from command_center.core.public_urls import normalize_public_url
from command_center.db.agents import AgentRun
from command_center.db.artifacts import Artifact, ArtifactVersion, TaskArtifact
from command_center.db.conversations import AgentSession
from command_center.db.evidence import SourceRecord
from command_center.db.idempotency import RequestReceipt
from command_center.db.models import Task
from command_center.db.research_executions import ResearchExecution, ResearchExecutionInput
from command_center.integrations.clients import ProviderError
from command_center.integrations.public_research import scrape_public

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["research-executions"])


class ResearchSourceCreate(s.Contract):
    url: str = Field(min_length=1, max_length=2000)


class ResearchSourceRead(s.ResponseContract):
    artifact_id: UUID
    version_id: UUID
    source_record_id: UUID
    url: str
    title: str
    retrieved_at: datetime


class ResearchExecutionCreate(s.Contract):
    script: str = Field(min_length=1, max_length=51_200)
    input_version_ids: list[UUID] = Field(min_length=1, max_length=20)
    output_title: str = Field(min_length=1, max_length=300)
    document_type: Literal["research", "interview"] = "research"


class ExecutionVersionRead(s.ResponseContract):
    artifact_id: UUID
    artifact_title: str
    version_id: UUID
    version: int
    role: Literal["script", "material", "public_source", "output"]


class ResearchExecutionRead(s.ResponseContract):
    id: UUID
    task_id: UUID
    state: Literal["queued", "running", "completed", "failed", "cancelled"]
    attempt_count: int
    max_attempts: int
    error_code: str | None
    policy_snapshot: dict[str, Any]
    script: ExecutionVersionRead
    inputs: list[ExecutionVersionRead]
    output: ExecutionVersionRead | None
    cleanup_pending: bool
    row_version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ExecutionRevision(s.Contract):
    expected_version: int = Field(ge=1)


def enforce_task_scope(db: Session, *, owner_id: UUID, run_id: UUID | None, task_id: UUID) -> None:
    if run_id is None:
        return
    scoped = db.scalar(
        select(AgentRun.id)
        .join(AgentSession, AgentSession.id == AgentRun.session_id)
        .where(
            AgentRun.id == run_id,
            AgentRun.owner_id == owner_id,
            AgentSession.owner_id == owner_id,
            AgentSession.task_id == task_id,
        )
    )
    if scoped is None:
        raise HTTPException(403, "This run cannot access another task's research")


def _version_summary(
    db: Session, version_id: UUID, role: Literal["script", "material", "public_source", "output"]
) -> ExecutionVersionRead:
    row = db.execute(
        select(ArtifactVersion, Artifact)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(ArtifactVersion.id == version_id)
    ).first()
    if row is None:
        raise ValueError("Research execution version lineage is incomplete")
    version, artifact = row
    return ExecutionVersionRead(
        artifact_id=artifact.id,
        artifact_title=artifact.title,
        version_id=version.id,
        version=version.version,
        role=role,
    )


def execution_read(db: Session, execution: ResearchExecution) -> dict[str, Any]:
    inputs = list(
        db.scalars(
            select(ResearchExecutionInput)
            .where(ResearchExecutionInput.execution_id == execution.id)
            .order_by(ResearchExecutionInput.version_id)
        )
    )
    value = ResearchExecutionRead(
        id=execution.id,
        task_id=execution.task_id,
        state=cast(
            Literal["queued", "running", "completed", "failed", "cancelled"],
            execution.state,
        ),
        attempt_count=execution.attempt_count,
        max_attempts=execution.max_attempts,
        error_code=execution.error_code,
        policy_snapshot=execution.policy_snapshot,
        script=_version_summary(db, execution.script_version_id, "script"),
        inputs=[
            _version_summary(
                db,
                item.version_id,
                cast(Literal["material", "public_source"], item.role),
            )
            for item in inputs
        ],
        output=(
            _version_summary(db, execution.output_version_id, "output")
            if execution.output_version_id
            else None
        ),
        cleanup_pending=(
            execution.container_lease_id is not None and execution.cleanup_confirmed_at is None
        ),
        row_version=execution.row_version,
        created_at=execution.created_at,
        updated_at=execution.updated_at,
        completed_at=execution.completed_at,
    )
    return value.model_dump(mode="json")


def owned_execution(
    db: Session, execution_id: UUID, owner_id: UUID, *, lock: bool = False
) -> ResearchExecution:
    statement = select(ResearchExecution).where(
        ResearchExecution.id == execution_id, ResearchExecution.owner_id == owner_id
    )
    if lock:
        statement = statement.with_for_update()
    execution = db.scalar(statement)
    if execution is None:
        raise HTTPException(404, "Research execution not found")
    return execution


def dispatch_research(execution_id: UUID) -> None:
    try:
        from command_center.agents import queue

        task = getattr(queue, "execute_research_execution", None)
        if task is None:
            return
        task.apply_async(
            args=(str(execution_id),),
            task_id=f"research-execution:{execution_id}",
            queue="execution",
            expires=300,
        )
    except Exception:
        logger.warning("Research execution %s remains queued for beat dispatch", execution_id)


@router.post(
    "/tasks/{task_id}/research-sources",
    response_model=ResearchSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def capture_research_source(
    task_id: UUID,
    body: ResearchSourceCreate,
    identity: CurrentIdentity,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    target = normalize_public_url(body.url)
    engine = request.app.state.engine
    with Session(engine) as db:
        owned(db, Task, task_id, identity.id)
        enforce_task_scope(db, owner_id=identity.id, run_id=identity.run_id, task_id=task_id)
    try:
        page = await scrape_public(request.app.state.firecrawl, target)
    except ProviderError as exc:
        raise HTTPException(503, "Web research is temporarily unavailable") from exc
    final_url = normalize_public_url(page.url)
    title = page.title.strip()[:300] or final_url
    request_id = UUID(request.state.request_id)
    with Session(engine) as db, db.begin():
        db.info["agent_run_id"] = getattr(request.state, "agent_run_id", None)

        def change(source_id: UUID) -> dict[str, Any]:
            fence_agent_write(request, db)
            task = owned(db, Task, task_id, identity.id, lock=True)
            if task.state in {"done", "cancelled"}:
                raise ValueError("Choose an active task")
            artifact = Artifact.draft(
                db,
                record_id=uuid5(source_id, "artifact"),
                owner_id=identity.id,
                title=title,
                kind="source",
                sensitivity="public",
                text=page.markdown,
                document_type_id=None,
                request_id=request_id,
            )
            version = db.scalar(
                select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
            )
            assert version is not None
            source = SourceRecord(
                id=source_id,
                artifact_version_id=version.id,
                provider=page.provider,
                account_scope="public",
                locator=final_url,
                extraction_method=page.extraction_method,
            )
            db.add_all([source, TaskArtifact(task_id=task.id, artifact_id=artifact.id)])
            db.flush()
            return ResearchSourceRead(
                artifact_id=artifact.id,
                version_id=version.id,
                source_record_id=source.id,
                url=final_url,
                title=artifact.title,
                retrieved_at=source.retrieved_at,
            ).model_dump(mode="json")

        return RequestReceipt.execute(
            db,
            actor_id=identity.id,
            key=key,
            operation=f"POST:task-research-source:{task_id}",
            payload={"url": target},
            change=change,
        )


@router.post(
    "/tasks/{task_id}/research-executions",
    response_model=ResearchExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_execution(
    task_id: UUID,
    body: ResearchExecutionCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    image = request.app.state.settings.research_sandbox_image
    if not image:
        raise HTTPException(503, "Research sandbox is not configured")
    policy = {
        "version": "research-sandbox.v1",
        "image": image,
        "network": "none",
        "memory_bytes": 256 * 1024 * 1024,
        "cpu_nanos": 1_000_000_000,
        "pids": 64,
        "wall_seconds": 90,
        "input_bytes": 20 * 1024 * 1024,
        "output_bytes": 1024 * 1024,
    }

    def change(execution_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        enforce_task_scope(db, owner_id=identity.id, run_id=identity.run_id, task_id=task_id)
        execution = ResearchExecution.create(
            db,
            record_id=execution_id,
            owner_id=identity.id,
            task_id=task_id,
            script=body.script,
            input_version_ids=body.input_version_ids,
            output_title=body.output_title,
            document_type_slug=body.document_type,
            policy_snapshot=policy,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return execution_read(db, execution)

    result = write(db, identity.id, key, f"POST:research-execution:{task_id}", body, change)
    if result["state"] == "queued":
        background.add_task(dispatch_research, UUID(str(result["id"])))
    return result


@router.get("/research-executions/{execution_id}", response_model=ResearchExecutionRead)
def execution_detail(execution_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    execution = owned_execution(db, execution_id, identity.id)
    enforce_task_scope(db, owner_id=identity.id, run_id=identity.run_id, task_id=execution.task_id)
    return execution_read(db, execution)


def change_execution(
    action: Literal["cancel", "retry"],
    execution_id: UUID,
    body: ExecutionRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        execution = owned_execution(db, execution_id, identity.id, lock=True)
        enforce_task_scope(
            db, owner_id=identity.id, run_id=identity.run_id, task_id=execution.task_id
        )
        check_version(execution, body.expected_version)
        getattr(execution, action)(request_id=UUID(request.state.request_id))
        db.flush()
        return execution_read(db, execution)

    result = write(
        db,
        identity.id,
        key,
        f"POST:research-execution:{execution_id}:{action}",
        body,
        change,
    )
    if action == "retry" and result["state"] == "queued":
        background.add_task(dispatch_research, execution_id)
    return result


@router.post("/research-executions/{execution_id}/cancel", response_model=ResearchExecutionRead)
def cancel_execution(
    execution_id: UUID,
    body: ExecutionRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    return change_execution("cancel", execution_id, body, identity, db, key, request, background)


@router.post("/research-executions/{execution_id}/retry", response_model=ResearchExecutionRead)
def retry_execution(
    execution_id: UUID,
    body: ExecutionRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
    background: BackgroundTasks,
) -> dict[str, Any]:
    return change_execution("retry", execution_id, body, identity, db, key, request, background)
