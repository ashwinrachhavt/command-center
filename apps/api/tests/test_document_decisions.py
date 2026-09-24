"""Synthetic document decisions exercise exact human review and paid-job fences."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from command_center.api.document_decisions import DocumentAnalysisContext, classification_data
from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import Artifact, ArtifactVersion, Document, DocumentType
from command_center.db.base import utc_now
from command_center.db.crm import CandidateProfile
from command_center.db.document_decisions import (
    DEFAULT_TEMPLATE,
    DocumentClassificationReview,
    DocumentDecision,
    DocumentPolicy,
    DocumentRename,
    catalog_for,
    validate_template,
)
from command_center.db.document_imports import DocumentImport
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor, Task
from command_center.db.spending import SpendingReservation, ensure_default_spending_policy
from command_center.documents import decision_worker, worker
from command_center.integrations.jev_documents import DocumentResult, document_payload


def answer(payload, choice=None):
    keys = list(payload["questions"]["document_type"]["criteria"])
    choice = choice or keys[0]
    result = {
        "model": payload["model"],
        "answers": {
            "document_type": {
                "type": "choice",
                "choice": choice,
                "confidence": 0.94,
                "probabilities": {key: 1.0 if key == choice else 0.0 for key in keys},
            },
            "sufficient_evidence": {"type": "noul", "noul": 0.99},
            "incompatible_purposes": {"type": "noul", "noul": 0.01},
            "processing_instructions": {"type": "noul", "noul": 0.01},
            "explicit_commitment": {"type": "noul", "noul": 0.1},
            "follow_up_requested": {"type": "noul", "noul": 0.1},
            "deadline_present": {"type": "noul", "noul": 0.1},
        },
        "usage": {"input_tokens": 400, "output_tokens": 90},
    }
    for name, question in payload["questions"].items():
        if name in result["answers"]:
            continue
        if question["type"] == "noul":
            result["answers"][name] = {"type": "noul", "noul": 0.2}
        elif question["type"] == "choice":
            options = list(question["criteria"])
            result["answers"][name] = {
                "type": "choice",
                "choice": options[0],
                "confidence": 1.0,
                "probabilities": {
                    option: 1.0 if option == options[0] else 0.0 for option in options
                },
            }
        else:
            result["answers"][name] = {
                "type": "score",
                "score": 1.0,
                "confidence": 1.0,
                "legend": {
                    str(index): description
                    for index, description in enumerate(question["criteria"])
                },
                "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0},
            }
    return result


def configured(settings):
    return settings.model_copy(update={"jev_api_key": SecretStr("synthetic-provider-key")})


def seed_document(engine, *, automatic=False, rename=False, kind="unclassified"):
    owner, import_id = uuid4(), uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner, kind="human", display_name="Synthetic document reviewer"))
        db.flush()
        db.add(CandidateProfile(actor_id=owner, timezone="America/Los_Angeles"))
        ensure_default_spending_policy(db, owner)
        if automatic or rename:
            DocumentPolicy.configure(
                db,
                owner_id=owner,
                expected_version=0,
                classification_mode="after_extraction" if automatic else "off",
                catalog_ids=[
                    row.id
                    for row in db.scalars(
                        select(DocumentType).where(DocumentType.slug != "unclassified")
                    )
                ],
                rename_mode="task" if rename else "off",
                rename_template=DEFAULT_TEMPLATE,
                timezone="America/Los_Angeles",
                external_processing_ack=True,
                request_id=uuid4(),
            )
        doc_type = db.scalar(select(DocumentType).where(DocumentType.slug == kind))
        content = b"Synthetic work history and education"
        imported = DocumentImport.create_from_upload(
            db,
            import_id=import_id,
            owner_id=owner,
            title="scan-0001",
            document_type_id=doc_type.id,
            blob_sha256=hashlib.sha256(content).hexdigest(),
            blob_storage_key=f"sha256/{hashlib.sha256(content).hexdigest()}",
            byte_size=len(content),
            filename="misleading-name.txt",
            media_type="text/plain",
            artifact_id=None,
            expected_version=None,
            request_id=uuid4(),
        )
        artifact_id = imported.artifact_id
    claimed = worker.claim(engine, import_id)
    worker.persist_output(
        engine,
        claimed,
        SimpleNamespace(
            text="Synthetic resume. Work history: example engineer. Education: example degree.",
            document={"synthetic": True},
            producer_version="synthetic-test",
        ),
    )
    return owner, artifact_id, import_id


def request_decision(
    engine, owner, artifact_id, *, automatic=False, provider="typesafe", analysis_context=None
):
    with Session(engine, expire_on_commit=False) as db, db.begin():
        artifact = db.get(Artifact, artifact_id)
        imported = db.scalar(
            select(DocumentImport).where(DocumentImport.artifact_id == artifact_id)
        )
        row = DocumentDecision.request(
            db,
            decision_id=uuid4(),
            owner_id=owner,
            artifact_id=artifact_id,
            metadata_revision=artifact.row_version,
            source_version_id=imported.source_version_id,
            extraction_version_id=imported.extraction_version_id,
            provider=provider,
            request_id=uuid4(),
            automatic=automatic,
            analysis_context=analysis_context,
        )
        return row.id


def review_type(db, owner, artifact_id, slug, *, decision_id=None):
    artifact = db.get(Artifact, artifact_id)
    imported = db.scalar(select(DocumentImport).where(DocumentImport.artifact_id == artifact_id))
    kind = db.scalar(select(DocumentType).where(DocumentType.slug == slug))
    return DocumentClassificationReview.record(
        db,
        review_id=uuid4(),
        owner_id=owner,
        artifact_id=artifact_id,
        metadata_revision=artifact.row_version,
        source_version_id=imported.source_version_id,
        extraction_version_id=imported.extraction_version_id,
        decision_id=decision_id,
        outcome="accept",
        document_type_id=kind.id,
        reason="Human inspected the synthetic source.",
        request_id=uuid4(),
    )


@pytest.mark.parametrize(
    "failure", ["nan", "infinity", "extra", "missing", "keys", "sum", "choice", "type", "model"]
)
def test_strict_document_response_rejects_malformed_answers(failure):
    payload = document_payload(
        "Synthetic document",
        "filename.txt",
        [
            {
                "id": str(uuid4()),
                "name": "Resume",
                "description": "Career experience",
            }
        ],
        "typesafe",
    )
    data = answer(payload)
    choice = data["answers"]["document_type"]
    if failure == "nan":
        choice["probabilities"][choice["choice"]] = float("nan")
    elif failure == "infinity":
        data["answers"]["sufficient_evidence"]["noul"] = float("inf")
    elif failure == "extra":
        data["answers"]["unexpected"] = {"type": "noul", "noul": 0.5}
    elif failure == "missing":
        del data["answers"]["processing_instructions"]
    elif failure == "keys":
        del choice["probabilities"]["mixed"]
    elif failure == "sum":
        choice["probabilities"]["unknown"] = 0.1
    elif failure == "choice":
        choice["choice"] = "unknown"
    elif failure == "type":
        data["answers"]["sufficient_evidence"] = {"type": "choice", "noul": 0.5}
    else:
        data["model"] = "different-model"
    with pytest.raises((ValidationError, ValueError)):
        DocumentResult.model_validate(data).validate_request(payload, "typesafe")


@pytest.mark.parametrize(
    "template",
    ["{type.__class__}", "{person}", "../{type}", "{type!r}", "{type:>20}", "{type}\n", "{"],
)
def test_template_is_an_allowlist_not_an_expression(template):
    with pytest.raises(ValueError):
        validate_template(template)


def test_automatic_jobs_are_opt_in_and_share_extraction_commit(engine):
    owner, artifact_id, _ = seed_document(engine)
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DocumentDecision)
                .where(DocumentDecision.owner_id == owner)
            )
            == 0
        )
    automatic_owner, automatic_artifact, _ = seed_document(engine, automatic=True)
    with Session(engine) as db:
        job = db.scalar(
            select(DocumentDecision).where(DocumentDecision.artifact_id == automatic_artifact)
        )
        assert job is not None and job.state == "queued" and job.trigger == "automatic"
        assert db.get(DocumentImport, job.import_id).state == "completed"
        assert db.get(Task, job.task_id).state == "open"
    assert request_decision(engine, automatic_owner, automatic_artifact, automatic=True) == job.id


def test_manual_type_review_updates_facets_and_renames_only_display_title(engine):
    owner, artifact_id, import_id = seed_document(engine, rename=True)
    with Session(engine) as db, db.begin():
        imported = db.get(DocumentImport, import_id)
        source = db.get(ArtifactVersion, imported.source_version_id)
        fingerprint = (source.content_sha256, source.blob_id, imported.filename, source.id)
        review = review_type(db, owner, artifact_id, "resume")
        db.flush()
        assert db.get(Document, imported.artifact_id).document_type_id == review.accepted_type_id
        assert (
            db.get(Document, imported.extraction_artifact_id).document_type_id
            == review.accepted_type_id
        )
        rename = db.scalar(select(DocumentRename).where(DocumentRename.review_id == review.id))
        assert rename and rename.state == "pending" and rename.after_title.startswith("Resume - ")
        assert db.get(Task, imported.task_id).state == "open"
        rename.apply(owner_id=owner, expected_version=rename.row_version, request_id=uuid4())
        db.flush()
        assert db.get(Artifact, artifact_id).title == rename.after_title
        assert db.get(Task, rename.task_id).state == "done"
        assert (source.content_sha256, source.blob_id, imported.filename, source.id) == fingerprint
        assert (
            db.scalar(
                select(func.count())
                .select_from(ArtifactVersion)
                .where(ArtifactVersion.artifact_id == artifact_id)
            )
            == 1
        )


def test_default_resume_blocks_incompatible_correction_and_future_selection_rechecks(engine):
    owner, artifact_id, import_id = seed_document(engine, kind="resume")
    with Session(engine) as db, db.begin():
        profile = db.get(CandidateProfile, owner)
        imported = db.get(DocumentImport, import_id)
        profile.select_default_resume(imported.source_version_id, request_id=uuid4())
        with pytest.raises(RecordConflict, match="default resume"), db.begin_nested():
            review_type(db, owner, artifact_id, "cover-letter")
        profile.select_default_resume(None, request_id=uuid4())
        review_type(db, owner, artifact_id, "cover-letter")
        db.flush()
        with pytest.raises(ValueError, match="resume"):
            profile.select_default_resume(imported.source_version_id, request_id=uuid4())


def test_document_worker_calls_once_outside_transactions_and_settles_explicit_subject(
    engine, settings, mocker
):
    owner, artifact_id, _ = seed_document(engine)
    decision_id = request_decision(engine, owner, artifact_id)

    async def synthetic_inference(config, claimed):
        with Session(engine) as db:
            assert db.get(DocumentDecision, claimed.id).state == "running"
            reservation = db.get(SpendingReservation, claimed.reservation_id)
            assert (
                reservation.document_decision_id == claimed.id and reservation.agent_run_id is None
            )
            assert reservation.state == "reserved"
        return DocumentResult.model_validate(answer(claimed.payload))

    paid = mocker.patch.object(decision_worker, "infer", side_effect=synthetic_inference)
    assert decision_worker.perform_document_decision(
        engine, configured(settings), decision_id, provenance="mocked"
    )
    assert not decision_worker.perform_document_decision(engine, configured(settings), decision_id)
    assert paid.call_count == 1
    with Session(engine) as db:
        job = db.get(DocumentDecision, decision_id)
        assert job.state == "proposed" and job.provenance == "mocked"
        assert job.cost_status == "settled" and job.answers["document_type"]["confidence"] == 0.94
        assert db.get(Task, job.task_id).state == "open"
        assert "extracted_text" not in str(job.input_manifest)


def test_unknown_outcome_requires_explicit_retry_and_preserves_spending(engine, settings, mocker):
    owner, artifact_id, _ = seed_document(engine)
    decision_id = request_decision(engine, owner, artifact_id)
    paid = mocker.patch.object(
        decision_worker, "infer", side_effect=TimeoutError("private provider details")
    )
    assert decision_worker.perform_document_decision(engine, configured(settings), decision_id)
    assert not decision_worker.perform_document_decision(engine, configured(settings), decision_id)
    with Session(engine) as db:
        row = db.get(DocumentDecision, decision_id)
        assert row.state == "unavailable" and row.answers is None and row.cost_status == "unknown"
        assert "private" not in row.error
        reserve = db.scalar(
            select(SpendingReservation).where(SpendingReservation.document_decision_id == row.id)
        )
        assert reserve.state == "unknown" and reserve.reserved_micros > 0
    new_id = request_decision(engine, owner, artifact_id)
    assert new_id != decision_id and paid.call_count == 1
    with Session(engine) as db:
        assert db.get(DocumentDecision, new_id).attempt == 2


def test_expired_lease_never_replays_or_publishes_paid_output(engine, settings):
    owner, artifact_id, _ = seed_document(engine)
    decision_id = request_decision(engine, owner, artifact_id)
    claimed = decision_worker.claim(engine, configured(settings), decision_id)
    with Session(engine) as db, db.begin():
        row = db.get(DocumentDecision, decision_id)
        row.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.flush()
        assert DocumentDecision.expire_stale(db) >= 1
    decision_worker.persist(
        engine,
        claimed,
        DocumentResult.model_validate(answer(claimed.payload)),
        latency_ms=1,
        provenance="mocked",
    )
    with Session(engine) as db:
        row = db.get(DocumentDecision, decision_id)
        assert row.state == "unavailable" and row.cost_status == "unknown" and row.answers is None
    assert decision_worker.claim(engine, configured(settings), decision_id) is None


def test_stale_title_and_policy_block_rename_apply(engine):
    owner, artifact_id, _ = seed_document(engine, rename=True)
    with Session(engine) as db, db.begin():
        review = review_type(db, owner, artifact_id, "resume")
        db.flush()
        rename = db.scalar(select(DocumentRename).where(DocumentRename.review_id == review.id))
        artifact = db.get(Artifact, artifact_id)
        artifact.title = "Human's newer title"
        db.flush()
        with pytest.raises(RecordConflict, match="metadata"):
            rename.apply(owner_id=owner, expected_version=rename.row_version, request_id=uuid4())
        policy = db.get(DocumentPolicy, owner)
        DocumentPolicy.configure(
            db,
            owner_id=owner,
            expected_version=policy.revision,
            classification_mode="off",
            catalog_ids=[
                row.id
                for row in db.scalars(
                    select(DocumentType).where(DocumentType.slug != "unclassified")
                )
            ],
            rename_mode="off",
            rename_template=DEFAULT_TEMPLATE,
            timezone="UTC",
            external_processing_ack=False,
            request_id=uuid4(),
        )
        assert rename.state == "superseded" and db.get(Task, rename.task_id).state == "cancelled"
        assert artifact.title == "Human's newer title"


def test_manual_api_review_is_human_idempotent_and_provider_independent(engine, settings):
    from command_center.main import create_app

    owner, artifact_id, _ = seed_document(engine, rename=True)
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner, "synthetic")
    with TestClient(app) as client:
        state = client.get(f"/api/v1/documents/{artifact_id}/classification").json()
        assert state["policy"]["provider_ready"] is False
        assert state["policy"]["classification_mode"] == "off"
        resume = next(
            row for row in client.get("/api/v1/document-types").json() if row["slug"] == "resume"
        )
        body = {
            "expected_version": state["metadata_revision"],
            "source_version_id": state["source_version_id"],
            "extraction_version_id": state["extraction_version_id"],
            "decision_id": None,
            "outcome": "accept",
            "document_type_id": resume["id"],
            "reason": "Inspected synthetic contents",
        }
        headers = {"Idempotency-Key": str(uuid4())}
        response = client.post(
            f"/api/v1/documents/{artifact_id}/classification/review", json=body, headers=headers
        )
        assert response.status_code == 200, response.text
        assert (
            client.post(
                f"/api/v1/documents/{artifact_id}/classification/review", json=body, headers=headers
            ).json()
            == response.json()
        )
        assert response.json()["accepted_type_id"] == resume["id"]
        app.dependency_overrides[authenticate] = lambda: Identity(owner, "agent", run_id=uuid4())
        denied = client.post(
            f"/api/v1/documents/{artifact_id}/classification/review",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert denied.status_code == 403


def test_stale_catalog_cannot_accept_old_assessment(engine, settings, mocker):
    owner, artifact_id, _ = seed_document(engine)
    decision_id = request_decision(engine, owner, artifact_id)

    async def infer(config, claimed):
        return DocumentResult.model_validate(answer(claimed.payload, "unknown"))

    mocker.patch.object(decision_worker, "infer", side_effect=infer)
    decision_worker.perform_document_decision(
        engine, configured(settings), decision_id, provenance="mocked"
    )
    with Session(engine) as db, db.begin():
        job = db.get(DocumentDecision, decision_id)
        assert (
            job.state == "needs_review"
            and job.proposed_type_id is None
            and "unknown" in job.reason_codes
        )
        catalog = catalog_for(db, None)
        policy = DocumentPolicy(owner_id=owner, catalog_ids=[catalog[0]["id"]])
        db.add(policy)
        db.flush()
        with pytest.raises(RecordConflict, match="stale"):
            review_type(db, owner, artifact_id, catalog[0]["slug"], decision_id=decision_id)
        data = classification_data(db, artifact_id, owner, settings)
        assert data["latest_decision"]["excerpt"].startswith("Synthetic resume")


def test_cancelled_automatic_request_allows_explicit_manual_attempt(engine, settings):
    owner, artifact_id, _ = seed_document(engine, automatic=True)
    with Session(engine) as db, db.begin():
        row = db.scalar(select(DocumentDecision).where(DocumentDecision.artifact_id == artifact_id))
        original_id = row.id
        db.get(DocumentPolicy, owner).classification_mode = "off"
    assert decision_worker.claim(engine, configured(settings), original_id) is None
    with Session(engine) as db:
        assert db.get(DocumentDecision, original_id).state == "cancelled"
    new_id = request_decision(engine, owner, artifact_id)
    assert new_id != original_id
    with Session(engine) as db:
        assert db.get(DocumentDecision, new_id).attempt == 2


def test_unresolved_model_alias_is_not_reused_indefinitely(engine, settings, mocker):
    owner, artifact_id, _ = seed_document(engine)
    config = settings.model_copy(
        update={"jev_provider": "gateway", "ai_gateway_api_key": SecretStr("synthetic")}
    )
    first = request_decision(engine, owner, artifact_id, provider="gateway")

    async def infer(config, claimed):
        return DocumentResult.model_validate(answer(claimed.payload))

    mocker.patch.object(decision_worker, "infer", side_effect=infer)
    decision_worker.perform_document_decision(engine, config, first, provenance="mocked")
    with Session(engine) as db:
        row = db.get(DocumentDecision, first)
        assert row.state == "proposed" and row.resolved_model is None
    assert request_decision(engine, owner, artifact_id, provider="gateway") != first


def test_stale_successful_inference_settles_known_usage(engine, settings, mocker):
    owner, artifact_id, _ = seed_document(engine)
    decision_id = request_decision(engine, owner, artifact_id)

    async def infer(config, claimed):
        with Session(engine) as db, db.begin():
            db.get(Artifact, artifact_id).title = "New title during inference"
        return DocumentResult.model_validate(answer(claimed.payload))

    mocker.patch.object(decision_worker, "infer", side_effect=infer)
    decision_worker.perform_document_decision(
        engine, configured(settings), decision_id, provenance="mocked"
    )
    with Session(engine) as db:
        row = db.get(DocumentDecision, decision_id)
        assert row.state == "superseded" and row.cost_status == "settled"
        assert row.usage["input_tokens"] == 400 and row.answers is not None


def test_claim_and_human_review_share_owner_first_lock_order(engine, settings):
    owner, artifact_id, _ = seed_document(engine)
    decision_id = request_decision(engine, owner, artifact_id)
    owner_lock_attempted = threading.Event()

    def observe(connection, cursor, statement, parameters, context, executemany):
        if (
            threading.current_thread().name.startswith("document-claim")
            and "FROM actors" in statement
            and "FOR UPDATE" in statement
        ):
            owner_lock_attempted.set()

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-claim") as executor:
            with Session(engine) as db, db.begin():
                db.execute(text("SET LOCAL lock_timeout='2s'"))
                db.scalar(select(Actor).where(Actor.id == owner).with_for_update())
                future = executor.submit(
                    decision_worker.claim, engine, configured(settings), decision_id
                )
                assert owner_lock_attempted.wait(3)
                # A claim must not hold the document while waiting on its owner.
                review_type(db, owner, artifact_id, "resume")
            assert future.result(timeout=3) is None
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "context",
    [
        {"unknown": "not allowed"},
        {"claim": "x" * 4001},
        {"research_query": "   "},
        {
            "claim": "a" * 4000,
            "policy": "b" * 4000,
            "agent_request": "c" * 4000,
            "research_query": "d",
        },
    ],
)
def test_document_analysis_context_bounds_reject_invalid_input(context):
    with pytest.raises(ValidationError):
        DocumentAnalysisContext.model_validate(context)


def test_context_changes_fingerprint_and_worker_reconstructs_exact_snapshot(engine, settings):
    owner, artifact_id, _ = seed_document(engine)
    context = {
        "research_query": "  Find synthetic engineering experience.  ",
        "claim": "The synthetic candidate worked as an engineer.",
        "agent_request": "Summarize this synthetic document with sources.",
        "policy": "Use only source-supported claims.",
        "proposed_action": "Create an unsent summary for human review.",
    }
    parsed = DocumentAnalysisContext.model_validate(context).model_dump(exclude_none=True)
    assert parsed == context
    contextual = request_decision(engine, owner, artifact_id, analysis_context=context)
    base = request_decision(engine, owner, artifact_id)
    assert contextual != base
    claimed = decision_worker.claim(engine, configured(settings), contextual)
    with Session(engine) as db:
        job = db.get(DocumentDecision, contextual)
        assert job.input_manifest["analysis_context"] == context
        imported = db.get(DocumentImport, job.import_id)
        extraction = db.get(ArtifactVersion, job.extraction_version_id)
        expected = document_payload(
            extraction.payload["text"],
            imported.filename,
            job.catalog_snapshot,
            "typesafe",
            analysis_context=context,
        )
        assert claimed.payload == expected
        assert len(claimed.payload["questions"]) == 13
        assert db.scalar(select(func.count()).select_from(Task).where(Task.owner_id == owner)) == 1
    decision_worker.persist(
        engine,
        claimed,
        DocumentResult.model_validate(answer(claimed.payload)),
        latency_ms=0,
        provenance="mocked",
    )
    with Session(engine) as db:
        job = db.get(DocumentDecision, contextual)
        assert job.answers["relevance"]["type"] == "score"
        assert job.answers["evidence_role"]["choice"] == "direct_evidence"
        assert len(job.answers) == 13 and job.cost_status == "settled"
        assert db.scalar(select(func.count()).select_from(Task).where(Task.owner_id == owner)) == 1


def test_contextual_http_request_is_inspectable_and_owner_scoped(engine, settings, mocker):
    from command_center.main import create_app

    owner, artifact_id, _ = seed_document(engine)
    app = create_app(configured(settings))
    app.dependency_overrides[authenticate] = lambda: Identity(owner, "synthetic")
    mocker.patch("command_center.agents.queue.execute_document_decision.apply_async")
    with TestClient(app) as client:
        current = client.get(f"/api/v1/documents/{artifact_id}/classification").json()
        body = {
            "expected_version": current["metadata_revision"],
            "source_version_id": current["source_version_id"],
            "extraction_version_id": current["extraction_version_id"],
            "external_processing_ack": True,
            "analysis_context": {"research_query": "Synthetic reference question"},
        }
        response = client.post(
            f"/api/v1/documents/{artifact_id}/classification",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 202, response.text
        assessment = response.json()
        assert assessment["input_manifest"]["analysis_context"] == body["analysis_context"]
        assert "relevance" in assessment["questions"] and assessment["answers"] is None
        body["analysis_context"] = {"unsupported": "bad"}
        invalid = client.post(
            f"/api/v1/documents/{artifact_id}/classification",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert invalid.status_code == 422
        foreign = uuid4()
        app.dependency_overrides[authenticate] = lambda: Identity(foreign, "other")
        assert client.get(f"/api/v1/documents/decisions/{assessment['id']}").status_code == 404


def test_unchanged_rendered_title_does_not_create_a_rename_task(engine):
    owner, artifact_id, _ = seed_document(engine, rename=True)
    with Session(engine) as db, db.begin():
        db.get(DocumentPolicy, owner).rename_template = "scan-0001"
        review_type(db, owner, artifact_id, "resume")
        db.flush()
        assert (
            db.scalar(
                select(func.count())
                .select_from(DocumentRename)
                .where(DocumentRename.owner_id == owner)
            )
            == 0
        )
        assert db.scalar(select(func.count()).select_from(Task).where(Task.owner_id == owner)) == 1


def test_rename_cancel_preserves_title_and_closes_only_rename_task(engine):
    owner, artifact_id, import_id = seed_document(engine, rename=True)
    with Session(engine) as db, db.begin():
        review = review_type(db, owner, artifact_id, "resume")
        db.flush()
        rename = db.scalar(select(DocumentRename).where(DocumentRename.review_id == review.id))
        rename.close("cancelled", request_id=uuid4())
        assert db.get(Artifact, artifact_id).title == "scan-0001"
        assert db.get(Task, rename.task_id).state == "cancelled"
        assert db.get(Task, db.get(DocumentImport, import_id).task_id).state == "open"
        with pytest.raises(RecordConflict):
            rename.apply(owner_id=owner, expected_version=rename.row_version, request_id=uuid4())
