"""Owner-scoped settings, inspectable suggestions and separate human metadata review."""

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.api import schemas as s
from command_center.api.workspace import Database, Limit, Offset, WriteKey, write
from command_center.core.config import Settings
from command_center.core.identity import CurrentIdentity, Identity, require_workspace_tool
from command_center.db.artifacts import ArtifactVersion, Document
from command_center.db.crm import CandidateProfile
from command_center.db.document_decisions import (
    DEFAULT_TEMPLATE,
    DocumentClassificationReview,
    DocumentDecision,
    DocumentPolicy,
    DocumentRename,
    catalog_for,
    current_document,
    validate_analysis_context,
)
from command_center.db.models import Actor
from command_center.integrations.jev_documents import MAX_TEXT, digest, provider_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["document decisions"])


class DocumentPolicyRead(s.ResponseContract):
    revision: int
    classification_mode: Literal["off", "after_extraction"]
    catalog_ids: list[UUID]
    rename_mode: Literal["off", "task"]
    rename_template: str
    timezone: str
    provider: str
    provider_ready: bool


class DocumentPolicyUpdate(s.Contract):
    expected_version: int = Field(ge=0)
    classification_mode: Literal["off", "after_extraction"]
    catalog_ids: list[UUID] = Field(min_length=1, max_length=100)
    rename_mode: Literal["off", "task"]
    rename_template: str = Field(min_length=1, max_length=250)
    timezone: str = Field(min_length=1, max_length=100)
    external_processing_ack: bool = False


class DocumentDecisionRead(s.ResponseContract):
    id: UUID
    artifact_id: UUID
    task_id: UUID
    source_version_id: UUID
    extraction_version_id: UUID
    metadata_revision: int
    state: Literal[
        "queued", "running", "proposed", "needs_review", "unavailable", "cancelled", "superseded"
    ]
    proposed_type_id: UUID | None
    reason_codes: list[str]
    provider: str
    requested_model: str
    returned_model: str | None
    resolved_model: str | None
    question_version: str
    policy_version: str
    catalog_snapshot: list[dict[str, str]]
    state_hash: str
    question_hash: str
    input_manifest: dict[str, Any]
    questions: dict[str, Any]
    answers: dict[str, Any] | None
    usage: dict[str, Any] | None
    cost_status: Literal["not_started", "reserved", "settled", "unknown"]
    provenance: Literal["live", "mocked", "simulation", "recorded_fixture"] | None
    latency_ms: int | None
    error: str | None
    created_at: datetime
    excerpt: str = ""


class DocumentRenameRead(s.ResponseContract):
    id: UUID
    artifact_id: UUID
    review_id: UUID
    policy_revision: int
    metadata_revision: int
    task_id: UUID
    before_title: str
    after_title: str | None
    template: str
    render_inputs: dict[str, str]
    state: Literal["pending", "needs_correction", "applied", "cancelled", "superseded"]
    error: str | None
    row_version: int
    created_at: datetime


class DocumentClassificationRead(s.ResponseContract):
    artifact_id: UUID
    accepted_type_id: UUID
    metadata_revision: int
    source_version_id: UUID | None
    extraction_version_id: UUID | None
    policy: DocumentPolicyRead
    latest_decision: DocumentDecisionRead | None
    pending_rename: DocumentRenameRead | None


class DocumentClassificationReviewRead(s.ResponseContract):
    id: UUID
    artifact_id: UUID
    decision_id: UUID | None
    reviewer_id: UUID
    source_version_id: UUID
    extraction_version_id: UUID
    metadata_revision: int
    outcome: Literal["accept", "retain", "request_better_file"]
    accepted_type_id: UUID
    reason: str
    created_at: datetime


class DocumentAnalysisContext(s.Contract):
    model_config = ConfigDict(str_strip_whitespace=False)
    research_query: str | None = Field(default=None, min_length=1, max_length=4000)
    claim: str | None = Field(default=None, min_length=1, max_length=4000)
    agent_request: str | None = Field(default=None, min_length=1, max_length=4000)
    policy: str | None = Field(default=None, min_length=1, max_length=4000)
    proposed_action: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def bounded_context(self) -> "DocumentAnalysisContext":
        validate_analysis_context(self.model_dump(exclude_none=True))
        return self


class DocumentClassificationRequest(s.Contract):
    expected_version: int = Field(ge=1)
    source_version_id: UUID
    extraction_version_id: UUID
    external_processing_ack: bool
    analysis_context: DocumentAnalysisContext | None = None


class DocumentClassificationReviewCreate(s.Contract):
    expected_version: int = Field(ge=1)
    source_version_id: UUID
    extraction_version_id: UUID
    decision_id: UUID | None = None
    outcome: Literal["accept", "retain", "request_better_file"]
    document_type_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)


def human(identity: Identity) -> None:
    if not identity.is_human:
        raise HTTPException(403, "A human owner must review document metadata")


