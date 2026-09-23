"""Owned application tracker; saved packages are evidence of preparation, not submission."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import Row, func, or_, select

from command_center.api import schemas as s
from command_center.api.application_preparations import (
    ApplicationPreparationRead,
    human_only,
    preparation_read,
)
from command_center.api.browser_contracts import FieldResult, ResumeFile
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    Search,
    WriteKey,
    check_version,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.application_preparations import ApplicationPreparation
from command_center.db.applications import ApplicationStatus, ApplicationTrack
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.browser import BrowserCommand, BrowserSnapshot
from command_center.db.models import Task

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])


@router.get(
    "/{task_id}/packages/{preparation_id}/versions/{version_id}",
    response_model=ApplicationPreparationRead,
)
def package_version(
    task_id: UUID,
    preparation_id: UUID,
    version_id: UUID,
    identity: CurrentIdentity,
    db: Database,
) -> ApplicationPreparationRead:
    human_only(identity)
    row = db.execute(
        select(ApplicationPreparation, ArtifactVersion)
        .join(
            ArtifactVersion,
            ArtifactVersion.artifact_id == ApplicationPreparation.artifact_id,
        )
        .where(
            ApplicationPreparation.task_id == task_id,
            ApplicationPreparation.id == preparation_id,
            ApplicationPreparation.owner_id == identity.id,
            ArtifactVersion.id == version_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Application package version not found")
    return preparation_read(*row)


class ApplicationRead(s.Contract):
    task: s.TaskRead
    status: ApplicationStatus
    row_version: int
    submission_recorded_at: datetime | None
    preparation_id: UUID
    snapshot_id: UUID
    page_url: str
    page_title: str
    origin: str
    preparation_count: int
    last_activity_at: datetime
    job_context_artifact_id: UUID | None


class ApplicationContextCreate(s.Revision):
    job_title: str = Field(default="", max_length=300)
    company_name: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=30000)


class ApplicationContextRead(s.Contract):
    artifact_id: UUID
    artifact_title: str
    expected_version: int
    version_id: UUID
    version: int
    text: str
    job_title: str
    company_name: str
    page_url: str
    extraction_method: str
    truncated: bool
    created_at: datetime


class ApplicationRevision(s.Revision):
    status: ApplicationStatus


class ApplicationFillRead(s.Contract):
    id: UUID
    preparation_version_id: UUID
    state: str
    field_results: dict[str, FieldResult]
    created_at: datetime
    completed_at: datetime | None


class ApplicationPackageRead(s.Contract):
    id: UUID
    snapshot_id: UUID
    artifact_id: UUID
    version_id: UUID
    version: int
    created_at: datetime
    page_title: str
    page_url: str
    resume: ResumeFile | None
    resume_artifact_id: UUID | None
    cover_letter: ResumeFile | None = None
    cover_letter_artifact_id: UUID | None = None
    latest_fill: ApplicationFillRead | None


def application_read(row: Row[Any]) -> ApplicationRead:
    track, task, preparation_id, snapshot_id, page_url, title, origin, count, activity = row
    return ApplicationRead(
        task=s.TaskRead.model_validate(task),
        status=track.status,
        row_version=track.row_version,
        submission_recorded_at=track.submission_recorded_at,
        preparation_id=preparation_id,
        snapshot_id=snapshot_id,
        page_url=page_url,
        page_title=title,
        origin=origin,
        preparation_count=count,
        last_activity_at=activity,
        job_context_artifact_id=track.job_context_artifact_id,
    )


def owned_track(
    db: Database, owner_id: UUID, task_id: UUID, *, lock: bool = False
) -> ApplicationTrack:
    query = select(ApplicationTrack).where(
        ApplicationTrack.task_id == task_id, ApplicationTrack.owner_id == owner_id
    )
    if lock:
        query = query.with_for_update()
    track = db.scalar(query)
    if track is None:
        raise HTTPException(404, "Application not found")
    return track


def context_read(db: Database, track: ApplicationTrack) -> ApplicationContextRead | None:
    version = track.current_context_version(db)
    if version is None:
        return None
    artifact = db.get(Artifact, version.artifact_id)
    assert artifact is not None
    payload = version.payload or {}
    return ApplicationContextRead(
        artifact_id=artifact.id,
        artifact_title=artifact.title,
        expected_version=artifact.row_version,
        version_id=version.id,
        version=version.version,
        text=payload["text"],
        job_title=payload["job_title"],
        company_name=payload["company_name"],
        page_url=payload["page_url"],
        extraction_method=payload["extraction_method"],
        truncated=payload["truncated"],
        created_at=version.created_at,
    )


@router.get("/{task_id}/job-context", response_model=ApplicationContextRead | None)
def read_context(
    task_id: UUID, identity: CurrentIdentity, db: Database
) -> ApplicationContextRead | None:
    human_only(identity)
    return context_read(db, owned_track(db, identity.id, task_id))


@router.post("/{task_id}/job-context", response_model=ApplicationContextRead, status_code=201)
def add_context(
    task_id: UUID,
    body: ApplicationContextCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_only(identity)

    def change(record_id: UUID) -> dict[str, Any]:
        track = owned_track(db, identity.id, task_id, lock=True)
        check_version(track, body.expected_version)
        detail = application_detail(db, identity.id, task_id)
        track.capture_context(
            db,
            record_id=record_id,
            request_id=UUID(request.state.request_id),
            page_url=detail.page_url,
            context={
                **body.model_dump(exclude={"expected_version"}),
                "extraction_method": "manual",
                "truncated": False,
            },
        )
        db.flush()
        result = context_read(db, track)
        assert result is not None
        return result.model_dump(mode="json")

    return write(db, identity.id, key, f"POST:applications/{task_id}/job-context", body, change)


def application_detail(db: Database, owner_id: UUID, task_id: UUID) -> ApplicationRead:
    row = db.execute(
        ApplicationTrack.query(owner_id).where(ApplicationTrack.task_id == task_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Application not found")
    return application_read(row)


@router.get("", response_model=s.Page[ApplicationRead])
def applications(
    identity: CurrentIdentity,
    db: Database,
    q: Search = "",
    limit: Limit = 30,
    offset: Offset = 0,
    status: Annotated[ApplicationStatus | None, Query()] = None,
) -> dict[str, Any]:
    human_only(identity)
    query = ApplicationTrack.query(identity.id)
    if status:
        query = query.where(ApplicationTrack.status == status)
    if q:
        query = query.where(
            or_(
                Task.title.icontains(q, autoescape=True),
                BrowserSnapshot.title.icontains(q, autoescape=True),
                BrowserSnapshot.origin.icontains(q, autoescape=True),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(
            func.greatest(
                ApplicationTrack.updated_at, Task.updated_at, ApplicationPreparation.updated_at
            ).desc(),
            ApplicationTrack.task_id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [application_read(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{task_id}", response_model=ApplicationRead)
def detail(task_id: UUID, identity: CurrentIdentity, db: Database) -> ApplicationRead:
    human_only(identity)
    return application_detail(db, identity.id, task_id)


@router.patch("/{task_id}", response_model=ApplicationRead)
def update(
    task_id: UUID,
    body: ApplicationRevision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human_only(identity)

    def change(_: UUID) -> dict[str, Any]:
        track = db.scalar(
            select(ApplicationTrack)
            .where(
                ApplicationTrack.task_id == task_id,
                ApplicationTrack.owner_id == identity.id,
            )
            .with_for_update()
        )
        if track is None:
            raise HTTPException(404, "Application not found")
        check_version(track, body.expected_version)
        track.set_status(body.status, request_id=UUID(request.state.request_id))
        db.flush()
        return application_detail(db, identity.id, task_id).model_dump(mode="json")

    return write(db, identity.id, key, f"PATCH:applications/{task_id}", body, change)


@router.get("/{task_id}/packages", response_model=s.Page[ApplicationPackageRead])
def packages(
    task_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    offset: Offset = 0,
) -> dict[str, Any]:
    human_only(identity)
    application_detail(db, identity.id, task_id)
    predicate = (
        ApplicationPreparation.task_id == task_id,
        ApplicationPreparation.owner_id == identity.id,
    )
    total = (
        db.scalar(select(func.count()).select_from(ApplicationPreparation).where(*predicate)) or 0
    )
    rows = (
        db.execute(
            select(
                ApplicationPreparation.id,
                ApplicationPreparation.snapshot_id,
                ApplicationPreparation.artifact_id,
                ArtifactVersion.id.label("version_id"),
                ArtifactVersion.version,
                ApplicationPreparation.created_at,
                BrowserSnapshot.title.label("page_title"),
                BrowserSnapshot.page_url,
                ArtifactVersion.payload["resume"].label("resume"),
                ArtifactVersion.payload["cover_letter"].label("cover_letter"),
            )
            .join(ArtifactVersion, ArtifactVersion.id == ApplicationPreparation.current_version_id)
            .join(BrowserSnapshot, BrowserSnapshot.id == ApplicationPreparation.snapshot_id)
            .where(*predicate)
            .order_by(ApplicationPreparation.created_at.desc(), ApplicationPreparation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .mappings()
        .all()
    )
    # Query metadata/results only; listing history never loads each answer body.
    artifact_ids = [row["artifact_id"] for row in rows]
    fills = (
        db.execute(
            select(
                ArtifactVersion.artifact_id,
                BrowserCommand.id,
                BrowserCommand.preparation_version_id,
                BrowserCommand.state,
                BrowserCommand.field_results,
                BrowserCommand.created_at,
                BrowserCommand.completed_at,
            )
            .join(ArtifactVersion, ArtifactVersion.id == BrowserCommand.preparation_version_id)
            .where(
                BrowserCommand.owner_id == identity.id,
                ArtifactVersion.artifact_id.in_(artifact_ids),
            )
            .distinct(ArtifactVersion.artifact_id)
            .order_by(
                ArtifactVersion.artifact_id,
                BrowserCommand.created_at.desc(),
                BrowserCommand.id.desc(),
            )
        )
        .mappings()
        .all()
        if artifact_ids
        else []
    )
    by_artifact = {
        row["artifact_id"]: {key: value for key, value in row.items() if key != "artifact_id"}
        for row in fills
    }
    resume_ids = [
        UUID(row[key]["version_id"])
        for row in rows
        for key in ("resume", "cover_letter")
        if row[key]
    ]
    resume_artifacts = (
        {
            str(version_id): artifact_id
            for version_id, artifact_id in db.execute(
                select(ArtifactVersion.id, ArtifactVersion.artifact_id)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(Artifact.owner_id == identity.id, ArtifactVersion.id.in_(resume_ids))
            )
        }
        if resume_ids
        else {}
    )
    return {
        "items": [
            dict(
                row,
                latest_fill=by_artifact.get(row["artifact_id"]),
                cover_letter_artifact_id=resume_artifacts.get(row["cover_letter"]["version_id"])
                if row["cover_letter"]
                else None,
                resume_artifact_id=resume_artifacts.get(row["resume"]["version_id"])
                if row["resume"]
                else None,
            )
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
