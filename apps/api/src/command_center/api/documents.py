"""Upload, convert, review and select immutable document versions."""

import io
import logging
import re
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from command_center.api import schemas as s
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    WriteKey,
    check_version,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.artifacts import (
    Artifact,
    ArtifactVersion,
    Blob,
    Document,
    DocumentType,
)
from command_center.db.crm import CandidateProfile
from command_center.db.document_imports import DocumentImport
from command_center.db.idempotency import RequestReceipt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["documents"])
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCX_ENTRIES = 10_000
MAX_DOCX_EXPANDED_BYTES = 100 * 1024 * 1024
ArtifactFilter = Annotated[UUID | None, Query()]


class DocumentImportRead(s.ResponseContract):
    id: UUID
    artifact_id: UUID
    source_version_id: UUID
    task_id: UUID
    filename: str
    media_type: str
    byte_size: int
    state: Literal["queued", "running", "completed", "failed", "cancelled"]
    extraction_artifact_id: UUID | None
    extraction_version_id: UUID | None
    error: str | None
    created_at: datetime
    row_version: int


class ResumeSelection(s.Contract):
    version_id: UUID | None
    expected_version: int = Field(ge=1)


class ResumeSelectionRead(s.ResponseContract):
    row_version: int
    version_id: UUID | None
    artifact_id: UUID | None
    title: str | None
    filename: str | None
    media_type: str | None
    byte_size: int | None


def import_data(job: DocumentImport) -> dict[str, Any]:
    return DocumentImportRead.model_validate(job).model_dump(mode="json")


