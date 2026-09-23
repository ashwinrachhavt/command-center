"""Explicit application-document requests and exact run-scoped draft outputs."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field, StringConstraints
from sqlalchemy import func, select

from command_center.api import schemas as s
from command_center.api.agents import available_profile
from command_center.api.application_preparations import human_only
from command_center.api.applications import owned_track
from command_center.api.workspace import Database, Limit, Offset, WriteKey, write
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity
from command_center.db.agents import AgentRun
from command_center.db.application_materials import ApplicationMaterial, MaterialKind
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.spending import ensure_default_spending_policy

router = APIRouter(prefix="/api/v1", tags=["application materials"])


class MaterialCreate(s.Contract):
    kind: MaterialKind
    job_version_id: UUID
    resume_version_id: UUID
    instructions: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        default="", max_length=3000
    )


class MaterialOutput(s.Contract):
    text: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1, max_length=30000
    )
    fact_revision_ids: list[UUID] = Field(min_length=1, max_length=200)


class MaterialSourceRead(s.Contract):
    artifact_id: UUID
    version_id: UUID
    version: int
    title: str
    archived: bool


class MaterialRead(s.Contract):
    id: UUID
    task_id: UUID
    kind: MaterialKind
    run_id: UUID
    session_id: UUID
    state: str
    error_code: str | None
    job: MaterialSourceRead
    resume: MaterialSourceRead
    output: MaterialSourceRead | None
    created_at: datetime


def material_source(db: Database, version_id: UUID) -> MaterialSourceRead:
    version = db.get(ArtifactVersion, version_id)
    assert version is not None
    artifact = db.get(Artifact, version.artifact_id)
    assert artifact is not None
    return MaterialSourceRead(
        artifact_id=artifact.id,
        version_id=version.id,
        version=version.version,
        title=artifact.title,
        archived=artifact.archived_at is not None,
    )


def material_read(db: Database, material: ApplicationMaterial) -> dict[str, Any]:
    run = db.get(AgentRun, material.run_id)
    assert run is not None and run.session_id is not None
    return MaterialRead(
        id=material.id,
        task_id=material.task_id,
        kind=material.kind,
        run_id=run.id,
        session_id=run.session_id,
        state=run.state,
        error_code=run.error_code,
        job=material_source(db, material.job_version_id),
        resume=material_source(db, material.resume_version_id),
        output=material_source(db, material.output_version_id)
        if material.output_version_id
        else None,
        created_at=material.created_at,
    ).model_dump(mode="json")


def owned_material(db: Database, identity: CurrentIdentity, record_id: UUID) -> ApplicationMaterial:
    material = db.scalar(
        select(ApplicationMaterial).where(
            ApplicationMaterial.id == record_id,
            ApplicationMaterial.owner_id == identity.id,
        )
    )
    if material is None:
        raise HTTPException(404, "Application document request not found")
    if identity.run_id is not None and identity.run_id != material.run_id:
        raise HTTPException(403, "This document request belongs to another agent run")
    return material


@router.get("/applications/{task_id}/materials", response_model=s.Page[MaterialRead])
def list_materials(
    task_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 10,
    offset: Offset = 0,
) -> dict[str, Any]:
    human_only(identity)
    owned_track(db, identity.id, task_id)
    query = select(ApplicationMaterial).where(
        ApplicationMaterial.task_id == task_id,
        ApplicationMaterial.owner_id == identity.id,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(ApplicationMaterial.created_at.desc(), ApplicationMaterial.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [material_read(db, row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/applications/{task_id}/materials", response_model=MaterialRead, status_code=202)
def create_material(
    task_id: UUID,
    body: MaterialCreate,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
    key: WriteKey,
) -> dict[str, Any]:
    human_only(identity)

    def change(record_id: UUID) -> dict[str, Any]:
        profile, revision = available_profile(request, "application")
        if not {
            "application_material_context",
            "save_application_material",
            "document_read",
        }.issubset(profile.tools):
            raise HTTPException(
                503, "The application profile needs document-generation tools enabled"
            )
        ensure_default_spending_policy(db, identity.id)
        material = ApplicationMaterial.start(
            db,
            record_id=record_id,
            owner_id=identity.id,
            task_id=task_id,
            kind=body.kind,
            job_version_id=body.job_version_id,
            resume_version_id=body.resume_version_id,
            instructions=body.instructions,
            configuration=profile.model_dump(mode="json"),
            revision=revision,
            request_id=UUID(request.state.request_id),
        )
        return material_read(db, material)

    return write(db, identity.id, key, f"POST:applications/{task_id}/materials", body, change)


@router.get("/application-materials/{record_id}/context")
def material_context(
    record_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    offset: Annotated[int, Query(ge=0, le=500)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    return owned_material(db, identity, record_id).context(db, offset=offset, limit=limit)


@router.post("/application-materials/{record_id}/output", response_model=MaterialRead)
def save_material(
    record_id: UUID,
    body: MaterialOutput,
    identity: CurrentIdentity,
    db: Database,
    request: Request,
    key: WriteKey,
) -> dict[str, Any]:
    material = owned_material(db, identity, record_id)
    if identity.run_id is None:
        raise HTTPException(403, "Generated outputs require the assigned application run")

    def change(output_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        material.save_output(
            db,
            text=body.text,
            fact_revision_ids=body.fact_revision_ids,
            record_id=output_id,
            request_id=UUID(request.state.request_id),
        )
        return material_read(db, material)

    return write(
        db, identity.id, key, f"POST:application-materials/{record_id}/output", body, change
    )
