"""Replayable SSE over short, non-blocking database reads."""

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.core.identity import CurrentIdentity
from command_center.db.agent_events import AgentEvent
from command_center.db.agents import AgentRun

router = APIRouter(prefix="/api/v1", tags=["agents"])
POLL_SECONDS = 0.25
KEEPALIVE_SECONDS = 15


def authorize(engine: Engine, run_id: UUID, owner_id: UUID) -> None:
    with Session(engine) as db:
        found = db.scalar(
            select(AgentRun.id).where(AgentRun.id == run_id, AgentRun.owner_id == owner_id)
        )
    if found is None:
        raise HTTPException(404, "Record not found")


def read_page(
    engine: Engine, run_id: UUID, owner_id: UUID, after_sequence: int
) -> tuple[list[dict[str, object]], bool]:
    with Session(engine) as db:
        rows, terminal = AgentEvent.page(
            db,
            run_id=run_id,
            owner_id=owner_id,
            after_sequence=after_sequence,
        )
        return [row.envelope() for row in rows], terminal


def encode_event(event: dict[str, object]) -> str:
    return (
        "event: agent_event\n"
        f"id: {event['sequence']}\n"
        f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
    )


async def event_stream(
    request: Request,
    engine: Engine,
    run_id: UUID,
    owner_id: UUID,
    after_sequence: int,
) -> AsyncIterator[str]:
    cursor = after_sequence
    idle = 0.0
    while True:
        if await request.is_disconnected():
            return
        events, terminal = await asyncio.to_thread(read_page, engine, run_id, owner_id, cursor)
        for event in events:
            raw_sequence = event["sequence"]
            assert isinstance(raw_sequence, int)
            sequence = raw_sequence
            if sequence <= cursor:
                continue
            cursor = sequence
            idle = 0.0
            yield encode_event(event)
        if terminal:
            return
        await asyncio.sleep(POLL_SECONDS)
        idle += POLL_SECONDS
        if idle >= KEEPALIVE_SECONDS:
            idle = 0.0
            yield ": keepalive\n\n"


@router.get("/agent-runs/{run_id}/events")
async def run_events(
    run_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    after_sequence: int = Query(default=0, ge=0),
) -> StreamingResponse:
    engine = request.app.state.engine
    await asyncio.to_thread(authorize, engine, run_id, identity.id)
    return StreamingResponse(
        event_stream(request, engine, run_id, identity.id, after_sequence),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
