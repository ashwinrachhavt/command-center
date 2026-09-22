from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from command_center.api import schemas as s
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    Search,
    WriteKey,
    check_version,
    listing,
    owned,
    serialize,
    values,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.artifacts import (
    Artifact,
    ArtifactDerivation,
    ArtifactReview,
    ArtifactVersion,
    Document,
    DocumentType,
)

router = APIRouter(prefix="/api/v1", tags=["artifacts"])


def artifact_data(db: Database, artifact: Artifact) -> dict[str, Any]:
    data = serialize(artifact)
    data["latest_version"] = (
        db.scalar(
            select(func.max(ArtifactVersion.version)).where(
                ArtifactVersion.artifact_id == artifact.id
            )
        )
        or 0
    )
    facet = db.get(Document, artifact.id)
    data["document_type_id"] = str(facet.document_type_id) if facet else None
    return data


def version_data(db: Database, version: ArtifactVersion) -> dict[str, Any]:
    data = serialize(version)
    data["input_version_ids"] = [
        str(input_id)
        for input_id in db.scalars(
            select(ArtifactDerivation.input_version_id)
            .where(ArtifactDerivation.output_version_id == version.id)
            .order_by(ArtifactDerivation.input_version_id)
        )
    ]
    return data


@router.get("/document-types")
def document_types(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    return [serialize(row) for row in db.scalars(select(DocumentType).order_by(DocumentType.name))]


@router.get("/artifacts", response_model=s.Page[s.ArtifactRead])
def list_artifacts(
    identity: CurrentIdentity, db: Database, q: Search = "", limit: Limit = 30, offset: Offset = 0
) -> dict[str, Any]:
    page = listing(Artifact, db, identity.id, q, limit, offset)
    ids = [UUID(item["id"]) for item in page["items"]]
    versions = {
        key: value
        for key, value in db.execute(
            select(ArtifactVersion.artifact_id, func.max(ArtifactVersion.version))
            .where(ArtifactVersion.artifact_id.in_(ids))
            .group_by(ArtifactVersion.artifact_id)
        ).all()
    }
    documents = {
        key: value
        for key, value in db.execute(
            select(Document.artifact_id, Document.document_type_id).where(
                Document.artifact_id.in_(ids)
            )
        ).all()
    }
    for item in page["items"]:
        item["latest_version"] = versions.get(UUID(item["id"]), 0)
        item["document_type_id"] = documents.get(UUID(item["id"]))
    return page


@router.get("/artifacts/{record_id}", response_model=s.ArtifactRead)
def get_artifact(record_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    return artifact_data(db, owned(db, Artifact, record_id, identity.id))


@router.post("/artifacts", response_model=s.ArtifactRead, status_code=201)
def create_artifact(
    body: s.ArtifactCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        artifact = Artifact.draft(
            db,
            record_id=record_id,
            owner_id=identity.id,
            request_id=UUID(request.state.request_id),
            **values(body),
        )
        db.flush()
        return artifact_data(db, artifact)

    return write(db, identity.id, key, "POST:artifacts", body, change)


@router.patch("/artifacts/{record_id}", response_model=s.ArtifactRead)
def update_artifact(
    record_id: UUID,
    body: s.ArtifactUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        artifact = owned(db, Artifact, record_id, identity.id, lock=True)
        check_version(artifact, body.expected_version)
        artifact.revise(values(body, patch=True), request_id=UUID(request.state.request_id))
        db.flush()
        return artifact_data(db, artifact)

    return write(db, identity.id, key, f"PATCH:artifacts:{record_id}", body, change)


@router.post("/artifacts/{record_id}/archive", response_model=s.ArtifactRead)
def archive_artifact(
    record_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        artifact = owned(db, Artifact, record_id, identity.id, lock=True)
        check_version(artifact, body.expected_version)
        artifact.archive(request_id=UUID(request.state.request_id))
        db.flush()
        return artifact_data(db, artifact)

    return write(db, identity.id, key, f"ARCHIVE:artifacts:{record_id}", body, change)


@router.get("/artifacts/{record_id}/versions", response_model=list[s.VersionRead])
def versions(record_id: UUID, identity: CurrentIdentity, db: Database) -> Any:
    owned(db, Artifact, record_id, identity.id)
    rows = db.scalars(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == record_id)
        .order_by(ArtifactVersion.version.desc())
    ).all()
    return [version_data(db, version) for version in rows]


@router.post("/artifacts/{record_id}/versions", response_model=s.VersionRead, status_code=201)
def append_version(
    record_id: UUID,
    body: s.VersionCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(version_id: UUID) -> dict[str, Any]:
        artifact = owned(db, Artifact, record_id, identity.id, lock=True)
        check_version(artifact, body.expected_version)
        version = artifact.revise_text(
            body.text,
            based_on_version_id=body.based_on_version_id,
            version_id=version_id,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return version_data(db, version)

    return write(db, identity.id, key, f"POST:versions:{record_id}", body, change)


def owned_version(db: Database, version_id: UUID, actor_id: UUID) -> ArtifactVersion:
    version = db.scalar(
        select(ArtifactVersion)
        .join(Artifact)
        .where(ArtifactVersion.id == version_id, Artifact.owner_id == actor_id)
    )
    if version is None:
        raise HTTPException(404, "Version not found")
    return version


@router.get("/versions/{version_id}/reviews", response_model=list[s.ReviewRead])
def reviews(version_id: UUID, identity: CurrentIdentity, db: Database) -> Any:
    owned_version(db, version_id, identity.id)
    return db.scalars(
        select(ArtifactReview)
        .where(ArtifactReview.artifact_version_id == version_id)
        .order_by(ArtifactReview.created_at.desc())
    ).all()


@router.post("/versions/{version_id}/reviews", response_model=s.ReviewRead, status_code=201)
def review_version(
    version_id: UUID,
    body: s.ReviewCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    def change(review_id: UUID) -> dict[str, Any]:
        version = owned_version(db, version_id, identity.id)
        review = version.review(
            review_id=review_id,
            reviewer_id=identity.id,
            request_id=UUID(request.state.request_id),
            **values(body),
        )
        db.flush()
        return serialize(review)

    return write(db, identity.id, key, f"POST:reviews:{version_id}", body, change)


@router.get("/versions/{version_id}/lineage", response_model=list[s.VersionLineageRead])
def version_lineage(
    version_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    direction: Annotated[Literal["inputs", "outputs"], Query()] = "inputs",
) -> list[dict[str, Any]]:
    """Return bounded transitive lineage without exposing another owner's graph."""
    owned_version(db, version_id, identity.id)
    frontier = {version_id}
    seen = {version_id}
    result: list[dict[str, Any]] = []
    for depth in range(1, 9):
        if not frontier or len(result) >= 100:
            break
        if direction == "inputs":
            rows = db.execute(
                select(ArtifactVersion, Artifact, ArtifactDerivation.method)
                .join(
                    ArtifactDerivation,
                    ArtifactDerivation.input_version_id == ArtifactVersion.id,
                )
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(
                    ArtifactDerivation.output_version_id.in_(frontier),
                    Artifact.owner_id == identity.id,
                )
            ).all()
        else:
            rows = db.execute(
                select(ArtifactVersion, Artifact, ArtifactDerivation.method)
                .join(
                    ArtifactDerivation,
                    ArtifactDerivation.output_version_id == ArtifactVersion.id,
                )
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(
                    ArtifactDerivation.input_version_id.in_(frontier),
                    Artifact.owner_id == identity.id,
                )
            ).all()
        frontier = set()
        for version, artifact, method in rows:
            if version.id in seen:
                continue
            seen.add(version.id)
            frontier.add(version.id)
            result.append(
                s.VersionLineageRead(
                    artifact_id=artifact.id,
                    artifact_title=artifact.title,
                    artifact_kind=artifact.kind,
                    version_id=version.id,
                    version=version.version,
                    content_sha256=version.content_sha256,
                    media_type=version.media_type,
                    method=method,
                    depth=depth,
                ).model_dump(mode="json")
            )
    return result[:100]
