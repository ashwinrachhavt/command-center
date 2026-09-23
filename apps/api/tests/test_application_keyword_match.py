"""Keyword coverage is an owned, read-only comparison of exact document versions."""

import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_application_context import job_description
from test_application_materials import human, material_inputs
from test_application_preparations import client as client
from test_application_preparations import post, prepare, shared_page, upload_resume

from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.application_materials import ApplicationMaterial
from command_center.db.applications import ApplicationTrack
from command_center.db.artifacts import Artifact, ArtifactVersion, Blob, DocumentType
from command_center.db.base import utc_now
from command_center.db.document_imports import DocumentImport
from command_center.db.idempotency import RequestReceipt
from command_center.db.models import Actor, Task
from command_center.db.pdf_exports import PdfExport
from command_center.db.profile_facts import ProfileFact


def inputs(client, engine, **options):
    preparation, material, _ = material_inputs(client, engine, approve=False, **options)
    return (
        f"/api/v1/applications/{preparation['task_id']}/keyword-match",
        {key: material[key] for key in ("job_version_id", "resume_version_id")},
        preparation,
    )


def counts(db):
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model))
        for model in (
            AgentRun,
            ApplicationMaterial,
            ArtifactVersion,
            ProfileFact,
            RequestReceipt,
            Task,
        )
    }


def test_keyword_match_pins_extraction_and_is_read_only_without_profile_approval(client, engine):
    route, body, preparation = inputs(client, engine)
    with Session(engine) as db, db.begin():
        imported = db.scalar(
            select(DocumentImport).where(
                DocumentImport.source_version_id == UUID(body["resume_version_id"])
            )
        )
        source_id = imported.extraction_version_id
        source = db.get(ArtifactVersion, source_id)
        # A newer source version must not silently replace the original extraction.
        db.get(Artifact, source.artifact_id).append_text(
            "Python", version_id=uuid4(), request_id=uuid4()
        )
    body["keywords"] = ["accessible tools", "Python"]
    with Session(engine) as db:
        before = counts(db)
    result = client.post(route, json=body)
    assert result.status_code == 200, result.text
    report = result.json()
    assert report["job"]["version_id"] == body["job_version_id"]
    assert report["resume"]["version_id"] == body["resume_version_id"]
    assert report["resume_source"]["version_id"] == str(source_id)
    assert report["analysis"]["score"] == 50
    assert report["analysis"]["keywords"] == [
        {"term": "accessible tools", "matched": True},
        {"term": "Python", "matched": False},
    ]
    assert client.post(route, json=body).json() == report
    with Session(engine) as db:
        assert counts(db) == before
        assert db.get(Task, UUID(preparation["task_id"])).state == "open"
        assert db.get(ApplicationTrack, UUID(preparation["task_id"])).status == "preparing"


def test_keyword_match_rejects_stale_job(client, engine):
    route, body, preparation = inputs(client, engine)
    context_route = f"/api/v1/applications/{preparation['task_id']}/job-context"
    context = client.get(context_route).json()
    changed = post(
        client,
        f"artifacts/{context['artifact_id']}/versions",
        {
            "based_on_version_id": context["version_id"],
            "expected_version": context["expected_version"],
            "text": "Required: Python and TypeScript.",
        },
    )
    assert changed.status_code == 201, changed.text
    assert client.post(route, json=body).status_code == 409
    current = client.get(context_route).json()
    body["job_version_id"] = current["version_id"]
    report = client.post(route, json=body).json()
    assert report["job"]["version_id"] == current["version_id"]
    assert report["analysis"]["mode"] == "detected"
    assert report["analysis"]["score"] == 0
    assert {term["term"] for term in report["analysis"]["keywords"]} == {
        "Python",
        "TypeScript",
    }


