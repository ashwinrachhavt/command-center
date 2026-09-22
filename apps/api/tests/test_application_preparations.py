"""Synthetic application drafts exercise ownership, review, evidence and job boundaries."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.capabilities import issue_run_token
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.application_preparations import ApplicationPreparation, answer_context
from command_center.db.artifacts import ArtifactVersion, TaskArtifact
from command_center.db.base import utc_now
from command_center.db.browser import BrowserSnapshot
from command_center.db.conversations import AgentMessage
from command_center.db.models import Actor, Task
from command_center.main import create_app


@pytest.fixture
def client(settings, engine, tmp_path, mocker):
    actor_id = uuid4()
    config = settings.model_copy(
        update={
            "blob_store_path": tmp_path / "blobs",
            "openai_api_key": SecretStr("synthetic-model-key"),
        }
    )
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic applicant"))
    app = create_app(config)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    mocker.patch("command_center.api.documents.dispatch_import")
    with TestClient(app) as http:
        http.actor_id = actor_id
        http.human_identity = app.dependency_overrides[authenticate]
        yield http


def post(client, path, body, *, key=None, headers=None):
    return client.post(
        "/api/v1/" + path,
        json=body,
        headers={"Idempotency-Key": str(key or uuid4()), **(headers or {})},
    )


def shared_page(client, fields=None):
    paired = post(client, "browser/pairings", {"name": "Synthetic browser"}).json()
    credentials = client.post(
        "/api/v1/browser/pairings/exchange", json={"code": paired["code"]}
    ).json()
    headers = {"Authorization": "Bearer " + credentials["token"]}
    fields = fields or [
        {"id": "f0", "label": "Full name", "type": "text", "value_state": "empty"},
        {
            "id": "f1",
            "label": "Describe your experience",
            "type": "textarea",
            "value_state": "empty",
        },
        {"id": "f2", "label": "Email", "type": "email", "value_state": "present"},
        {
            "id": "f3",
            "label": "Are you authorized to work here?",
            "type": "select",
            "options": ["Yes", "No"],
            "value_state": "empty",
        },
        {
            "id": "f4",
            "label": "Resume",
            "type": "file",
            "accept": "text/plain",
            "value_state": "empty",
        },
    ]
    response = post(
        client,
        "browser/snapshots",
        {
            "id": str(uuid4()),
            "protocol_version": 2,
            "page_url": "https://jobs.example.test/apply",
            "title": "Synthetic role",
            "fields": fields,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json(), headers


def fact(client, field="full_name", value="Synthetic Person", **extra):
    created = post(client, "profile/facts", {"field": field, "value": value, **extra})
    assert created.status_code == 201, created.text
    return created.json()


def review_fact(client, value, decision="approved"):
    response = post(
        client,
        f"profile/facts/{value['id']}/reviews",
        {
            "expected_version": value["row_version"],
            "revision_id": value["current"]["id"],
            "decision": decision,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def prepare(client, snapshot, **body):
    response = post(client, f"browser/snapshots/{snapshot['id']}/preparations", body)
    assert response.status_code == 201, response.text
    return response.json()


def revise(client, preparation, **body):
    response = post(
        client,
        f"browser/preparations/{preparation['id']}/revisions",
        {
            "expected_version_id": preparation["version_id"],
            "resume_version_id": preparation["resume"]["version_id"]
            if preparation["resume"]
            else None,
            **body,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def opportunity(client):
    company = post(client, "companies", {"name": "Synthetic Example"}).json()
    created = post(
        client, "opportunities", {"title": "Synthetic role", "company_id": company["id"]}
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_reviewed_number_answer_obeys_snapshot_constraints(client):
    snapshot, _ = shared_page(
        client,
        fields=[
            {
                "id": "f0",
                "label": "Years of experience",
                "type": "number",
                "value_state": "empty",
                "numeric_constraints": {
                    "minimum": "0.1",
                    "maximum": "1.1",
                    "step": "0.2",
                    "step_base": "0.1",
                },
            }
        ],
    )
    preparation = prepare(client, snapshot)
    rejected = post(
        client,
        f"browser/preparations/{preparation['id']}/revisions",
        {
            "expected_version_id": preparation["version_id"],
            "resume_version_id": None,
            "fields": {"f0": "0.2"},
        },
    )
    assert rejected.status_code == 422, rejected.text
    reviewed = revise(client, preparation, fields={"f0": "0.3"})
    assert reviewed["fields"][0]["value"] == "0.3"


def upload_resume(client, content=b"Synthetic exact resume"):
    resume_type = next(
        item for item in client.get("/api/v1/document-types").json() if item["slug"] == "resume"
    )
    uploaded = client.post(
        "/api/v1/documents/imports",
        data={"title": "Synthetic resume", "document_type_id": resume_type["id"]},
        files={"file": ("resume.txt", content, "text/plain")},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert uploaded.status_code == 202, uploaded.text
    return uploaded.json()["source_version_id"]


def running_agent(client, engine, preparation):
    queued = post(client, f"browser/preparations/{preparation['id']}/generate", {})
    assert queued.status_code == 202, queued.text
    run_id = UUID(queued.json()["run_id"])
    with Session(engine) as db, db.begin():
        run = AgentRun.claim(db, run_id)
        assert run is not None
        token = issue_run_token(client.app.state.settings, run.id, run.lease_id)
    client.app.dependency_overrides.pop(authenticate)
    return {"Authorization": "Bearer " + token}, run_id


def test_preparation_uses_active_approval_preserves_page_and_reuses_receipt(client, engine):
    active = review_fact(client, fact(client))
    pending = post(
        client,
        f"profile/facts/{active['id']}/versions",
        {"expected_version": active["row_version"], "value": "Unreviewed changed name"},
    )
    assert pending.status_code == 201, pending.text
    fact(client, "experience", "Unapproved personal claim")
    review_fact(client, fact(client, "email", "synthetic@example.test"))
    snapshot, _ = shared_page(client)
    key = uuid4()
    route = f"browser/snapshots/{snapshot['id']}/preparations"
    response = post(client, route, {}, key=key)
    assert response.status_code == 201, response.text
    preparation = response.json()
    assert post(client, route, {}, key=key).json() == preparation
    answers = {item["field_id"]: item for item in preparation["fields"]}
    assert answers["f0"]["value"] == "Synthetic Person"
    assert answers["f0"]["evidence"][0]["revision_id"] == active["active"]["id"]
    assert answers["f1"]["status"] == "needs_input"
    assert answers["f2"]["status"] == "preserved" and answers["f2"]["value"] is None
    assert answers["f3"]["status"] == "needs_input"
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationPreparation)
                .where(ApplicationPreparation.owner_id == client.actor_id)
            )
            == 1
        )
        assert db.get(Task, UUID(preparation["task_id"])).state == "open"
        assert db.get(
            TaskArtifact, (UUID(preparation["task_id"]), UUID(preparation["artifact_id"]))
        )
        assert (
            db.get(ArtifactVersion, UUID(preparation["version_id"])).schema_key
            == "application.answers.v1"
        )


def test_exact_human_review_required_and_revoked_fact_blocks_claim(client, engine):
    approved = review_fact(client, fact(client))
    snapshot, device_headers = shared_page(client)
    preparation = prepare(client, snapshot)
    command = {
        "snapshot_id": snapshot["id"],
        "fields": {"f0": "Synthetic Person"},
        "preparation_version_id": preparation["version_id"],
    }
    assert post(client, "browser/commands", command).status_code == 409
    reviewed = revise(client, preparation, fields={"f0": "Synthetic Person"})
    assert reviewed["fields"][0]["evidence"]
    command["preparation_version_id"] = reviewed["version_id"]
    proposed = post(client, "browser/commands", command)
    assert proposed.status_code == 201, proposed.text
    assert (
        post(
            client, "browser/commands", command | {"fields": {"f0": "Unreviewed replacement"}}
        ).status_code
        == 409
    )
    review_fact(client, approved, "revoked")
    assert (
        client.post(
            f"/api/v1/browser/device/commands/{proposed.json()['id']}/claim", headers=device_headers
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            f"browser/preparations/{reviewed['id']}/revisions",
            {
                "expected_version_id": reviewed["version_id"],
                "resume_version_id": None,
                "fields": {"f0": "Synthetic Person"},
            },
        ).status_code
        == 409
    )


def test_review_pins_explicit_replacement_and_selected_upload_field(client):
    snapshot, device_headers = shared_page(client)
    first = upload_resume(client)
    other = upload_resume(client, b"Different synthetic resume")
    preparation = prepare(client, snapshot, resume_version_id=first)
    bad = post(
        client,
        f"browser/preparations/{preparation['id']}/revisions",
        {
            "expected_version_id": preparation["version_id"],
            "resume_version_id": first,
            "fields": {"f2": "new@example.test"},
        },
    )
    assert bad.status_code == 422
    reviewed = revise(
        client,
        preparation,
        fields={"f2": "new@example.test"},
        replace_fields=["f2"],
        upload_fields=["f4"],
    )
    command = {
        "snapshot_id": snapshot["id"],
        "fields": {"f2": "new@example.test"},
        "uploads": {"f4": first},
        "replace_fields": ["f2"],
        "preparation_version_id": reviewed["version_id"],
    }
    assert post(client, "browser/commands", command | {"uploads": {"f4": other}}).status_code == 409
    proposed = post(client, "browser/commands", command)
    assert proposed.status_code == 201, proposed.text
    path = f"/api/v1/browser/device/commands/{proposed.json()['id']}"
    assert client.post(path + "/claim", headers=device_headers).status_code == 200
    assert (
        client.get(path + "/files/f4", headers=device_headers).content == b"Synthetic exact resume"
    )
    with_no_upload_selection = revise(
        client,
        reviewed,
        fields={"f2": "new@example.test"},
        upload_fields=[],
        replace_fields=["f2"],
    )
    assert (
        post(
            client,
            "browser/commands",
            command | {"preparation_version_id": with_no_upload_selection["version_id"]},
        ).status_code
        == 409
    )


def test_stale_revisions_and_foreign_devices_cannot_modify_preparation(client):
    snapshot, device_headers = shared_page(client)
    _, other_device = shared_page(client)
    route = f"browser/device/snapshots/{snapshot['id']}/preparations"
    assert post(client, route, {}, headers=other_device).status_code == 404
    created = post(client, route, {}, headers=device_headers)
    assert created.status_code == 201, created.text
    preparation = created.json()
    assert (
        client.get(
            f"/api/v1/browser/device/preparations/{preparation['id']}", headers=other_device
        ).status_code
        == 404
    )
    revised = revise(client, preparation, fields={"f1": "Human reviewed answer"})
    stale = post(
        client,
        f"browser/preparations/{preparation['id']}/revisions",
        {
            "expected_version_id": preparation["version_id"],
            "resume_version_id": None,
            "fields": {"f1": "Overwritten"},
        },
    )
    assert stale.status_code == 409
    assert (
        client.get(f"/api/v1/browser/preparations/{preparation['id']}").json()["version_id"]
        == revised["version_id"]
    )
    client.app.dependency_overrides[authenticate] = lambda: Identity(uuid4(), "stranger")
    assert client.get(f"/api/v1/browser/preparations/{preparation['id']}").status_code == 404


def test_confirmed_answer_is_reusable_only_for_same_opportunity_and_question(client):
    chosen = opportunity(client)
    other = opportunity(client)
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot, opportunity_id=chosen)
    revise(client, preparation, fields={"f3": "Yes"}, remember_fields=["f3"])
    next_page, _ = shared_page(client)
    same = prepare(client, next_page, opportunity_id=chosen)
    different = prepare(client, next_page, opportunity_id=other)
    assert same["fields"][3]["value"] == "Yes"
    assert different["fields"][3]["status"] == "needs_input"
    assert same["fields"][3]["evidence"][0]["context"] == answer_context(
        UUID(chosen), snapshot["fields"][3]["label"]
    )
    no_scope = prepare(client, next_page)
    assert (
        post(
            client,
            f"browser/preparations/{no_scope['id']}/revisions",
            {
                "expected_version_id": no_scope["version_id"],
                "resume_version_id": None,
                "fields": {"f3": "Yes"},
                "remember_fields": ["f3"],
            },
        ).status_code
        == 422
    )


def test_expired_facts_and_expired_snapshots_do_not_prepare(client, engine, mocker):
    review_fact(client, fact(client, valid_until=(utc_now() + timedelta(minutes=1)).isoformat()))
    mocker.patch(
        "command_center.db.application_preparations.utc_now",
        return_value=utc_now() + timedelta(minutes=2),
    )
    snapshot, _ = shared_page(client)
    assert prepare(client, snapshot)["fields"][0]["status"] == "needs_input"
    with Session(engine) as db, db.begin():
        db.get(BrowserSnapshot, UUID(snapshot["id"])).created_at = utc_now() - timedelta(minutes=31)
    expired = post(client, f"browser/snapshots/{snapshot['id']}/preparations", {})
    assert expired.status_code == 409 and "expired" in expired.json()["detail"]


def test_generation_enqueues_once_in_task_conversation(client, engine):
    snapshot, device_headers = shared_page(client)
    preparation = prepare(client, snapshot)
    status_path = f"/api/v1/browser/device/preparations/{preparation['id']}/generation"
    assert client.get(status_path, headers=device_headers).json()["state"] == "idle"
    key = uuid4()
    path = f"browser/preparations/{preparation['id']}/generate"
    generated = post(client, path, {}, key=key)
    assert generated.status_code == 202, generated.text
    assert post(client, path, {}, key=key).json() == generated.json()
    assert post(client, path, {}).json() == generated.json()
    status = client.get(status_path, headers=device_headers)
    assert status.status_code == 200
    assert status.json() == generated.json() | {"state": "queued", "error_code": None}
    _, foreign_device_headers = shared_page(client)
    assert client.get(status_path, headers=foreign_device_headers).status_code == 404
    with Session(engine) as db:
        run = db.get(AgentRun, UUID(generated.json()["run_id"]))
        assert run.state == "queued" and run.profile == "application"
        assert str(preparation["id"]) in run.prompt
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.owner_id == client.actor_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentMessage)
                .where(AgentMessage.session_id == run.session_id, AgentMessage.author == "user")
            )
            == 1
        )
    with Session(engine) as db, db.begin():
        run = db.get(AgentRun, UUID(generated.json()["run_id"]))
        run.state = "failed"
        run.error_code = "provider_unavailable"
    assert client.get(status_path, headers=device_headers).json() == generated.json() | {
        "state": "failed",
        "error_code": "provider_unavailable",
    }


def test_review_requires_every_retained_answer_and_allows_explicit_clear(client):
    review_fact(client, fact(client))
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    omitted = post(
        client,
        f"browser/preparations/{preparation['id']}/revisions",
        {
            "expected_version_id": preparation["version_id"],
            "resume_version_id": None,
            "fields": {"f1": "My answer"},
        },
    )
    assert omitted.status_code == 409
    reviewed = revise(client, preparation, fields={"f0": "", "f1": "My answer"})
    assert reviewed["fields"][0]["value"] is None
    command = {
        "snapshot_id": snapshot["id"],
        "preparation_version_id": reviewed["version_id"],
    }
    assert (
        post(
            client, "browser/commands", command | {"fields": {"f0": "Synthetic Person"}}
        ).status_code
        == 409
    )
    assert (
        post(client, "browser/commands", command | {"fields": {"f1": "My answer"}}).status_code
        == 201
    )


def test_scalar_suggestion_requires_exact_matching_fact(client, engine):
    approved_name = review_fact(client, fact(client))
    experience = review_fact(client, fact(client, "experience", "Built synthetic systems"))
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    headers, _ = running_agent(client, engine, preparation)
    path = f"browser/preparations/{preparation['id']}/suggestions"
    body = {
        "expected_version_id": preparation["version_id"],
        "answers": [
            {
                "field_id": "f0",
                "value": "Invented Person",
                "fact_revision_ids": [experience["active"]["id"]],
            }
        ],
    }
    assert post(client, path, body, headers=headers).status_code == 422
    body["answers"][0]["fact_revision_ids"] = [approved_name["active"]["id"]]
    assert post(client, path, body, headers=headers).status_code == 422
    body["answers"][0]["value"] = "Synthetic Person"
    saved = post(client, path, body, headers=headers)
    assert saved.status_code == 201, saved.text
    assert saved.json()["fields"][0]["value"] == "Synthetic Person"


def test_scoped_agent_suggestions_require_active_facts_and_stay_unapproved(client, engine):
    approved = review_fact(client, fact(client, "experience", "Built synthetic systems in Python"))
    unapproved = fact(client, "experience", "Unreviewed achievement")
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    other_snapshot, _ = shared_page(client)
    other = prepare(client, other_snapshot)
    headers, run_id = running_agent(client, engine, preparation)
    context = client.get(
        f"/api/v1/browser/preparations/{preparation['id']}/context?limit=2", headers=headers
    )
    assert context.status_code == 200 and context.json()["next_offset"] == 2
    assert (
        client.get(
            f"/api/v1/browser/preparations/{other['id']}/context", headers=headers
        ).status_code
        == 403
    )
    path = f"browser/preparations/{preparation['id']}/suggestions"
    body = {
        "expected_version_id": preparation["version_id"],
        "answers": [
            {
                "field_id": "f1",
                "value": "I build synthetic Python systems.",
                "fact_revision_ids": [unapproved["current"]["id"]],
            }
        ],
    }
    assert post(client, path, body, headers=headers).status_code == 409
    body["answers"][0]["fact_revision_ids"] = [approved["active"]["id"]]
    saved = post(client, path, body, headers=headers)
    assert saved.status_code == 201, saved.text
    assert saved.json()["fields"][1]["evidence"][0]["revision_id"] == approved["active"]["id"]
    assert (
        post(
            client,
            f"browser/preparations/{preparation['id']}/revisions",
            {"expected_version_id": saved.json()["version_id"], "resume_version_id": None},
            headers=headers,
        ).status_code
        == 403
    )
    client.app.dependency_overrides[authenticate] = client.human_identity
    assert (
        post(
            client,
            "browser/commands",
            {
                "snapshot_id": snapshot["id"],
                "fields": {"f1": body["answers"][0]["value"]},
                "preparation_version_id": saved.json()["version_id"],
            },
        ).status_code
        == 409
    )
    with Session(engine) as db, db.begin():
        db.get(AgentRun, run_id).lease_expires_at = utc_now() - timedelta(seconds=1)
    client.app.dependency_overrides.pop(authenticate)
    body["expected_version_id"] = saved.json()["version_id"]
    assert post(client, path, body, headers=headers).status_code == 401


def test_agent_cannot_guess_sensitive_answers_or_overwrite_human_edits(client, engine):
    approved = review_fact(client, fact(client, "experience", "Built synthetic systems"))
    snapshot, _ = shared_page(client)
    preparation = revise(client, prepare(client, snapshot), fields={"f1": "My own answer"})
    headers, _ = running_agent(client, engine, preparation)
    path = f"browser/preparations/{preparation['id']}/suggestions"
    base = {
        "expected_version_id": preparation["version_id"],
        "answers": [
            {"field_id": "f3", "value": "Yes", "fact_revision_ids": [approved["active"]["id"]]}
        ],
    }
    assert post(client, path, base, headers=headers).status_code == 422
    base["answers"][0].update(field_id="f1", value="Overwritten by agent")
    assert post(client, path, base, headers=headers).status_code == 409
    base["answers"][0].update(field_id="f2", value="agent@example.test")
    assert post(client, path, base, headers=headers).status_code == 409
