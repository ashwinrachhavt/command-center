"""One durable document inference, with short SQL leases around provider I/O."""

import asyncio
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.db.artifacts import ArtifactVersion
from command_center.db.base import utc_now
from command_center.db.crm import record_event
from command_center.db.document_decisions import (
    DocumentDecision,
    DocumentPolicy,
    catalog_for,
    fence_document,
)
from command_center.db.document_imports import DocumentImport
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor
from command_center.db.spending import SpendingDenied, SpendingReservation
from command_center.integrations.jev import JevProvider
from command_center.integrations.jev_documents import (
    DocumentResult,
    classify_document,
    digest,
    document_payload,
    provider_key,
)


@dataclass(frozen=True)
class ClaimedDecision:
    id: UUID
    lease_id: UUID
    reservation_id: UUID
    provider: JevProvider
    payload: dict[str, Any]


def claim(engine: Engine, settings: Settings, decision_id: UUID) -> ClaimedDecision | None:
    with Session(engine) as db, db.begin():
        owner_id = db.scalar(
            select(DocumentDecision.owner_id).where(DocumentDecision.id == decision_id)
        )
        if owner_id is None:
            return None
        db.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
        row = db.scalar(
            select(DocumentDecision)
            .where(DocumentDecision.id == decision_id, DocumentDecision.state == "queued")
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        if row.provider != settings.jev_provider or not provider_key(settings):
            row.finish("unavailable", error="provider_unconfigured_or_changed")
            return None
        policy = db.get(DocumentPolicy, row.owner_id)
        if row.trigger == "automatic" and (
            policy is None or policy.classification_mode != "after_extraction"
        ):
            row.finish("cancelled", error="automatic_classification_disabled")
            return None
        try:
            fence_document(
                db,
                row.artifact_id,
                row.owner_id,
                row.metadata_revision,
                row.source_version_id,
                row.extraction_version_id,
            )
            if digest(catalog_for(db, policy)) != row.catalog_hash:
                raise RecordConflict("Catalog changed")
        except RecordConflict:
            row.finish("superseded", error="source_metadata_or_catalog_changed")
            return None
        extraction = db.get(ArtifactVersion, row.extraction_version_id)
        imported = db.get(DocumentImport, row.import_id)
        assert extraction is not None and imported is not None
        provider = settings.jev_provider
        try:
            payload = document_payload(
                str((extraction.payload or {}).get("text", "")),
                imported.filename,
                row.catalog_snapshot,
                provider,
                analysis_context=row.input_manifest.get("analysis_context", {}),
            )
        except ValueError:
            row.finish("superseded", error="decision_input_changed")
            return None
        if (
            digest(payload["state"]) != row.state_hash
            or digest(payload["questions"]) != row.question_hash
        ):
            row.finish("superseded", error="decision_input_changed")
            return None
        row.state = "running"
        row.lease_id = uuid4()
        row.lease_expires_at = utc_now() + timedelta(minutes=2)
        db.flush()
        try:
            reservation = SpendingReservation.reserve_document_model(
                db,
                decision_id=row.id,
                lease_id=row.lease_id,
                input_token_bound=64_000,
                output_token_bound=4096,
            )
        except SpendingDenied as exc:
            row.finish("unavailable", error=exc.code)
            return None
        row.cost_status = "reserved"
        return ClaimedDecision(row.id, row.lease_id, reservation.id, provider, payload)


def persist(
    engine: Engine,
    claimed: ClaimedDecision,
    result: DocumentResult | None,
    *,
    latency_ms: int,
    provenance: str,
) -> None:
    with Session(engine) as db, db.begin():
        owner_id = db.scalar(
            select(DocumentDecision.owner_id).where(DocumentDecision.id == claimed.id)
        )
        if owner_id is None:
            return
        db.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
        row = db.scalar(
            select(DocumentDecision).where(DocumentDecision.id == claimed.id).with_for_update()
        )
        if row is None:
            return
        if not row.accepts(claimed.lease_id):
            # An expired/lost lease never publishes output or silently retries.
            SpendingReservation.mark_unknown(
                db,
                reservation_id=claimed.reservation_id,
                lease_id=claimed.lease_id,
                reason="document_outcome_unknown",
            )
            if row.state == "running" and row.lease_id == claimed.lease_id:
                row.cost_status = "unknown"
                row.finish("unavailable", error="outcome_unknown_explicit_retry_required")
            return
        if result is None:
            SpendingReservation.mark_unknown(
                db,
                reservation_id=claimed.reservation_id,
                lease_id=claimed.lease_id,
                reason="document_provider_unavailable",
            )
            row.cost_status = "unknown"
            row.finish("unavailable", error="provider_unavailable_explicit_retry_required")
        else:
            result.validate_request(claimed.payload, claimed.provider)
            # Owner -> document -> spending is the same order as claim/review.
            # Even a stale input's successful inference still settles known cost.
            stale = False
            try:
                fence_document(
                    db,
                    row.artifact_id,
                    row.owner_id,
                    row.metadata_revision,
                    row.source_version_id,
                    row.extraction_version_id,
                )
                if (
                    digest(catalog_for(db, db.get(DocumentPolicy, row.owner_id)))
                    != row.catalog_hash
                ):
                    raise RecordConflict("Catalog changed")
            except RecordConflict:
                stale = True
            SpendingReservation.settle_model(
                db,
                reservation_id=claimed.reservation_id,
                lease_id=claimed.lease_id,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            )
            row.cost_status = "settled"
            row.complete(result, latency_ms=latency_ms, provenance=provenance)
            if stale:
                row.finish("superseded", error="source_metadata_or_catalog_changed")
        record_event(
            db,
            row.owner_id,
            uuid4(),
            "documents.classification_finished",
            "document_decisions",
            row.id,
            state=row.state,
            reason_codes=row.reason_codes,
            cost_status=row.cost_status,
        )


async def infer(settings: Settings, claimed: ClaimedDecision) -> DocumentResult:
    async with httpx.AsyncClient() as http:
        return await classify_document(
            http, provider_key(settings), claimed.payload, claimed.provider
        )


def perform_document_decision(
    engine: Engine, settings: Settings, decision_id: UUID | str, *, provenance: str = "live"
) -> bool:
    claimed = claim(engine, settings, UUID(str(decision_id)))
    if claimed is None:
        return False
    started = time.monotonic()
    try:
        result = asyncio.run(infer(settings, claimed))
    except Exception:
        # Provider response bodies and extracted text never enter logs or errors.
        result = None
    persist(
        engine,
        claimed,
        result,
        latency_ms=int((time.monotonic() - started) * 1000),
        provenance=provenance,
    )
    return True
