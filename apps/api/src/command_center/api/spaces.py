"""Owner-scoped HTTP contracts for persistent work contexts."""

from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from command_center.api import schemas as s
from command_center.api.artifacts import artifact_data
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    Search,
    WriteKey,
    check_version,
    owned,
    serialize,
    values,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.artifacts import Artifact
from command_center.db.spaces import LINK_MODELS, Space, SpaceLink, SpaceRecord, SpaceRecordType

router = APIRouter(prefix="/api/v1/spaces", tags=["spaces"])


class SpaceCreate(s.Contract):
    title: s.Title
    purpose: s.Notes | None = None


class SpaceUpdate(s.Revision):
    title: s.Title | None = None
    purpose: s.Notes | None = None


class SpaceLinkCreate(s.Revision):
    record_type: SpaceRecordType
    record_id: UUID


class SpaceRead(s.ResponseContract):
    id: UUID
    title: str
    purpose: str | None
    state: Literal["active", "archived"]
    row_version: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SpaceLinkRead(s.ResponseContract):
    id: UUID
    record_type: SpaceRecordType
    record_id: UUID
    created_at: datetime
    record: dict[str, Any]


class SpaceDetail(SpaceRead):
    links: list[SpaceLinkRead]


class SpaceTaskRead(s.ResponseContract):
    space: SpaceDetail
    task: s.TaskRead


def space_detail(db: Database, space: Space) -> dict[str, Any]:
    data = serialize(space)
    links = db.scalars(
        select(SpaceLink)
        .where(SpaceLink.space_id == space.id, SpaceLink.owner_id == space.owner_id)
        .order_by(SpaceLink.created_at, SpaceLink.id)
    ).all()
    records = {}
    for record_type, model in LINK_MODELS.items():
        ids = [link.record_id for link in links if link.record_type == record_type]
        if ids:
            for row in db.scalars(
                select(model).where(model.id.in_(ids), model.owner_id == space.owner_id)
            ):
                record = cast(SpaceRecord, row)
                records[(record_type, record.id)] = (
                    artifact_data(db, record) if isinstance(record, Artifact) else serialize(record)
                )
    data["links"] = [
        {
            "id": str(link.id),
            "record_type": link.record_type,
            "record_id": str(link.record_id),
            "created_at": link.created_at.isoformat(),
            "record": records[(link.record_type, link.record_id)],
        }
        for link in links
    ]
    return data


@router.get("", response_model=s.Page[SpaceRead])
def list_spaces(
    identity: CurrentIdentity,
    db: Database,
    state: Literal["active", "archived", "all"] = "active",
    q: Search = "",
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict[str, Any]:
    statement = select(Space).where(Space.owner_id == identity.id)
    if state != "all":
        statement = statement.where(Space.state == state)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(Space.title.ilike(f"%{escaped}%", escape="\\"))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(Space.updated_at.desc(), Space.id).limit(limit).offset(offset)
    )
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{space_id}", response_model=SpaceDetail)
def get_space(space_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    return space_detail(db, owned(db, Space, space_id, identity.id))


@router.post("", response_model=SpaceDetail, status_code=201)
def create_space(
    body: SpaceCreate, request: Request, identity: CurrentIdentity, db: Database, key: WriteKey
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        space = Space.create(
            db,
            record_id=record_id,
            owner_id=identity.id,
            title=body.title,
            purpose=body.purpose,
            request_id=UUID(request.state.request_id),
        )
        return space_detail(db, space)

    return write(db, identity.id, key, "POST:spaces", body, change)


@router.patch("/{space_id}", response_model=SpaceDetail)
def update_space(
    space_id: UUID,
    body: SpaceUpdate,
    request: Request,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        space = owned(db, Space, space_id, identity.id, lock=True)
        check_version(space, body.expected_version)
        space.revise(values(body, patch=True), request_id=UUID(request.state.request_id))
        db.flush()
        return space_detail(db, space)

    return write(db, identity.id, key, f"PATCH:spaces:{space_id}", body, change)


@router.post("/{space_id}/archive", response_model=SpaceDetail)
def archive_space(
    space_id: UUID,
    body: s.Revision,
    request: Request,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        space = owned(db, Space, space_id, identity.id, lock=True)
        check_version(space, body.expected_version)
        space.archive(request_id=UUID(request.state.request_id))
        db.flush()
        return space_detail(db, space)

    return write(db, identity.id, key, f"ARCHIVE:spaces:{space_id}", body, change)


@router.post("/{space_id}/restore", response_model=SpaceDetail)
def restore_space(
    space_id: UUID,
    body: s.Revision,
    request: Request,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        space = owned(db, Space, space_id, identity.id, lock=True)
        if space.row_version != body.expected_version:
            raise HTTPException(409, "This record changed. Refresh it before saving again.")
        space.restore(request_id=UUID(request.state.request_id))
        db.flush()
        return space_detail(db, space)

    return write(db, identity.id, key, f"RESTORE:spaces:{space_id}", body, change)


@router.post("/{space_id}/links", response_model=SpaceDetail)
def link_space_record(
    space_id: UUID,
    body: SpaceLinkCreate,
    request: Request,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        space = owned(db, Space, space_id, identity.id, lock=True)
        check_version(space, body.expected_version)
        space.link(body.record_type, body.record_id, request_id=UUID(request.state.request_id))
        db.flush()
        return space_detail(db, space)

    return write(db, identity.id, key, f"LINK:spaces:{space_id}", body, change)


@router.post("/{space_id}/links/{link_id}/unlink", response_model=SpaceDetail)
def unlink_space_record(
    space_id: UUID,
    link_id: UUID,
    body: s.Revision,
    request: Request,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        space = owned(db, Space, space_id, identity.id, lock=True)
        check_version(space, body.expected_version)
        space.unlink(link_id, request_id=UUID(request.state.request_id))
        db.flush()
        return space_detail(db, space)

    return write(db, identity.id, key, f"UNLINK:spaces:{space_id}:{link_id}", body, change)


@router.post("/{space_id}/tasks", response_model=SpaceTaskRead, status_code=201)
def create_space_task(
    space_id: UUID,
    body: s.TaskCreate,
    expected_version: Annotated[int, Query(ge=1)],
    request: Request,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(task_id: UUID) -> dict[str, Any]:
        space = owned(db, Space, space_id, identity.id, lock=True)
        check_version(space, expected_version)
        task = space.create_task(
            task_id=task_id, request_id=UUID(request.state.request_id), **values(body)
        )
        db.flush()
        return {"space": space_detail(db, space), "task": serialize(task)}

    return write(
        db,
        identity.id,
        key,
        f"TASK:spaces:{space_id}:version:{expected_version}",
        body,
        change,
    )
