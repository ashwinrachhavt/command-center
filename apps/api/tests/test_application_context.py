"""Application sources are explicit, owned, immutable and never candidate facts."""

from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_application_preparations import client as client
from test_application_preparations import post, prepare, running_agent, shared_page

from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import ArtifactVersion, TaskArtifact
from command_center.db.evidence import SourceRecord
from command_center.db.models import Actor
from command_center.db.profile_facts import ProfileFact


def job_description(**extra):
    return {
        "job_title": "Synthetic Product Engineer",
        "company_name": "Synthetic Northstar",
        "text": "Build dependable tools. Experience with APIs and accessible web interfaces.",
        "extraction_method": "json_ld",
        "truncated": False,
        **extra,
    }


def test_captured_context_is_versioned_source_and_continuation_preserves_human_edits(
    client, engine
):
    snapshot, headers = shared_page(client)
    preparation = prepare(client, snapshot, job_context=job_description())
    path = f"applications/{preparation['task_id']}/job-context"
    context = client.get("/api/v1/" + path).json()
    assert context["text"] == job_description()["text"]
    assert context["extraction_method"] == "json_ld"
    assert context["page_url"] == snapshot["page_url"]
    edited = post(
        client,
        f"artifacts/{context['artifact_id']}/versions",
        {
            "based_on_version_id": context["version_id"],
            "expected_version": context["expected_version"],
            "text": "My corrected job requirements, with the original source metadata retained.",
        },
    )
    assert edited.status_code == 201, edited.text
    body = {key: snapshot[key] for key in ("protocol_version", "page_url", "title", "fields")}
    body["id"] = str(uuid4())
    fresh = post(client, "browser/snapshots", body, headers=headers).json()
    prepare(
        client,
        fresh,
        continue_preparation_id=preparation["id"],
        job_context=job_description(
            text="New page noise must not replace the saved job description."
        ),
    )
    restored = client.get("/api/v1/" + path).json()
    assert restored["version_id"] == edited.json()["id"]
    assert restored["text"].startswith("My corrected")
    assert restored["job_title"] == job_description()["job_title"]
    with Session(engine) as db:
        original = db.get(ArtifactVersion, UUID(context["version_id"]))
        assert original.payload["text"] == job_description()["text"]
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProfileFact)
                .where(ProfileFact.owner_id == client.actor_id)
            )
            == 0
        )
        source = db.scalar(
            select(SourceRecord).where(SourceRecord.artifact_version_id == original.id)
        )
        assert source and source.provider == "browser_companion"
        assert db.get(TaskArtifact, (UUID(preparation["task_id"]), UUID(context["artifact_id"])))


def test_manual_writer_starts_from_one_retry_safe_saved_base(client):
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    path = f"applications/{preparation['task_id']}/job-context"
    assert client.get("/api/v1/" + path).json() is None
    key = uuid4()
    body = {"expected_version": 1, "job_title": "Synthetic role"}
    saved = post(client, path, body, key=key)
    assert saved.status_code == 201, saved.text
    assert saved.json()["text"] == ""
    assert saved.json()["extraction_method"] == "manual"
    assert post(client, path, body, key=key).json() == saved.json()
    assert (
        post(client, path, {**body, "expected_version": 2, "text": "Do not replace."}).status_code
        == 409
    )
    app = client.get(f"/api/v1/applications/{preparation['task_id']}").json()
    assert app["job_context_artifact_id"] == saved.json()["artifact_id"]
    assert app["row_version"] == 2 and app["status"] == "preparing"


def test_application_agent_reads_saved_requirements_by_exact_source_version(client, engine):
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot, job_context=job_description())
    saved = client.get(f"/api/v1/applications/{preparation['task_id']}/job-context").json()
    headers, _ = running_agent(client, engine, preparation)
    response = client.get(
        f"/api/v1/browser/preparations/{preparation['id']}/context", headers=headers
    )
    assert response.status_code == 200, response.text
    source = response.json()["job_context"]
    assert source["version_id"] == saved["version_id"]
    assert "text" not in source
    text = client.get(f"/api/v1/documents/versions/{source['version_id']}/text", headers=headers)
    assert text.status_code == 200, text.text
    assert text.json()["text"] == job_description()["text"]


def test_context_is_owned_and_cannot_claim_a_different_source_page(client, engine):
    snapshot, _ = shared_page(client)
    malformed = post(
        client,
        f"browser/snapshots/{snapshot['id']}/preparations",
        {
            "job_context": job_description(page_url="https://elsewhere.example.test/private"),
        },
    )
    assert malformed.status_code == 422
    preparation = prepare(client, snapshot)
    path = f"/api/v1/applications/{preparation['task_id']}/job-context"
    other = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other, kind="human", display_name="Synthetic unrelated applicant"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other, "synthetic")
    assert client.get(path).status_code == 404
    assert (
        client.post(
            path,
            json={"expected_version": 1, "text": "Other source"},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 404
    )
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic", run_id=uuid4()
    )
    assert client.get(path).status_code == 403


def test_context_migration_refuses_to_discard_saved_job_links(client, engine, migration_config):
    from test_migrations import clear_question_fixtures

    clear_question_fixtures(engine)
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot, job_context=job_description())
    with pytest.raises(RuntimeError, match="refusing to discard their links"):
        command.downgrade(migration_config, "0024_application_tracking")
    current = client.get(f"/api/v1/applications/{preparation['task_id']}/job-context")
    assert current.status_code == 200 and current.json()["text"] == job_description()["text"]