def policy_data(db: Session, owner_id: UUID, settings: Settings) -> dict[str, Any]:
    row = db.get(DocumentPolicy, owner_id)
    profile = db.get(CandidateProfile, owner_id)
    return {
        "revision": row.revision if row else 0,
        "classification_mode": row.classification_mode if row else "off",
        "catalog_ids": row.catalog_ids if row else [item["id"] for item in catalog_for(db, None)],
        "rename_mode": row.rename_mode if row else "off",
        "rename_template": row.rename_template if row else DEFAULT_TEMPLATE,
        "timezone": row.timezone if row else profile.timezone if profile else "UTC",
        "provider": settings.jev_provider,
        "provider_ready": bool(provider_key(settings)),
    }


def decision_data(db: Session, row: DocumentDecision) -> dict[str, Any]:
    data = DocumentDecisionRead.model_validate(row).model_dump(mode="json")
    version = db.get(ArtifactVersion, row.extraction_version_id)
    data["excerpt"] = str((version.payload or {}).get("text", ""))[:MAX_TEXT] if version else ""
    return data


def classification_data(
    db: Session, artifact_id: UUID, owner_id: UUID, settings: Settings
) -> dict[str, Any]:
    artifact, imported = current_document(db, artifact_id, owner_id)
    facet = db.get(Document, artifact.id)
    assert facet is not None
    latest = db.scalar(
        select(DocumentDecision)
        .where(DocumentDecision.artifact_id == artifact.id, DocumentDecision.owner_id == owner_id)
        .order_by(DocumentDecision.created_at.desc(), DocumentDecision.id.desc())
        .limit(1)
    )
    rename = db.scalar(
        select(DocumentRename)
        .where(
            DocumentRename.artifact_id == artifact.id,
            DocumentRename.owner_id == owner_id,
            DocumentRename.state.in_(["pending", "needs_correction"]),
        )
        .order_by(DocumentRename.created_at.desc())
        .limit(1)
    )
    latest_data = decision_data(db, latest) if latest else None
    if (
        latest
        and latest_data
        and latest.state in {"queued", "proposed", "needs_review"}
        and (
            artifact.archived_at
            or artifact.row_version != latest.metadata_revision
            or imported is None
            or imported.source_version_id != latest.source_version_id
            or imported.extraction_version_id != latest.extraction_version_id
            or digest(catalog_for(db, db.get(DocumentPolicy, owner_id))) != latest.catalog_hash
        )
    ):
        latest_data["state"] = "superseded"
        latest_data["error"] = "source_metadata_or_catalog_changed"
    rename_data = (
        DocumentRenameRead.model_validate(rename).model_dump(mode="json") if rename else None
    )
    if (
        rename
        and rename_data
        and (artifact.archived_at or artifact.row_version != rename.metadata_revision)
    ):
        rename_data["state"] = "superseded"
        rename_data["error"] = "document_metadata_changed"
    return {
        "artifact_id": str(artifact.id),
        "accepted_type_id": str(facet.document_type_id),
        "metadata_revision": artifact.row_version,
        "source_version_id": str(imported.source_version_id) if imported else None,
        "extraction_version_id": str(imported.extraction_version_id)
        if imported and imported.extraction_version_id
        else None,
        "policy": policy_data(db, owner_id, settings),
        "latest_decision": latest_data,
        "pending_rename": rename_data,
    }


@router.get("/documents/policy", response_model=DocumentPolicyRead)
def get_document_policy(
    identity: CurrentIdentity, db: Database, request: Request
) -> dict[str, Any]:
    require_workspace_tool(identity, "artifact_read")
    return policy_data(db, identity.id, request.app.state.settings)