def clean_filename(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").replace("\\", "/")
    value = value.rsplit("/", 1)[-1].strip().strip(".")
    value = "".join(character for character in value if character.isprintable())
    value = re.sub(r"\s+", " ", value)[:255]
    if not value:
        raise HTTPException(422, "Choose a named PDF, DOCX, text or Markdown file")
    return value


def inspect_document(filename: str, content: bytes) -> tuple[str, str]:
    """Return a safe filename and content-derived media type."""
    safe_name = clean_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if not content:
        raise HTTPException(422, "The uploaded document is empty")
    if content.startswith(b"%PDF-"):
        if extension != ".pdf":
            raise HTTPException(422, "The filename must match the uploaded PDF content")
        return safe_name, "application/pdf"
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" in names and "word/document.xml" in names:
                unsafe_path = any(
                    entry.filename.startswith(("/", "\\"))
                    or ".." in entry.filename.replace("\\", "/").split("/")
                    for entry in entries
                )
                if (
                    len(entries) > MAX_DOCX_ENTRIES
                    or sum(entry.file_size for entry in entries) > MAX_DOCX_EXPANDED_BYTES
                    or any(entry.flag_bits & 0x1 for entry in entries)
                    or unsafe_path
                ):
                    raise HTTPException(422, "The DOCX archive expands beyond safe limits")
                if extension != ".docx":
                    raise HTTPException(422, "The filename must match the uploaded DOCX content")
                return (
                    safe_name,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
    except zipfile.BadZipFile:
        pass
    if extension not in {".txt", ".md", ".markdown"}:
        raise HTTPException(422, "Upload a PDF, DOCX, text or Markdown document")
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Text and Markdown documents must be valid UTF-8") from exc
    if "\x00" in decoded or any(
        ord(character) < 32 and character not in "\t\n\r" for character in decoded
    ):
        raise HTTPException(422, "The uploaded file is not safe text content")
    return safe_name, "text/markdown" if extension in {".md", ".markdown"} else "text/plain"


async def bounded_upload(file: UploadFile) -> bytes:
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    await file.close()
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "Documents are limited to 20 MiB")
    return content


def dispatch_import(import_id: UUID) -> None:
    """Best-effort dispatch after SQL commit; beat recovers broker outages."""
    try:
        from command_center.agents.queue import execute_document_import

        execute_document_import.apply_async(
            args=(str(import_id),), task_id=f"document-import:{import_id}", expires=300
        )
    except Exception:
        logger.warning("Document import %s remains queued for beat dispatch", import_id)


def owned_import(
    db: Session, import_id: UUID, owner_id: UUID, *, lock: bool = False
) -> DocumentImport:
    statement = select(DocumentImport).where(
        DocumentImport.id == import_id, DocumentImport.owner_id == owner_id
    )
    if lock:
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        raise HTTPException(404, "Document import not found")
    return job


@router.post("/documents/imports", response_model=DocumentImportRead, status_code=202)
async def import_document(
    request: Request,
    identity: CurrentIdentity,
    key: WriteKey,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    document_type_id: Annotated[UUID, Form()],
    artifact_id: Annotated[UUID | None, Form()] = None,
    expected_version: Annotated[int | None, Form(ge=1)] = None,
) -> dict[str, Any]:
    content = await bounded_upload(file)
    filename, media_type = inspect_document(file.filename or "", content)
    from command_center.core.storage import BlobStore

    stored = await run_in_threadpool(
        BlobStore(request.app.state.settings.blob_store_path).put, content
    )
    payload = {
        "title": title.strip(),
        "document_type_id": str(document_type_id),
        "artifact_id": str(artifact_id) if artifact_id else None,
        "expected_version": expected_version,
        "filename": filename,
        "media_type": media_type,
        "byte_size": stored.byte_size,
        "sha256": stored.sha256,
    }
    with Session(request.app.state.engine) as db, db.begin():
        request_id = UUID(request.state.request_id)

        def change(import_id: UUID) -> dict[str, Any]:
            job = DocumentImport.create_from_upload(
                db,
                import_id=import_id,
                owner_id=identity.id,
                title=title,
                document_type_id=document_type_id,
                blob_sha256=stored.sha256,
                blob_storage_key=stored.storage_key,
                filename=filename,
                media_type=media_type,
                byte_size=stored.byte_size,
                artifact_id=artifact_id,
                expected_version=expected_version,
                request_id=request_id,
            )
            return import_data(job)

        result = RequestReceipt.execute(
            db,
            actor_id=identity.id,
            key=key,
            operation="POST:document-imports",
            payload=payload,
            change=change,
        )
        current = owned_import(db, UUID(str(result["id"])), identity.id)
        result = import_data(current)
    if result["state"] == "queued":
        dispatch_import(UUID(str(result["id"])))
    return result


@router.get("/documents/imports", response_model=s.Page[DocumentImportRead])
def list_imports(
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 30,
    offset: Offset = 0,
    artifact_id: ArtifactFilter = None,
) -> dict[str, Any]:
    statement = select(DocumentImport).where(DocumentImport.owner_id == identity.id)
    if artifact_id:
        statement = statement.where(DocumentImport.artifact_id == artifact_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(DocumentImport.created_at.desc(), DocumentImport.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [import_data(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/documents/imports/{import_id}", response_model=DocumentImportRead)
def get_import(import_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    return import_data(owned_import(db, import_id, identity.id))


def change_import(
    action: Literal["retry", "cancel"],
    import_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    with Session(request.app.state.engine) as db, db.begin():

        def change(_: UUID) -> dict[str, Any]:
            job = owned_import(db, import_id, identity.id, lock=True)
            check_version(job, body.expected_version)
            getattr(job, action)(request_id=UUID(request.state.request_id))
            db.flush()
            return import_data(job)

        receipt = write(
            db,
            identity.id,
            key,
            f"POST:document-imports:{import_id}:{action}",
            body,
            change,
        )
        result = import_data(owned_import(db, UUID(str(receipt["id"])), identity.id))
    if action == "retry" and result["state"] == "queued":
        dispatch_import(import_id)
    return result


@router.post("/documents/imports/{import_id}/retry", response_model=DocumentImportRead)
def retry_import(
    import_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return change_import("retry", import_id, body, identity, key, request)


@router.post("/documents/imports/{import_id}/cancel", response_model=DocumentImportRead)
def cancel_import(
    import_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return change_import("cancel", import_id, body, identity, key, request)


@router.get("/artifacts/{artifact_id}/versions/{version_id}/download")
async def download_version(
    artifact_id: UUID, version_id: UUID, identity: CurrentIdentity, request: Request
) -> Response:
    with Session(request.app.state.engine) as db:
        row = db.execute(
            select(ArtifactVersion, Blob, Artifact, DocumentImport.filename)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .join(Blob, Blob.id == ArtifactVersion.blob_id)
            .outerjoin(DocumentImport, DocumentImport.source_version_id == ArtifactVersion.id)
            .where(
                Artifact.id == artifact_id,
                ArtifactVersion.id == version_id,
                Artifact.owner_id == identity.id,
                Artifact.archived_at.is_(None),
            )
        ).first()
        if row is None:
            raise HTTPException(404, "Downloadable version not found")
        version, _, artifact, imported_filename = row
        digest, media_type = version.content_sha256, version.media_type
        filename = clean_filename(imported_filename or artifact.title)
    from command_center.core.storage import BlobStore

    content = await run_in_threadpool(
        BlobStore(request.app.state.settings.blob_store_path).read, digest
    )
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


def resume_selection(db: Session, profile: CandidateProfile) -> dict[str, Any]:
    if profile.default_resume_version_id is None:
        return ResumeSelectionRead(
            row_version=profile.row_version,
            version_id=None,
            artifact_id=None,
            title=None,
            filename=None,
            media_type=None,
            byte_size=None,
        ).model_dump(mode="json")
    row = db.execute(
        select(ArtifactVersion, Artifact, Blob, DocumentImport.filename)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .join(Blob, Blob.id == ArtifactVersion.blob_id)
        .join(Document, Document.artifact_id == Artifact.id)
        .join(DocumentType, DocumentType.id == Document.document_type_id)
        .outerjoin(DocumentImport, DocumentImport.source_version_id == ArtifactVersion.id)
        .where(
            ArtifactVersion.id == profile.default_resume_version_id,
            Artifact.owner_id == profile.actor_id,
            Artifact.archived_at.is_(None),
            DocumentType.slug == "resume",
        )
    ).first()
    if row is None:
        raise HTTPException(409, "The selected resume version is unavailable")
    version, artifact, stored_blob, filename = row
    return ResumeSelectionRead(
        row_version=profile.row_version,
        version_id=version.id,
        artifact_id=artifact.id,
        title=artifact.title,
        filename=filename or artifact.title,
        media_type=version.media_type,
        byte_size=stored_blob.byte_size,
    ).model_dump(mode="json")


def profile_row(db: Session, actor_id: UUID, *, lock: bool = False) -> CandidateProfile:
    db.execute(insert(CandidateProfile).values(actor_id=actor_id).on_conflict_do_nothing())
    statement = select(CandidateProfile).where(CandidateProfile.actor_id == actor_id)
    if lock:
        statement = statement.with_for_update()
    profile = db.scalar(statement)
    assert profile is not None
    return profile


@router.get("/profile/default-resume", response_model=ResumeSelectionRead)
def get_default_resume(identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    return resume_selection(db, profile_row(db, identity.id))


@router.post("/profile/default-resume", response_model=ResumeSelectionRead)
def set_default_resume(
    body: ResumeSelection,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    if identity.run_id is not None:
        raise HTTPException(403, "Only the workspace owner can select the default resume")

    def change(_: UUID) -> dict[str, Any]:
        profile = profile_row(db, identity.id, lock=True)
        check_version(profile, body.expected_version)
        profile.select_default_resume(body.version_id, request_id=UUID(request.state.request_id))
        db.flush()
        return resume_selection(db, profile)

    return write(db, identity.id, key, "POST:profile:default-resume", body, change)
