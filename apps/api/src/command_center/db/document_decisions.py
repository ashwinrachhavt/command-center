"""Human-reviewed type metadata and display-title proposals for exact document inputs."""

from datetime import datetime
from string import Formatter
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import Artifact, ArtifactVersion, Document, DocumentType
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.document_imports import DocumentImport
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.models import Actor, Task
from command_center.integrations.jev import JEV_MODELS, JevProvider
from command_center.integrations.jev_documents import (
    MAX_TEXT,
    POLICY_VERSION,
    QUESTION_VERSION,
    DocumentResult,
    application_reasons,
    digest,
    document_payload,
)

DEFAULT_TEMPLATE = "{type} - {uploaded_date} - {short_id}"
ANALYSIS_CONTEXT_KEYS = {"research_query", "claim", "agent_request", "policy", "proposed_action"}


def validate_analysis_context(context: dict[str, str] | None) -> dict[str, str]:
    """Caller-supplied criteria stay bounded private data, never executable instructions."""
    if context is None:
        return {}
    if not isinstance(context, dict) or set(context) - ANALYSIS_CONTEXT_KEYS:
        raise ValueError("Choose supported document analysis context fields")
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > 4000
        for value in context.values()
    ):
        raise ValueError("Each analysis context field must contain 1 to 4,000 characters")
    if sum(len(value) for value in context.values()) > 12_000:
        raise ValueError("Document analysis context is limited to 12,000 characters total")
    if any(
        "\x00" in value or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
        for value in context.values()
    ):
        raise ValueError("Analysis context must contain valid text without null characters")
    return dict(context)


def catalog_for(session: Session, policy: "DocumentPolicy | None") -> list[dict[str, str]]:
    statement = select(DocumentType).where(DocumentType.slug != "unclassified")
    if policy is not None:
        statement = statement.where(
            DocumentType.id.in_([UUID(item) for item in policy.catalog_ids])
        )
    rows = session.scalars(statement.order_by(DocumentType.id)).all()
    return [
        {
            "id": str(row.id),
            "slug": row.slug,
            "name": row.name,
            "description": row.description or "",
        }
        for row in rows
        if row.description and row.description.strip()
    ]


def validate_template(template: str) -> None:
    if (
        not template.strip()
        or len(template) > 250
        or any(not character.isprintable() or character in "/\\" for character in template)
    ):
        raise ValueError("Use a display title template without paths or control characters")
    try:
        parts = list(Formatter().parse(template))
    except ValueError:
        raise ValueError("The display title template has invalid braces") from None
    for _, field, spec, conversion in parts:
        if field is not None and (
            field not in {"type", "uploaded_date", "short_id"} or spec or conversion
        ):
            raise ValueError("Only {type}, {uploaded_date} and {short_id} are allowed")


def current_document(
    session: Session, artifact_id: UUID, owner_id: UUID, *, lock: bool = False
) -> tuple[Artifact, DocumentImport | None]:
    # Canvas links to either member of the original/extraction pair.
    source = session.scalar(
        select(DocumentImport.artifact_id).where(
            DocumentImport.extraction_artifact_id == artifact_id,
            DocumentImport.owner_id == owner_id,
        )
    )
    statement = select(Artifact).where(
        Artifact.id == (source or artifact_id), Artifact.owner_id == owner_id
    )
    if lock:
        statement = statement.with_for_update()
    artifact = session.scalar(statement)
    if artifact is None or session.get(Document, artifact.id) is None:
        raise RecordNotFound("Document not found")
    latest = session.scalar(
        select(ArtifactVersion.id)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    )
    job = session.scalar(select(DocumentImport).where(DocumentImport.source_version_id == latest))
    return artifact, job