@router.put("/documents/policy", response_model=DocumentPolicyRead)
def update_document_policy(
    body: DocumentPolicyUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human(identity)

    def change(_: UUID) -> dict[str, Any]:
        DocumentPolicy.configure(
            db, owner_id=identity.id, request_id=UUID(request.state.request_id), **body.model_dump()
        )
        return policy_data(db, identity.id, request.app.state.settings)

    return write(db, identity.id, key, "PUT:document-policy", body, change)


@router.get("/documents/{artifact_id}/classification", response_model=DocumentClassificationRead)
def get_classification(
    artifact_id: UUID, identity: CurrentIdentity, db: Database, request: Request
) -> dict[str, Any]:
    require_workspace_tool(identity, "artifact_read")
    return classification_data(db, artifact_id, identity.id, request.app.state.settings)


@router.get("/documents/decisions/{decision_id}", response_model=DocumentDecisionRead)
def inspect_decision(decision_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    require_workspace_tool(identity, "artifact_read")
    row = db.scalar(
        select(DocumentDecision).where(
            DocumentDecision.id == decision_id, DocumentDecision.owner_id == identity.id
        )
    )
    if row is None:
        raise HTTPException(404, "Document assessment not found")
    return decision_data(db, row)


@router.get(
    "/documents/{artifact_id}/classification/history", response_model=s.Page[DocumentDecisionRead]
)
def decision_history(
    artifact_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 20,
    offset: Offset = 0,
) -> dict[str, Any]:
    require_workspace_tool(identity, "artifact_read")
    artifact, _ = current_document(db, artifact_id, identity.id)
    statement = select(DocumentDecision).where(
        DocumentDecision.artifact_id == artifact.id, DocumentDecision.owner_id == identity.id
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(DocumentDecision.created_at.desc(), DocumentDecision.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [decision_data(db, row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/documents/{artifact_id}/classification/reviews",
    response_model=s.Page[DocumentClassificationReviewRead],
)
def review_history(
    artifact_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 20,
    offset: Offset = 0,
) -> dict[str, Any]:
    require_workspace_tool(identity, "artifact_read")
    artifact, _ = current_document(db, artifact_id, identity.id)
    statement = select(DocumentClassificationReview).where(
        DocumentClassificationReview.artifact_id == artifact.id,
        DocumentClassificationReview.owner_id == identity.id,
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(
            DocumentClassificationReview.created_at.desc(), DocumentClassificationReview.id
        )
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [
            DocumentClassificationReviewRead.model_validate(row).model_dump(mode="json")
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/documents/{artifact_id}/classification", response_model=DocumentDecisionRead, status_code=202
)
def request_classification(
    artifact_id: UUID,
    body: DocumentClassificationRequest,
    identity: CurrentIdentity,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    require_workspace_tool(identity, "artifact_read")
    if not body.external_processing_ack:
        raise HTTPException(
            422, "Acknowledge sending this document's extracted text to the configured provider"
        )
    settings = request.app.state.settings
    if not provider_key(settings):
        raise HTTPException(409, "Configure the Jev provider before requesting classification")
    with Session(request.app.state.engine) as db, db.begin():

        def change(decision_id: UUID) -> dict[str, Any]:
            row = DocumentDecision.request(
                db,
                decision_id=decision_id,
                owner_id=identity.id,
                artifact_id=artifact_id,
                metadata_revision=body.expected_version,
                source_version_id=body.source_version_id,
                extraction_version_id=body.extraction_version_id,
                provider=settings.jev_provider,
                request_id=UUID(request.state.request_id),
                analysis_context=body.analysis_context.model_dump(exclude_none=True)
                if body.analysis_context
                else None,
            )
            return decision_data(db, row)

        receipt = write(
            db, identity.id, key, f"POST:document-classification:{artifact_id}", body, change
        )
        row = db.get(DocumentDecision, UUID(str(receipt["id"])))
        assert row is not None
        result = decision_data(db, row)
    if result["state"] == "queued":
        try:
            from command_center.agents.queue import execute_document_decision

            execute_document_decision.apply_async(
                args=(result["id"],), task_id=f"document-decision:{result['id']}", expires=60
            )
        except Exception:
            logger.warning(
                "Document classification %s remains queued for durable dispatch", result["id"]
            )
    return result


@router.post(
    "/documents/{artifact_id}/classification/review", response_model=DocumentClassificationRead
)
def review_classification(
    artifact_id: UUID,
    body: DocumentClassificationReviewCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    human(identity)

    def change(review_id: UUID) -> dict[str, Any]:
        DocumentClassificationReview.record(
            db,
            review_id=review_id,
            owner_id=identity.id,
            artifact_id=artifact_id,
            metadata_revision=body.expected_version,
            source_version_id=body.source_version_id,
            extraction_version_id=body.extraction_version_id,
            decision_id=body.decision_id,
            outcome=body.outcome,
            document_type_id=body.document_type_id,
            reason=body.reason,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return classification_data(db, artifact_id, identity.id, request.app.state.settings)

    return write(
        db, identity.id, key, f"POST:document-classification-review:{artifact_id}", body, change
    )


def change_rename(
    action: str,
    rename_id: UUID,
    body: s.Revision,
    identity: Identity,
    db: Session,
    key: UUID,
    request: Request,
) -> dict[str, Any]:
    human(identity)

    def change(_: UUID) -> dict[str, Any]:
        db.scalar(select(Actor).where(Actor.id == identity.id).with_for_update())
        row = db.scalar(
            select(DocumentRename)
            .where(DocumentRename.id == rename_id, DocumentRename.owner_id == identity.id)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(404, "Rename proposal not found")
        if action == "apply":
            row.apply(
                owner_id=identity.id,
                expected_version=body.expected_version,
                request_id=UUID(request.state.request_id),
            )
        else:
            if row.row_version != body.expected_version or row.state not in {
                "pending",
                "needs_correction",
            }:
                raise HTTPException(409, "The rename proposal changed; refresh before cancelling")
            row.close("cancelled", request_id=UUID(request.state.request_id))
        db.flush()
        return DocumentRenameRead.model_validate(row).model_dump(mode="json")

    return write(db, identity.id, key, f"POST:document-rename:{rename_id}:{action}", body, change)


@router.post("/documents/renames/{rename_id}/apply", response_model=DocumentRenameRead)
def apply_rename(
    rename_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return change_rename("apply", rename_id, body, identity, db, key, request)


@router.post("/documents/renames/{rename_id}/cancel", response_model=DocumentRenameRead)
def cancel_rename(
    rename_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return change_rename("cancel", rename_id, body, identity, db, key, request)
