"""Human-only autosave; saved draft data never authorizes an external effect."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid5

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import ConfigDict, Field, JsonValue
from sqlalchemy import func, select

from command_center.api import schemas as s
from command_center.api.workspace import Database, WriteKey
from command_center.core.identity import CurrentIdentity
from command_center.db.writing import WritingDraft, WritingRecoveryCopy

router = APIRouter(prefix="/api/v1/writing-drafts", tags=["writing"])
DraftScope = Annotated[str, Path(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")]


class DraftSave(s.Contract):
    model_config = ConfigDict(str_strip_whitespace=False)
    expected_version: int = Field(ge=0)
    data: dict[str, JsonValue]


class DraftClear(s.Contract):
    expected_version: int = Field(ge=0)


class DraftRead(s.ResponseContract):
    model_config = ConfigDict(str_strip_whitespace=False)
    scope_key: str
    row_version: int
    data: dict[str, JsonValue] | None
    updated_at: datetime | None
    last_save_key: UUID | None


class RecoverySummary(s.ResponseContract):
    id: UUID
    row_version: int
    created_at: datetime


class RecoveryRead(RecoverySummary):
    model_config = ConfigDict(str_strip_whitespace=False)
    data: dict[str, JsonValue]


class RecoveryHistory(s.ResponseContract):
    items: list[RecoverySummary]
    total: int
    next_before: int | None


def human_writer(identity: CurrentIdentity) -> None:
    if identity.run_id is not None:
        raise HTTPException(
            403, "Working drafts are edited by you; agents propose separate versions"
        )


def draft_read(scope_key: str, draft: WritingDraft | None) -> dict[str, Any]:
    return {
        "scope_key": scope_key,
        "row_version": draft.row_version if draft else 0,
        "data": draft.data if draft else None,
        "updated_at": draft.updated_at if draft else None,
        "last_save_key": draft.last_save_key if draft else None,
    }


@router.get("/{scope_key}", response_model=DraftRead)
def get_draft(scope_key: DraftScope, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    human_writer(identity)
    draft = db.scalar(
        select(WritingDraft).where(
            WritingDraft.owner_id == identity.id,
            WritingDraft.scope_key == scope_key,
        )
    )
    return draft_read(scope_key, draft)


@router.get("/{scope_key}/recovery", response_model=RecoveryHistory)
def recovery_history(
    scope_key: DraftScope,
    identity: CurrentIdentity,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    human_writer(identity)
    draft_id = uuid5(identity.id, f"writing-draft:{scope_key}")
    conditions = [WritingRecoveryCopy.draft_id == draft_id]
    if before is not None:
        conditions.append(WritingRecoveryCopy.row_version < before)
    rows = (
        db.execute(
            select(
                WritingRecoveryCopy.id,
                WritingRecoveryCopy.row_version,
                WritingRecoveryCopy.created_at,
            )
            .where(*conditions)
            .order_by(WritingRecoveryCopy.row_version.desc())
            .limit(limit + 1)
        )
        .mappings()
        .all()
    )
    return {
        "items": rows[:limit],
        "total": db.scalar(
            select(func.count())
            .select_from(WritingRecoveryCopy)
            .where(WritingRecoveryCopy.draft_id == draft_id)
        ),
        "next_before": rows[limit - 1]["row_version"] if len(rows) > limit else None,
    }


@router.get("/{scope_key}/recovery/{copy_id}", response_model=RecoveryRead)
def read_recovery(
    scope_key: DraftScope, copy_id: UUID, identity: CurrentIdentity, db: Database
) -> WritingRecoveryCopy:
    human_writer(identity)
    copy = db.scalar(
        select(WritingRecoveryCopy).where(
            WritingRecoveryCopy.id == copy_id,
            WritingRecoveryCopy.draft_id == uuid5(identity.id, f"writing-draft:{scope_key}"),
        )
    )
    if copy is None:
        raise HTTPException(404, "Recovery copy is no longer available")
    return copy


@router.put("/{scope_key}", response_model=DraftRead)
def save_draft(
    scope_key: DraftScope,
    body: DraftSave,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_writer(identity)
    draft = WritingDraft.save(
        db,
        owner_id=identity.id,
        scope_key=scope_key,
        data=body.data,
        expected_version=body.expected_version,
        save_key=key,
        request_id=UUID(request.state.request_id),
    )
    return draft_read(scope_key, draft)


@router.post("/{scope_key}/clear", response_model=DraftRead)
def clear_draft(
    scope_key: DraftScope,
    body: DraftClear,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_writer(identity)
    draft = WritingDraft.save(
        db,
        owner_id=identity.id,
        scope_key=scope_key,
        data=None,
        expected_version=body.expected_version,
        save_key=key,
        request_id=UUID(request.state.request_id),
    )
    return draft_read(scope_key, draft)