def fence_document(
    session: Session,
    artifact_id: UUID,
    owner_id: UUID,
    metadata_revision: int,
    source_version_id: UUID,
    extraction_version_id: UUID,
) -> tuple[Artifact, DocumentImport]:
    artifact, imported = current_document(session, artifact_id, owner_id, lock=True)
    if artifact.archived_at or artifact.row_version != metadata_revision:
        raise RecordConflict("Document metadata changed or was archived; refresh before reviewing")
    if (
        imported is None
        or imported.state != "completed"
        or imported.source_version_id != source_version_id
        or imported.extraction_version_id != extraction_version_id
    ):
        raise RecordConflict("The original or extraction changed; review the current document")
    extraction = session.scalar(
        select(Artifact).where(Artifact.id == imported.extraction_artifact_id).with_for_update()
    )
    latest_extraction = session.scalar(
        select(ArtifactVersion.id)
        .where(ArtifactVersion.artifact_id == imported.extraction_artifact_id)
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    )
    if (
        extraction is None
        or extraction.owner_id != owner_id
        or extraction.archived_at
        or latest_extraction != extraction_version_id
    ):
        raise RecordConflict("The current extraction is unavailable or changed")
    return artifact, imported


class DocumentPolicy(Base):
    __tablename__ = "document_policies"
    __table_args__ = (
        CheckConstraint(
            "classification_mode IN ('off', 'after_extraction')", name="classification_mode"
        ),
        CheckConstraint("rename_mode IN ('off', 'task')", name="rename_mode"),
        CheckConstraint("revision >= 1", name="revision"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    classification_mode: Mapped[str] = mapped_column(String(30), default="off")
    catalog_ids: Mapped[list[str]] = mapped_column(JSONB)
    rename_mode: Mapped[str] = mapped_column(String(20), default="off")
    rename_template: Mapped[str] = mapped_column(String(250), default=DEFAULT_TEMPLATE)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    @classmethod
    def configure(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        expected_version: int,
        classification_mode: str,
        catalog_ids: list[UUID],
        rename_mode: str,
        rename_template: str,
        timezone: str,
        external_processing_ack: bool,
        request_id: UUID,
    ) -> "DocumentPolicy":
        session.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
        policy = session.get(cls, owner_id)
        if (policy.revision if policy else 0) != expected_version:
            raise RecordConflict("Document settings changed; refresh before saving")
        if classification_mode not in {"off", "after_extraction"} or rename_mode not in {
            "off",
            "task",
        }:
            raise ValueError("Choose a supported document setting")
        if classification_mode == "after_extraction" and not external_processing_ack:
            raise ValueError("Acknowledge external processing of extracted text")
        if not catalog_ids or len(catalog_ids) > 100 or len(set(catalog_ids)) != len(catalog_ids):
            raise ValueError("Choose between 1 and 100 distinct document types")
        allowed = {item["id"] for item in catalog_for(session, None)}
        if not {str(item) for item in catalog_ids}.issubset(allowed):
            raise ValueError("Choose catalog types with nonempty descriptions")
        validate_template(rename_template)
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid timezone for upload dates") from None
        if policy is None:
            policy = cls(owner_id=owner_id, revision=1)
            session.add(policy)
        else:
            policy.revision += 1
        policy.classification_mode = classification_mode
        policy.catalog_ids = sorted(str(item) for item in catalog_ids)
        policy.rename_mode = rename_mode
        policy.rename_template = rename_template
        policy.timezone = timezone
        for rename in session.scalars(
            select(DocumentRename)
            .where(
                DocumentRename.owner_id == owner_id,
                DocumentRename.state.in_(["pending", "needs_correction"]),
            )
            .with_for_update()
        ):
            rename.close("superseded", request_id=request_id)
        record_event(
            session,
            owner_id,
            request_id,
            "documents.policy_updated",
            "document_policies",
            owner_id,
            revision=policy.revision,
            classification_mode=classification_mode,
            rename_mode=rename_mode,
        )
        session.flush()
        return policy


class DocumentDecision(Base):
    __tablename__ = "document_decisions"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        UniqueConstraint("owner_id", "fingerprint", "attempt"),
        CheckConstraint(
            "state IN ('queued', 'running', 'proposed', 'needs_review', 'unavailable', "
            "'cancelled', 'superseded')",
            name="state",
        ),
        CheckConstraint(
            "(state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="lease",
        ),
        CheckConstraint(
            "cost_status IN ('not_started', 'reserved', 'settled', 'unknown')", name="cost_status"
        ),
        CheckConstraint("attempt >= 1", name="attempt"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    import_id: Mapped[UUID] = mapped_column(ForeignKey("document_imports.id"))
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"))
    source_version_id: Mapped[UUID] = mapped_column(ForeignKey("artifact_versions.id"))
    extraction_version_id: Mapped[UUID] = mapped_column(ForeignKey("artifact_versions.id"))
    metadata_revision: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    proposed_type_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_types.id"))
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    provider: Mapped[str] = mapped_column(String(30))
    requested_model: Mapped[str] = mapped_column(String(100))
    returned_model: Mapped[str | None] = mapped_column(String(100))
    resolved_model: Mapped[str | None] = mapped_column(String(100))
    question_version: Mapped[str] = mapped_column(String(100), default=QUESTION_VERSION)
    policy_version: Mapped[str] = mapped_column(String(100), default=POLICY_VERSION)
    catalog_snapshot: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    catalog_hash: Mapped[str] = mapped_column(String(64))
    state_hash: Mapped[str] = mapped_column(String(64))
    question_hash: Mapped[str] = mapped_column(String(64))
    input_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    questions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cost_status: Mapped[str] = mapped_column(String(20), default="not_started")
    provenance: Mapped[str | None] = mapped_column(String(30))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @classmethod
    def request(
        cls,
        session: Session,
        *,
        decision_id: UUID,
        owner_id: UUID,
        artifact_id: UUID,
        metadata_revision: int,
        source_version_id: UUID,
        extraction_version_id: UUID,
        provider: JevProvider,
        request_id: UUID,
        automatic: bool = False,
        analysis_context: dict[str, str] | None = None,
    ) -> "DocumentDecision":
        session.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
        artifact, imported = fence_document(
            session,
            artifact_id,
            owner_id,
            metadata_revision,
            source_version_id,
            extraction_version_id,
        )
        policy = session.get(DocumentPolicy, owner_id)
        if automatic and (policy is None or policy.classification_mode != "after_extraction"):
            raise ValueError("Automatic document classification is off")
        catalog = catalog_for(session, policy)
        extracted = session.get(ArtifactVersion, extraction_version_id)
        text = str((extracted.payload or {}).get("text", "")) if extracted else ""
        context = validate_analysis_context(analysis_context)
        if automatic and context:
            raise ValueError("Automatic classification does not supply research or agent context")
        payload = document_payload(
            text, imported.filename, catalog, provider, analysis_context=context
        )
        fingerprint = digest(
            {
                "source": str(source_version_id),
                "extraction": str(extraction_version_id),
                "revision": metadata_revision,
                "state": payload["state"],
                "questions": payload["questions"],
                "catalog": catalog,
                "provider": provider,
                "model": payload["model"],
                "question_version": QUESTION_VERSION,
                "policy_version": POLICY_VERSION,
                "analysis_context": context,
            }
        )
        prior = session.scalar(
            select(cls)
            .where(cls.owner_id == owner_id, cls.fingerprint == fingerprint)
            .order_by(cls.attempt.desc())
            .limit(1)
        )
        if prior:
            reusable = prior.state in {"queued", "running"} or (
                prior.state in {"proposed", "needs_review"} and prior.resolved_model is not None
            )
            if automatic or reusable:
                return prior
        row = cls(
            id=decision_id,
            owner_id=owner_id,
            artifact_id=artifact.id,
            import_id=imported.id,
            task_id=imported.task_id,
            source_version_id=source_version_id,
            extraction_version_id=extraction_version_id,
            metadata_revision=metadata_revision,
            fingerprint=fingerprint,
            attempt=prior.attempt + 1 if prior else 1,
            trigger="automatic" if automatic else "manual",
            provider=provider,
            requested_model=JEV_MODELS[provider],
            catalog_snapshot=catalog,
            catalog_hash=digest(catalog),
            state_hash=digest(payload["state"]),
            question_hash=digest(payload["questions"]),
            questions=payload["questions"],
            input_manifest={
                "analysis_context": context,
                "source_version_id": str(source_version_id),
                "extraction_version_id": str(extraction_version_id),
                "extraction_sha256": extracted.content_sha256 if extracted else "",
                "character_ranges": [[0, min(len(text), MAX_TEXT)]],
                "total_characters": len(text),
                "truncated": len(text) > MAX_TEXT,
                "omitted_characters": max(0, len(text) - MAX_TEXT),
            },
        )
        session.add(row)
        session.flush()
        record_event(
            session,
            owner_id,
            request_id,
            "documents.classification_requested",
            "document_decisions",
            row.id,
            artifact_id=str(artifact.id),
            source_version_id=str(source_version_id),
            extraction_version_id=str(extraction_version_id),
            trigger=row.trigger,
        )
        return row

    def accepts(self, lease_id: UUID) -> bool:
        return bool(
            self.state == "running"
            and self.lease_id == lease_id
            and self.lease_expires_at
            and self.lease_expires_at > utc_now()
        )

    def finish(self, state: str, *, error: str | None = None) -> None:
        self.state = state
        self.error = error
        self.lease_id = None
        self.lease_expires_at = None
        self.completed_at = utc_now()

    def complete(self, result: DocumentResult, *, latency_ms: int, provenance: str) -> None:
        self.returned_model = result.model
        self.resolved_model = result.resolved_model
        self.answers = result.answers.model_dump(mode="json", exclude_none=True)
        self.usage = result.usage.model_dump()
        self.latency_ms = latency_ms
        self.provenance = provenance
        self.reason_codes = application_reasons(
            result, truncated=bool(self.input_manifest["truncated"])
        )
        choice = result.answers.document_type.choice
        self.proposed_type_id = UUID(choice) if choice not in {"unknown", "mixed"} else None
        self.finish(
            "proposed" if self.reason_codes == ["human_review_required"] else "needs_review"
        )

    @classmethod
    def expire_stale(cls, session: Session) -> int:
        from command_center.db.spending import SpendingReservation

        rows = session.scalars(
            select(cls)
            .where(cls.state == "running", cls.lease_expires_at <= utc_now())
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            reservation = session.scalar(
                select(SpendingReservation).where(
                    SpendingReservation.document_decision_id == row.id
                )
            )
            if reservation:
                SpendingReservation.mark_unknown(
                    session,
                    reservation_id=reservation.id,
                    lease_id=row.lease_id,
                    reason="document_outcome_unknown",
                )
                row.cost_status = "unknown"
            row.finish("unavailable", error="outcome_unknown_explicit_retry_required")
        return len(rows)


class DocumentClassificationReview(Base):
    __tablename__ = "document_classification_reviews"
    __table_args__ = (
        CheckConstraint("outcome IN ('accept', 'retain', 'request_better_file')", name="outcome"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_decisions.id"))
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    source_version_id: Mapped[UUID] = mapped_column(ForeignKey("artifact_versions.id"))
    extraction_version_id: Mapped[UUID] = mapped_column(ForeignKey("artifact_versions.id"))
    metadata_revision: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(30))
    accepted_type_id: Mapped[UUID] = mapped_column(ForeignKey("document_types.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @classmethod
    def record(
        cls,
        session: Session,
        *,
        review_id: UUID,
        owner_id: UUID,
        artifact_id: UUID,
        metadata_revision: int,
        source_version_id: UUID,
        extraction_version_id: UUID,
        decision_id: UUID | None,
        outcome: str,
        document_type_id: UUID | None,
        reason: str,
        request_id: UUID,
    ) -> "DocumentClassificationReview":
        actor = session.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
        if actor is None or actor.kind != "human":
            raise ValueError("A human owner must review document types")
        artifact, imported = fence_document(
            session,
            artifact_id,
            owner_id,
            metadata_revision,
            source_version_id,
            extraction_version_id,
        )
        policy = session.get(DocumentPolicy, owner_id)
        catalog = catalog_for(session, policy)
        if outcome not in {"accept", "retain", "request_better_file"} or not reason.strip():
            raise ValueError("Choose a review outcome and explain the choice")
        if decision_id:
            decision = session.get(DocumentDecision, decision_id)
            if (
                decision is None
                or decision.owner_id != owner_id
                or decision.artifact_id != artifact.id
                or decision.state not in {"proposed", "needs_review"}
                or decision.source_version_id != source_version_id
                or decision.extraction_version_id != extraction_version_id
                or decision.metadata_revision != metadata_revision
                or decision.catalog_hash != digest(catalog)
            ):
                raise RecordConflict(
                    "The assessment is stale; request a fresh assessment or make a manual choice"
                )
        facet = session.get(Document, artifact.id)
        assert facet is not None
        selected = document_type_id if outcome == "accept" else facet.document_type_id
        unclassified = session.scalar(
            select(DocumentType.id).where(DocumentType.slug == "unclassified")
        )
        allowed = {UUID(item["id"]) for item in catalog} | (
            {unclassified} if unclassified else set()
        )
        if selected is None or (outcome == "accept" and selected not in allowed):
            raise ValueError("Choose a current catalog document type")
        review = cls(
            id=review_id,
            owner_id=owner_id,
            artifact_id=artifact.id,
            decision_id=decision_id,
            reviewer_id=owner_id,
            source_version_id=source_version_id,
            extraction_version_id=extraction_version_id,
            metadata_revision=metadata_revision,
            outcome=outcome,
            accepted_type_id=selected,
            reason=reason.strip(),
        )
        session.add(review)
        session.flush()
        if outcome == "accept":
            facet.correct_type(
                session,
                owner_id=owner_id,
                document_type_id=selected,
                metadata_revision=metadata_revision,
                source_version_id=source_version_id,
                extraction_version_id=extraction_version_id,
                review_id=review.id,
                request_id=request_id,
            )
            session.flush()
            DocumentRename.propose(
                session,
                review=review,
                artifact=artifact,
                imported=imported,
                policy=policy,
                request_id=request_id,
            )
        record_event(
            session,
            owner_id,
            request_id,
            "documents.classification_reviewed",
            "document_classification_reviews",
            review.id,
            artifact_id=str(artifact.id),
            decision_id=str(decision_id) if decision_id else None,
            outcome=outcome,
            accepted_type_id=str(selected),
            provenance="human",
        )
        return review


class DocumentRename(Base):
    __tablename__ = "document_renames"
    __table_args__ = (
        UniqueConstraint("artifact_id", "review_id", "policy_revision"),
        CheckConstraint(
            "state IN ('pending', 'needs_correction', 'applied', 'cancelled', 'superseded')",
            name="state",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    review_id: Mapped[UUID] = mapped_column(ForeignKey("document_classification_reviews.id"))
    policy_revision: Mapped[int] = mapped_column(Integer)
    metadata_revision: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), unique=True)
    before_title: Mapped[str] = mapped_column(String(300))
    after_title: Mapped[str | None] = mapped_column(String(300))
    template: Mapped[str] = mapped_column(String(250))
    render_inputs: Mapped[dict[str, str]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    error: Mapped[str | None] = mapped_column(String(100))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def propose(
        cls,
        session: Session,
        *,
        review: DocumentClassificationReview,
        artifact: Artifact,
        imported: DocumentImport,
        policy: DocumentPolicy | None,
        request_id: UUID,
    ) -> "DocumentRename | None":
        for pending in session.scalars(
            select(cls)
            .where(cls.artifact_id == artifact.id, cls.state.in_(["pending", "needs_correction"]))
            .with_for_update()
        ):
            pending.close("superseded", request_id=request_id)
        if policy is None or policy.rename_mode != "task":
            return None
        kind = session.get(DocumentType, review.accepted_type_id)
        assert kind is not None
        inputs = {
            "type": kind.name,
            "uploaded_date": imported.created_at.astimezone(ZoneInfo(policy.timezone))
            .date()
            .isoformat(),
            "short_id": artifact.id.hex[:8],
        }
        error = None
        try:
            validate_template(policy.rename_template)
            title = policy.rename_template.format_map(inputs).strip()
            if not title or len(title) > 300 or any(not char.isprintable() for char in title):
                raise ValueError("Invalid rendered title")
        except (KeyError, ValueError):
            title, error = None, "rename_template_needs_correction"
        if title == artifact.title:
            record_event(
                session,
                artifact.owner_id,
                request_id,
                "documents.rename_unchanged",
                "artifacts",
                artifact.id,
                review_id=str(review.id),
                policy_revision=policy.revision,
            )
            return None
        rename_id = uuid5(review.id, f"rename:{policy.revision}")
        task = artifact.create_task(
            task_id=uuid5(rename_id, "task"),
            request_id=request_id,
            title=f"Rename document: {artifact.title}"[:300],
            rationale=(
                "Review a Vault display title. The original filename and bytes are preserved."
            ),
        )
        row = cls(
            id=rename_id,
            owner_id=artifact.owner_id,
            artifact_id=artifact.id,
            review_id=review.id,
            policy_revision=policy.revision,
            metadata_revision=artifact.row_version,
            task_id=task.id,
            before_title=artifact.title,
            after_title=title,
            template=policy.rename_template,
            render_inputs=inputs,
            state="needs_correction" if error else "pending",
            error=error,
        )
        session.add(row)
        return row

    def close(self, state: str, *, request_id: UUID) -> None:
        session = object_session(self)
        assert session is not None
        self.state = state
        task = session.get(Task, self.task_id)
        if task and task.state not in {"done", "cancelled"}:
            task.revise({"state": "cancelled"}, request_id=request_id)
        record_event(
            session,
            self.owner_id,
            request_id,
            f"documents.rename_{state}",
            "document_renames",
            self.id,
        )

    def apply(self, *, owner_id: UUID, expected_version: int, request_id: UUID) -> None:
        session = object_session(self)
        assert session is not None
        session.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
        if self.owner_id != owner_id:
            raise RecordNotFound("Rename proposal not found")
        if (
            self.row_version != expected_version
            or self.state != "pending"
            or self.after_title is None
        ):
            raise RecordConflict("The rename proposal is no longer pending; refresh the document")
        review = session.get(DocumentClassificationReview, self.review_id)
        assert review is not None
        artifact, _ = fence_document(
            session,
            self.artifact_id,
            owner_id,
            self.metadata_revision,
            review.source_version_id,
            review.extraction_version_id,
        )
        policy = session.get(DocumentPolicy, owner_id)
        facet = session.get(Document, artifact.id)
        if (
            policy is None
            or policy.rename_mode != "task"
            or policy.revision != self.policy_revision
            or artifact.title != self.before_title
            or facet is None
            or facet.document_type_id != review.accepted_type_id
        ):
            raise RecordConflict(
                "The title, type or rename policy changed; review a fresh proposal"
            )
        task = session.get(Task, self.task_id)
        if task is None or task.owner_id != owner_id or task.state in {"done", "cancelled"}:
            raise RecordConflict("The rename task is no longer active")
        artifact.title = self.after_title
        artifact.updated_at = utc_now()
        self.state = "applied"
        task.complete(actor_id=owner_id, request_id=request_id)
        record_event(
            session,
            owner_id,
            request_id,
            "documents.title_renamed",
            "artifacts",
            artifact.id,
            rename_id=str(self.id),
            review_id=str(review.id),
            before_title=self.before_title,
            after_title=self.after_title,
            source_version_id=str(review.source_version_id),
            extraction_version_id=str(review.extraction_version_id),
        )
