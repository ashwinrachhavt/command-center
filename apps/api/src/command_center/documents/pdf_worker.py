"""Fenced exact-version PDF rendering and immutable blob persistence."""

import logging
import time
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.core.storage import BlobStore
from command_center.db.artifacts import Artifact, ArtifactVersion, Blob
from command_center.db.pdf_exports import PdfExport
from command_center.integrations.pdf_renderer import (
    DockerWeasyPrintRenderer,
    PdfRenderer,
    PdfRenderRequest,
)
from command_center.integrations.sandbox import SandboxError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedExport:
    id: UUID
    lease_id: UUID
    image: str
    title: str
    markdown: str


def claim(engine: Engine, export_id: UUID) -> ClaimedExport | None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        export = PdfExport.claim(db, export_id)
        if export is None:
            return None
        row = db.execute(
            select(ArtifactVersion, Artifact)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ArtifactVersion.id == export.source_version_id,
                Artifact.id == export.source_artifact_id,
                Artifact.owner_id == export.owner_id,
                Artifact.archived_at.is_(None),
            )
        ).first()
        if row is None:
            raise ValueError("PDF source is unavailable")
        version, artifact = row
        markdown = version.payload.get("text") if version.payload else None
        if not isinstance(markdown, str):
            raise ValueError("PDF source is not editable text")
        db.flush()
        assert export.lease_id is not None
        return ClaimedExport(
            export.id, export.lease_id, export.renderer_revision, artifact.title, markdown
        )


class LeasePulse:
    def __init__(self, engine: Engine, export_id: UUID, lease_id: UUID):
        self.engine, self.export_id, self.lease_id = engine, export_id, lease_id
        self.next_check = 0.0

    def cancelled(self) -> bool:
        now = time.monotonic()
        if now < self.next_check:
            return False
        self.next_check = now + 5
        with Session(self.engine) as db, db.begin():
            export = db.scalar(
                select(PdfExport)
                .where(PdfExport.id == self.export_id)
                .with_for_update(key_share=True)
            )
            if export is None or not export.accepts(self.lease_id):
                return True
            export.renew(self.lease_id)
        return False


def _mark_cleanup(engine: Engine, claimed: ClaimedExport) -> None:
    with Session(engine) as db, db.begin():
        export = db.get(PdfExport, claimed.id)
        if export is not None:
            export.mark_cleanup_confirmed(claimed.lease_id)


def _fail(engine: Engine, claimed: ClaimedExport, code: str, *, cleanup_confirmed: bool) -> None:
    with Session(engine) as db, db.begin():
        export = db.scalar(select(PdfExport).where(PdfExport.id == claimed.id).with_for_update())
        if export is not None:
            export.fail(claimed.lease_id, code, cleanup=cleanup_confirmed)


def perform_pdf_export(
    engine: Engine,
    settings: Settings,
    export_id: UUID | str,
    renderer: PdfRenderer | None = None,
) -> bool:
    claimed = claim(engine, UUID(str(export_id)))
    if claimed is None:
        return False
    adapter = renderer or DockerWeasyPrintRenderer()
    pulse = LeasePulse(engine, claimed.id, claimed.lease_id)
    try:
        result = adapter.render(
            PdfRenderRequest(
                export_id=claimed.id,
                lease_id=claimed.lease_id,
                image=claimed.image,
                title=claimed.title,
                markdown=claimed.markdown,
            ),
            cancelled=pulse.cancelled,
        )
        stored = BlobStore(settings.blob_store_path).put(result.data)
        _mark_cleanup(engine, claimed)
        with Session(engine) as db, db.begin():
            export = db.scalar(
                select(PdfExport).where(PdfExport.id == claimed.id).with_for_update()
            )
            if export is None or not export.accepts(claimed.lease_id):
                return True
            db.execute(
                insert(Blob)
                .values(
                    id=uuid5(NAMESPACE_URL, "command-center:blob:" + stored.sha256),
                    sha256=stored.sha256,
                    storage_key=stored.storage_key,
                    byte_size=stored.byte_size,
                )
                .on_conflict_do_nothing(index_elements=[Blob.sha256])
            )
            blob = db.scalar(select(Blob).where(Blob.sha256 == stored.sha256))
            if blob is None:
                raise ValueError("Stored PDF metadata is unavailable")
            export.complete(claimed.lease_id, blob=blob, request_id=uuid4())
        return True
    except SandboxError as exc:
        if exc.cleanup_confirmed:
            _mark_cleanup(engine, claimed)
        if exc.code != "cancelled":
            _fail(
                engine,
                claimed,
                exc.code,
                cleanup_confirmed=exc.cleanup_confirmed,
            )
        return True
    except Exception:
        logger.warning("PDF export %s failed; content suppressed", claimed.id)
        cleanup_confirmed = adapter.prove_stopped(claimed.id, claimed.lease_id)
        if cleanup_confirmed:
            _mark_cleanup(engine, claimed)
        _fail(
            engine,
            claimed,
            "export_failed",
            cleanup_confirmed=cleanup_confirmed,
        )
        return True


def reap_pdf_sandboxes(
    engine: Engine, renderer: PdfRenderer | None = None, *, limit: int = 20
) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Cleanup limit must be between 1 and 100")
    adapter = renderer or DockerWeasyPrintRenderer()
    with Session(engine) as db:
        rows = list(
            db.execute(
                select(PdfExport.id, PdfExport.container_lease_id)
                .where(
                    PdfExport.state.in_(["failed", "cancelled"]),
                    PdfExport.cleanup_confirmed_at.is_(None),
                    PdfExport.container_lease_id.is_not(None),
                )
                .order_by(PdfExport.updated_at, PdfExport.id)
                .limit(limit)
            ).all()
        )
    cleaned = 0
    for export_id, lease_id in rows:
        assert lease_id is not None
        if not adapter.prove_stopped(export_id, lease_id):
            continue
        with Session(engine) as db, db.begin():
            export = db.scalar(select(PdfExport).where(PdfExport.id == export_id).with_for_update())
            if export and export.mark_cleanup_confirmed(lease_id):
                cleaned += 1
    return cleaned
