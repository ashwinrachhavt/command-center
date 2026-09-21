from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import Field

from command_center.api import schemas as s
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    Search,
    WriteKey,
    archive_record,
    listing,
    serialize,
    update_record,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.crm import record_event
from command_center.db.memory import MemoryItem

router = APIRouter(prefix="/api/v1/memories", tags=["memory"])


class MemoryCreate(s.Contract):
    title: s.Name
    content: str = Field(min_length=1, max_length=10000)
    kind: Literal["note", "preference"] = "note"


class MemoryUpdate(MemoryCreate, s.Revision):
    pass


class MemoryRead(MemoryCreate, s.RecordRead):
    source: str


@router.get("", response_model=s.Page[MemoryRead])
def memories(
    identity: CurrentIdentity, db: Database, q: Search = "", limit: Limit = 30, offset: Offset = 0
) -> dict[str, Any]:
    return listing(MemoryItem, db, identity.id, q, limit, offset)


@router.post("", response_model=MemoryRead, status_code=201)
def remember(
    body: MemoryCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        item = MemoryItem(
            id=record_id,
            owner_id=identity.id,
            **body.model_dump(),
            source="agent" if identity.run_id else "human",
        )
        db.add(item)
        record_event(
            db,
            identity.id,
            UUID(request.state.request_id),
            "memory.created",
            "memory_items",
            record_id,
            source=item.source,
        )
        db.flush()
        return serialize(item)

    return write(db, identity.id, key, "POST:memories", body, change)


@router.patch("/{record_id}", response_model=MemoryRead)
def edit_memory(
    record_id: UUID,
    body: MemoryUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return update_record(
        MemoryItem, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.post("/{record_id}/archive", response_model=MemoryRead)
def forget(
    record_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return archive_record(
        MemoryItem, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )
