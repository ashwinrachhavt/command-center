"""Fenced Docling conversion with independent lease renewal."""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.core.storage import BlobStore
from command_center.db.artifacts import (
    Artifact,
    ArtifactDerivation,
    ArtifactVersion,
    Document,
    TaskArtifact,
)
from command_center.db.document_imports import DocumentImport
from command_center.integrations.docling import DoclingClient, ExtractedDocument
from command_center.integrations.jev import JevProvider

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15
CONVERSION_SECONDS = 240


class ConversionLeaseLost(Exception):
    pass


@dataclass(frozen=True)
class ClaimedImport:
    id: UUID
    lease_id: UUID
    source_version_id: UUID
    content_sha256: str
    filename: str
    media_type: str


def leased(db: Session, import_id: UUID, lease_id: UUID) -> DocumentImport:
    job = db.scalar(
        select(DocumentImport).where(DocumentImport.id == import_id).with_for_update(key_share=True)
    )
    if job is None or not job.accepts(lease_id):
        raise ConversionLeaseLost()
    return job


def claim(engine: Engine, import_id: UUID) -> ClaimedImport | None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        job = DocumentImport.claim(db, import_id)
        if job is None:
            return None
        version = db.get(ArtifactVersion, job.source_version_id)
        if version is None or version.blob_id is None:
            raise ValueError("Document source version is unavailable")
        db.flush()
        assert job.lease_id is not None
        return ClaimedImport(
            id=job.id,
            lease_id=job.lease_id,
            source_version_id=job.source_version_id,
            content_sha256=version.content_sha256,
            filename=job.filename,
            media_type=job.media_type,
        )


def renew(engine: Engine, claimed: ClaimedImport) -> None:
    with Session(engine) as db, db.begin():
        leased(db, claimed.id, claimed.lease_id).renew(claimed.lease_id)


async def convert_with_heartbeat(
    engine: Engine,
    settings: Settings,
    claimed: ClaimedImport,
    content: bytes,
) -> ExtractedDocument:
    api_key = settings.docling_api_key.get_secret_value()
    client = DoclingClient(settings.docling_url, api_key)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await asyncio.to_thread(renew, engine, claimed)

    conversion = asyncio.create_task(client.convert(content, claimed.filename, claimed.media_type))
    pulse = asyncio.create_task(heartbeat())
    try:
        async with asyncio.timeout(CONVERSION_SECONDS):
            done, _ = await asyncio.wait({conversion, pulse}, return_when=asyncio.FIRST_COMPLETED)
            if pulse in done:
                await pulse
            return await conversion
    finally:
        for task in (conversion, pulse):
            if not task.done():
                task.cancel()
        await asyncio.gather(conversion, pulse, return_exceptions=True)
        await client.close()


def persist_output(
    engine: Engine,
    claimed: ClaimedImport,
    output: ExtractedDocument,
    provider: JevProvider = "typesafe",
) -> None:
    if not output.text.strip() or not isinstance(output.document, dict):
        raise ValueError("Document conversion did not produce reviewable content")
    with Session(engine) as db, db.begin():
        job = leased(db, claimed.id, claimed.lease_id)
        source = db.get(ArtifactVersion, job.source_version_id)
        assert source is not None
        source_artifact = db.get(Artifact, job.artifact_id)
        source_document = db.get(Document, job.artifact_id)
        if (
            source_artifact is None
            or source_artifact.archived_at is not None
            or source_document is None
        ):
            raise ConversionLeaseLost()
        artifact_id = uuid5(job.id, "extraction-artifact")
        version_id = uuid5(job.id, "extraction-version")
        extraction = Artifact(
            id=artifact_id,
            owner_id=job.owner_id,
            created_by_id=job.owner_id,
            title=f"Extracted text: {source_artifact.title}",
            kind="document",
            sensitivity=source_artifact.sensitivity,
        )
        db.add(extraction)
        db.flush()
        db.add(
            Document(
                artifact_id=artifact_id,
                document_type_id=source_document.document_type_id,
            )
        )
        derived = extraction.append_payload(
            {
                "text": output.text,
                "document": output.document,
                "producer_version": output.producer_version,
            },
            schema_key="docling.document.v1",
            version_id=version_id,
            request_id=uuid4(),
        )
        db.flush()
        db.add_all(
            [
                ArtifactDerivation(
                    output_version_id=derived.id,
                    input_version_id=source.id,
                    method="docling.convert",
                ),
                TaskArtifact(task_id=job.task_id, artifact_id=extraction.id),
            ]
        )
        job.complete(
            claimed.lease_id,
            extraction_artifact_id=extraction.id,
            extraction_version_id=derived.id,
            request_id=uuid4(),
        )
        # Persist dispatch intent in the extraction transaction; beat recovers
        # broker outages. Classification cannot roll back the completed import.
        from command_center.db.document_decisions import DocumentDecision, DocumentPolicy

        policy = db.get(DocumentPolicy, job.owner_id)
        if policy and policy.classification_mode == "after_extraction":
            try:
                with db.begin_nested():
                    DocumentDecision.request(
                        db,
                        decision_id=uuid5(job.id, "automatic-classification"),
                        owner_id=job.owner_id,
                        artifact_id=job.artifact_id,
                        metadata_revision=source_artifact.row_version,
                        source_version_id=job.source_version_id,
                        extraction_version_id=derived.id,
                        provider=provider,
                        request_id=uuid4(),
                        automatic=True,
                    )
            except ValueError:
                logger.warning(
                    "Document import %s completed; classification inputs need review", job.id
                )


def fail(engine: Engine, claimed: ClaimedImport, error: str) -> None:
    with Session(engine) as db, db.begin():
        job = db.scalar(
            select(DocumentImport).where(DocumentImport.id == claimed.id).with_for_update()
        )
        if job is not None:
            job.fail(claimed.lease_id, error=error, request_id=uuid4())


def perform_document_import(engine: Engine, settings: Settings, import_id: UUID | str) -> bool:
    """Claim at most once, do file/network I/O outside SQL, then fence the output."""
    claimed = claim(engine, UUID(str(import_id)))
    if claimed is None:
        return False
    try:
        content = BlobStore(settings.blob_store_path).read(claimed.content_sha256)
        output = asyncio.run(convert_with_heartbeat(engine, settings, claimed, content))
        persist_output(engine, claimed, output, settings.jev_provider)
    except ConversionLeaseLost:
        return True
    except TimeoutError:
        fail(engine, claimed, "conversion_timeout")
    except Exception:
        logger.warning(
            "Document import %s failed; source and provider details suppressed", claimed.id
        )
        fail(engine, claimed, "conversion_failed")
    return True