def test_keyword_match_reports_shortened_saved_description(client, engine):
    _, body, _ = inputs(client, engine)
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot, job_context=job_description(truncated=True))
    context = client.get(f"/api/v1/applications/{preparation['task_id']}/job-context").json()
    body["job_version_id"] = context["version_id"]
    result = client.post(f"/api/v1/applications/{preparation['task_id']}/keyword-match", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["job_truncated"] is True


@pytest.mark.parametrize("target", ["job", "resume", "extraction"])
def test_keyword_match_rejects_archived_sources(client, engine, target):
    route, body, _ = inputs(client, engine)
    with Session(engine) as db, db.begin():
        version_id = UUID(body["job_version_id" if target == "job" else "resume_version_id"])
        if target == "extraction":
            version_id = db.scalar(
                select(DocumentImport.extraction_version_id).where(
                    DocumentImport.source_version_id == version_id
                )
            )
        source = db.get(ArtifactVersion, version_id)
        db.get(Artifact, source.artifact_id).archived_at = utc_now()
    assert client.post(route, json=body).status_code == 409


def test_keyword_match_requires_readable_source_and_valid_selected_keywords(client, engine):
    route, body, _ = inputs(client, engine, extract=False)
    response = client.post(route, json=body)
    assert response.status_code == 409
    assert "extracting" in response.json()["detail"]
    for keywords in ([], ["a" * 81], ["Python"] * 51):
        assert client.post(route, json={**body, "keywords": keywords}).status_code == 422
    with Session(engine) as db, db.begin():
        imported = db.scalar(
            select(DocumentImport).where(
                DocumentImport.source_version_id == UUID(body["resume_version_id"])
            )
        )
        extraction = DocumentImport.claim(db, imported.id)
        source = Artifact(
            id=uuid4(),
            owner_id=client.actor_id,
            created_by_id=client.actor_id,
            title="Synthetic empty extraction",
            kind="source",
            sensitivity="private",
        )
        db.add(source)
        db.flush()
        version = source.append_text("", version_id=uuid4(), request_id=uuid4())
        db.flush()
        extraction.complete(
            extraction.lease_id,
            extraction_artifact_id=source.id,
            extraction_version_id=version.id,
            request_id=uuid4(),
        )
    assert client.post(route, json=body).status_code == 409
    route, body, _ = inputs(client, engine)
    assert client.post(route, json={**body, "keywords": [" "]}).status_code == 422


def test_keyword_match_is_human_owned_and_rejects_foreign_or_wrong_type_resume(client, engine):
    route, body, _ = inputs(client, engine)
    other_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other_id, kind="human", display_name="Synthetic other applicant"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other_id, "synthetic")
    assert client.post(route, json=body).status_code == 404
    foreign_resume = upload_resume(client)
    human(client)
    assert client.post(route, json={**body, "resume_version_id": foreign_resume}).status_code == 409
    assert (
        client.post(route, json={**body, "resume_version_id": body["job_version_id"]}).status_code
        == 409
    )
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic", run_id=uuid4()
    )
    assert client.post(route, json=body).status_code == 403


def test_keyword_match_uses_exact_source_of_completed_resume_pdf(client, engine):
    route, body, _ = inputs(client, engine)
    with Session(engine) as db, db.begin():
        doc_type = db.scalar(select(DocumentType).where(DocumentType.slug == "resume"))
        artifact = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=client.actor_id,
            title="Synthetic tailored resume",
            kind="document",
            sensitivity="private",
            text="Python and TypeScript",
            document_type_id=doc_type.id,
            request_id=uuid4(),
        )
        db.flush()
        source = db.scalar(
            select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
        )
        export = PdfExport.create(
            db,
            record_id=uuid4(),
            owner_id=client.actor_id,
            artifact_id=artifact.id,
            version_id=source.id,
            renderer_revision="sha256:" + "a" * 64,
            task_id=None,
            request_id=uuid4(),
        )
        db.flush()
        PdfExport.claim(db, export.id)
        content = b"%PDF-1.7\nsynthetic keyword comparison fixture"
        digest = hashlib.sha256(content).hexdigest()
        blob = db.scalar(select(Blob).where(Blob.sha256 == digest))
        if blob is None:
            blob = Blob(sha256=digest, storage_key=f"sha256/{digest}", byte_size=len(content))
            db.add(blob)
        db.flush()
        output = export.complete(export.lease_id, blob=blob, request_id=uuid4())
        db.flush()
        body["resume_version_id"] = str(output.id)
        source_id = source.id
        artifact.append_text("Different content", version_id=uuid4(), request_id=uuid4())
    body["keywords"] = ["Python", "TypeScript"]
    result = client.post(route, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["resume_source"]["version_id"] == str(source_id)
    assert result.json()["analysis"]["score"] == 100
