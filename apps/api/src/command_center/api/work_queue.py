"""Human-owned dashboard reads over the canonical work and task projections."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from command_center.api import schemas as s
from command_center.api.workspace import Database, Limit, Offset
from command_center.core.identity import CurrentIdentity
from command_center.db.models import Actor
from command_center.db.work_queue import TaskView, WorkLane, daily_tasks_page, work_queue_page

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class WorkQueueItem(s.Contract):
    id: UUID
    kind: Literal["question", "run", "action", "browser", "artifact"]
    title: str
    state: str
    updated_at: datetime
    task_id: UUID | None
    opportunity_id: UUID | None
    run_id: UUID | None
    artifact_id: UUID | None
    version_id: UUID | None
    detail: str
    action_kind: str | None


class DailyTaskRead(s.TaskRead):
    due_status: Literal["overdue", "today", "upcoming", "unscheduled"]


class DailyTaskCounts(s.Contract):
    today: int
    upcoming: int
    unscheduled: int
    snoozed: int


class DailyTasksRead(s.Page[DailyTaskRead]):
    timezone: str
    today: date
    counts: DailyTaskCounts


def human_owner(identity: CurrentIdentity, session: Database) -> None:
    actor = session.get(Actor, identity.id)
    if identity.run_id is not None or actor is None or actor.kind != "human" or not actor.active:
        raise HTTPException(403, "The dashboard requires the active human owner")


@router.get("/work", response_model=s.Page[WorkQueueItem])
def work(
    identity: CurrentIdentity,
    session: Database,
    lane: WorkLane = "attention",
    limit: Limit = 6,
    offset: Offset = 0,
) -> s.Page[WorkQueueItem]:
    human_owner(identity, session)
    return s.Page[WorkQueueItem].model_validate(
        work_queue_page(session, identity.id, lane=lane, limit=limit, offset=offset)
    )


@router.get("/tasks", response_model=DailyTasksRead)
def tasks(
    identity: CurrentIdentity,
    session: Database,
    view: TaskView = "today",
    timezone: Annotated[str, Query(max_length=100)] = "UTC",
    limit: Limit = 6,
    offset: Offset = 0,
) -> DailyTasksRead:
    human_owner(identity, session)
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "Choose a valid IANA timezone") from exc
    return DailyTasksRead.model_validate(
        daily_tasks_page(session, identity.id, view=view, timezone=zone, limit=limit, offset=offset)
    )
