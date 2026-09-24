from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import StringConstraints
from sqlalchemy import select

from command_center.api import schemas as s
from command_center.api.workspace import Database
from command_center.core.identity import CurrentIdentity
from command_center.db.artifacts import Artifact, ArtifactVersion

router = APIRouter(prefix="/api/v1", tags=["documents"])


class DocumentTextRead(s.ResponseContract):
    artifact_id: UUID
    version_id: UUID
    title: str
    text: Annotated[str, StringConstraints(strip_whitespace=False)]
    offset: int
    next_offset: int | None
    total_chars: int


@router.get("/documents/versions/{version_id}/text", response_model=DocumentTextRead)
def read_document_text(
    version_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=12000)] = 12000,
) -> DocumentTextRead:
    row = db.execute(
        select(ArtifactVersion, Artifact)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(ArtifactVersion.id == version_id, Artifact.owner_id == identity.id)
    ).first()
    if row is None:
        raise HTTPException(404, "Artifact version not found")
    version, artifact = row
    text = (version.payload or {}).get("text")
    if not isinstance(text, str):
        raise HTTPException(409, "This version has no extracted text; open its document import")
    end = min(offset + limit, len(text))
    return DocumentTextRead(
        artifact_id=artifact.id,
        version_id=version.id,
        title=artifact.title,
        text=text[offset:end],
        offset=offset,
        next_offset=end if end < len(text) else None,
        total_chars=len(text),
    )
