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


def test_history_autofill_pins_each_entry_and_revocation_blocks_claim(client):
    from command_center.db.career import CareerEntry

    recent = review_fact(
        client,
        fact(
            client,
            "experience",
            CareerEntry(
                kind="experience",
                organization="Synthetic Recent",
                role="Engineer",
                start_date="2020-09",
            ).encode(),
        ),
    )
    review_fact(
        client,
        fact(
            client,
            "experience",
            CareerEntry(
                kind="experience",
                organization="Synthetic Earlier",
                role="Analyst",
                start_date="2015",
            ).encode(),
        ),
    )
    fields = []
    for group in range(2):
        for component in ("organization", "role", "start_year"):
            fields.append(
                {
                    "id": f"f{len(fields)}",
                    "label": component,
                    "type": "text",
                    "value_state": "empty",
                    "history": {
                        "group_id": f"h{group}",
                        "kind": "experience",
                        "position": group,
                        "label": f"Work experience {group + 1}",
                        "component": component,
                    },
                }
            )
    snapshot, headers = shared_page(client, fields)
    preparation = prepare(client, snapshot)
    automatic = post(
        client,
        f"browser/device/preparations/{preparation['id']}/autofill",
        {
            "expected_version_id": preparation["version_id"],
            "attach_resume": False,
        },
        headers=headers,
    )
    assert automatic.status_code == 201, automatic.text
    result = automatic.json()
    values = {item["field_id"]: item["value"] for item in result["fields"]}
    assert list(values.values()) == [
        "Synthetic Recent",
        "Engineer",
        "2020",
        "Synthetic Earlier",
        "Analyst",
        "2015",
    ]
    proposed = post(
        client,
        "browser/device/commands",
        {
            "snapshot_id": snapshot["id"],
            "fields": values,
            "preparation_version_id": result["version_id"],
        },
        headers=headers,
    )
    assert proposed.status_code == 201, proposed.text
    review_fact(client, recent, "revoked")
    assert (
        client.post(
            f"/api/v1/browser/device/commands/{proposed.json()['id']}/claim", headers=headers
        ).status_code
        == 409
    )


def test_one_click_autofill_uses_only_active_facts_and_exact_resume(client, engine):
    from command_center.db.artifacts import ArtifactReview
    from command_center.db.models import AuditEvent

    approved = review_fact(client, fact(client))
    fact(client, "phone", "1234567890")  # Unreviewed data must not become an answer.
    snapshot, headers = shared_page(client)
    original_fields = snapshot["fields"]
    original_fields.extend(
        [
            {"id": "f5", "label": "Cover letter", "type": "file", "value_state": "empty"},
            {
                "id": "f6",
                "label": "Resume or supporting documents",
                "type": "file",
                "value_state": "empty",
            },
            {"id": "f7", "label": "Phone", "type": "tel", "value_state": "empty"},
        ]
    )
    snapshot, headers = shared_page(client, fields=original_fields)
    resume_id = upload_resume(client)
    preparation = prepare(client, snapshot, resume_version_id=resume_id)
    key = uuid4()
    path = f"browser/device/preparations/{preparation['id']}/autofill"
    body = {"expected_version_id": preparation["version_id"], "attach_resume": True}
    filled = post(client, path, body, key=key, headers=headers)
    assert filled.status_code == 201, filled.text
    result = filled.json()
    assert post(client, path, body, key=key, headers=headers).json() == result
    assert result["upload_fields"] == ["f4"]
    assert result["replace_fields"] == []
    fields = {row["field_id"]: row for row in result["fields"]}
    assert fields["f0"]["value"] == "Synthetic Person"
    assert fields["f0"]["evidence"][0]["revision_id"] == approved["current"]["id"]
    assert fields["f2"]["status"] == "preserved"
    assert fields["f3"]["status"] == "needs_input"
    assert fields["f7"]["value"] is None
    command = post(
        client,
        "browser/device/commands",
        {
            "snapshot_id": snapshot["id"],
            "fields": {"f0": "Synthetic Person"},
            "uploads": {"f4": resume_id},
            "preparation_version_id": result["version_id"],
        },
        headers=headers,
    )
    assert command.status_code == 201, command.text
    with Session(engine) as db:
        review = db.scalar(
            select(ArtifactReview).where(ArtifactReview.artifact_version_id == result["version_id"])
        )
        assert review and "Requested autofill" in review.reason
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.subject_id == preparation["id"],
                    AuditEvent.action == "application.autofill_requested",
                )
            )
            == 1
        )
    _, other_device = shared_page(client)
    assert post(client, path, body, headers=other_device).status_code == 404


def test_tracker_groups_captures_and_reopens_snapshots_outside_recent_window(client):
    snapshot, headers = shared_page(client)
    first = prepare(client, snapshot)
    body = {key: snapshot[key] for key in ("protocol_version", "page_url", "title", "fields")}
    body["id"] = str(uuid4())
    fresh = post(client, "browser/snapshots", body, headers=headers).json()
    latest = prepare(client, fresh, continue_preparation_id=first["id"])
    for _ in range(21):
        body["id"] = str(uuid4())
        assert post(client, "browser/snapshots", body, headers=headers).status_code == 201
    recent = client.get("/api/v1/browser/snapshots").json()
    assert snapshot["id"] not in {row["id"] for row in recent}
    result = client.get("/api/v1/applications?q=synthetic&status=preparing&limit=1")
    assert result.status_code == 200, result.text
    page = result.json()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["task"]["id"] == first["task_id"]
    assert item["preparation_count"] == 2
    assert item["preparation_id"] == latest["id"]
    assert item["status"] == "preparing" and item["submission_recorded_at"] is None
    assert "fields" not in item
    assert client.get("/api/v1/applications?status=submitted").json()["total"] == 0
    history = client.get(f"/api/v1/applications/{first['task_id']}/packages?limit=1&offset=1")
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 2
    assert history.json()["items"][0]["id"] == first["id"]
    assert "fields" not in history.json()["items"][0]
    old = client.get(f"/api/v1/browser/snapshots/{snapshot['id']}")
    assert old.status_code == 200 and old.json()["id"] == snapshot["id"]
    restored = client.get(f"/api/v1/browser/snapshots/{snapshot['id']}/preparation")
    assert restored.status_code == 200 and restored.json()["version_id"] == first["version_id"]


def test_application_status_is_explicit_versioned_and_retry_safe(client, engine):
    from command_center.db.models import AuditEvent

    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    path = f"/api/v1/applications/{preparation['task_id']}"
    key = str(uuid4())
    body = {"expected_version": 1, "status": "submitted"}
    saved = client.patch(path, json=body, headers={"Idempotency-Key": key})
    assert saved.status_code == 200, saved.text
    assert saved.json()["submission_recorded_at"] is not None
    # Reporting a hiring outcome is separate from completing the preparation task.
    assert saved.json()["task"]["state"] == "open"
    assert client.patch(path, json=body, headers={"Idempotency-Key": key}).json() == saved.json()
    stale = client.patch(
        path, json={**body, "status": "offer"}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert stale.status_code == 409
    interview = client.patch(
        path,
        json={"expected_version": 2, "status": "interviewing"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert interview.status_code == 200, interview.text
    assert interview.json()["submission_recorded_at"] == saved.json()["submission_recorded_at"]
    corrected = client.patch(
        path,
        json={"expected_version": 3, "status": "preparing"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["submission_recorded_at"] is None
    with Session(engine) as db:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.actor_id == client.actor_id,
                    AuditEvent.action == "application.status_recorded",
                )
            )
        )
        assert len(events) == 3
        assert all(event.details["source"] == "human_report" for event in events)


def test_application_packages_pin_answers_resume_and_fill_evidence(client):
    snapshot, headers = shared_page(client)
    resume_id = upload_resume(client)
    preparation = prepare(client, snapshot, resume_version_id=resume_id)
    first = revise(client, preparation, fields={"f0": "Synthetic answer one"})
    command = post(
        client,
        "browser/device/commands",
        {
            "snapshot_id": snapshot["id"],
            "fields": {"f0": "Synthetic answer one"},
            "preparation_version_id": first["version_id"],
        },
        headers=headers,
    )
    assert command.status_code == 201, command.text
    revised = revise(client, first, fields={"f0": "Synthetic answer two"})
    path = f"/api/v1/applications/{preparation['task_id']}"
    history = client.get(path + "/packages")
    assert history.status_code == 200, history.text
    item = history.json()["items"][0]
    assert item["version_id"] == revised["version_id"]
    assert item["resume"]["version_id"] == resume_id
    assert item["resume_artifact_id"] is not None
    assert item["latest_fill"]["preparation_version_id"] == first["version_id"]
    assert item["latest_fill"]["state"] == "pending"
    assert "fields" not in item["latest_fill"]
    old = client.get(path + f"/packages/{preparation['id']}/versions/{first['version_id']}")
    assert old.status_code == 200, old.text
    assert old.json()["fields"][0]["value"] == "Synthetic answer one"
    mismatch = client.get(path + f"/packages/{preparation['id']}/versions/{resume_id}")
    assert mismatch.status_code == 404
    assert client.get(path).json()["status"] == "preparing"


def test_application_tracker_enforces_owner_and_human_scope(client, engine):
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    path = f"/api/v1/applications/{preparation['task_id']}"
    other = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other, kind="human", display_name="Other synthetic applicant"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other, "synthetic")
    assert client.get("/api/v1/applications").json()["total"] == 0
    for target in (
        path,
        path + "/packages",
        path + f"/packages/{preparation['id']}/versions/{preparation['version_id']}",
        f"/api/v1/browser/snapshots/{snapshot['id']}",
        f"/api/v1/browser/snapshots/{snapshot['id']}/preparation",
    ):
        assert client.get(target).status_code == 404
    assert (
        client.patch(
            path,
            json={"expected_version": 1, "status": "submitted"},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 404
    )
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic", run_id=uuid4()
    )
    assert client.get("/api/v1/applications").status_code == 403
    assert (
        client.patch(
            path,
            json={"expected_version": 1, "status": "submitted"},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 403
    )


def test_tracking_migration_backfills_preparing_and_preserves_reported_outcomes(
    client,
    engine,
    migration_config,
):
    from alembic import command
    from test_migrations import clear_question_fixtures

    clear_question_fixtures(engine)
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    task_id = preparation["task_id"]
    completed = client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"expected_version": 1, "state": "done"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert completed.status_code == 200, completed.text
    command.downgrade(migration_config, "0023_application_profile")
    command.upgrade(migration_config, "head")
    path = f"/api/v1/applications/{task_id}"
    restored = client.get(path)
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "preparing"
    assert restored.json()["task"]["state"] == "done"
    assert (
        client.patch(
            path,
            json={"expected_version": 1, "status": "submitted"},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 200
    )
    with pytest.raises(RuntimeError, match="refusing to discard recorded outcomes"):
        command.downgrade(migration_config, "0023_application_profile")
    assert client.get(path).json()["status"] == "submitted"
    assert (
        client.patch(
            path,
            json={"expected_version": 2, "status": "preparing"},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 200
    )


def test_autofill_rechecks_revoked_facts_and_does_not_approve_missing_answers(client, engine):
    from command_center.db.artifacts import ArtifactReview

    active = review_fact(client, fact(client))
    snapshot, headers = shared_page(client)
    preparation = prepare(client, snapshot)
    review_fact(client, active, "revoked")
    filled = post(
        client,
        f"browser/device/preparations/{preparation['id']}/autofill",
        {
            "expected_version_id": preparation["version_id"],
            "attach_resume": False,
        },
        headers=headers,
    )
    assert filled.status_code == 201, filled.text
    result = filled.json()
    assert all(row["value"] is None for row in result["fields"])
    assert result["upload_fields"] == []
    with Session(engine) as db:
        assert (
            db.scalar(
                select(ArtifactReview).where(
                    ArtifactReview.artifact_version_id == result["version_id"]
                )
            )
            is None
        )
    stale = post(
        client,
        f"browser/device/preparations/{preparation['id']}/autofill",
        {
            "expected_version_id": preparation["version_id"],
            "attach_resume": False,
        },
        headers=headers,
    )
    assert stale.status_code == 409


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


def test_application_identity_fields_are_exact_and_dropdown_labels_match(client):
    for key, value in [
        ("first_name", "Synthetic"),
        ("last_name", "Applicant"),
        ("city", "Example City"),
        ("country", "United States"),
    ]:
        review_fact(client, fact(client, key, value))
    fields = [
        {"id": "f0", "label": "First name *", "type": "text", "value_state": "empty"},
        {
            "id": "f1",
            "label": "Your surname",
            "autocomplete": "family-name",
            "type": "text",
            "value_state": "empty",
        },
        {"id": "f2", "label": "City", "type": "text", "value_state": "empty"},
        {
            "id": "f3",
            "label": "Country",
            "type": "select",
            "options": ["US", "CA"],
            "option_labels": {"US": "United States", "CA": "Canada"},
            "value_state": "empty",
        },
        {
            "id": "f4",
            "label": "Citizenship",
            "autocomplete": "country",
            "type": "text",
            "value_state": "empty",
        },
    ]
    snapshot, headers = shared_page(client, fields)
    preparation = prepare(client, snapshot)
    response = post(
        client,
        f"browser/device/preparations/{preparation['id']}/autofill",
        {"expected_version_id": preparation["version_id"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert [field["value"] for field in response.json()["fields"]] == [
        "Synthetic",
        "Applicant",
        "Example City",
        "US",
        None,
    ]
    # A second current scalar is rejected; no ambiguous automatic choice.
    conflicting = fact(client, "first_name", "Different")
    conflict = post(
        client,
        f"profile/facts/{conflicting['id']}/reviews",
        {
            "expected_version": conflicting["row_version"],
            "revision_id": conflicting["current"]["id"],
            "decision": "approved",
        },
    )
    assert conflict.status_code == 409


def test_recapture_reuses_task_but_requires_same_device_and_page(client, engine):
    snapshot, headers = shared_page(client)
    preparation = prepare(client, snapshot)
    body = {key: snapshot[key] for key in ("protocol_version", "page_url", "title", "fields")}
    body["id"] = str(uuid4())
    fresh = post(client, "browser/snapshots", body, headers=headers).json()
    continued = prepare(client, fresh, continue_preparation_id=preparation["id"])
    assert continued["task_id"] == preparation["task_id"]
    assert continued["artifact_id"] != preparation["artifact_id"]
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Task).where(Task.owner_id == client.actor_id)
            )
            == 1
        )
    other, _ = shared_page(client)
    wrong_device = post(
        client,
        f"browser/snapshots/{other['id']}/preparations",
        {
            "continue_preparation_id": preparation["id"],
        },
    )
    assert wrong_device.status_code == 404
    body.update(id=str(uuid4()), page_url="https://jobs.example.test/different-role")
    changed = post(client, "browser/snapshots", body, headers=headers).json()
    wrong_page = post(
        client,
        f"browser/snapshots/{changed['id']}/preparations",
        {
            "continue_preparation_id": preparation["id"],
        },
    )
    assert wrong_page.status_code == 409


def test_autofill_skips_incompatible_resume_control_and_still_fills_answers(client):
    review_fact(client, fact(client))
    resume_id = upload_resume(client)
    snapshot, headers = shared_page(
        client,
        fields=[
            {"id": "f0", "label": "Full name", "type": "text", "value_state": "empty"},
            {
                "id": "f1",
                "label": "Resume PDF",
                "type": "file",
                "accept": ".pdf",
                "value_state": "empty",
            },
        ],
    )
    preparation = prepare(client, snapshot, resume_version_id=resume_id)
    response = post(
        client,
        f"browser/device/preparations/{preparation['id']}/autofill",
        {"expected_version_id": preparation["version_id"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["upload_fields"] == []
    assert saved["fields"][0]["value"] == "Synthetic Person"
    command = post(
        client,
        "browser/device/commands",
        {
            "snapshot_id": snapshot["id"],
            "fields": {"f0": "Synthetic Person"},
            "preparation_version_id": saved["version_id"],
        },
        headers=headers,
    )
    assert command.status_code == 201, command.text


def upload_cover_letter(client, content=b"Synthetic exact cover letter"):
    letter_type = next(
        item
        for item in client.get("/api/v1/document-types").json()
        if item["slug"] == "cover-letter"
    )
    uploaded = client.post(
        "/api/v1/documents/imports",
        data={"title": "Synthetic cover letter", "document_type_id": letter_type["id"]},
        files={"file": ("cover-letter.txt", content, "text/plain")},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert uploaded.status_code == 202, uploaded.text
    return uploaded.json()["source_version_id"]


def test_cover_letter_autofill_pins_each_file_and_preserves_manual_and_ambiguous_fields(client):
    labels = [
        "Resume",
        "Cover letter",
        "Resume or cover letter",
        "Cover letter and supporting documents",
        "Cover letter PDF",
        "Covering letter already attached",
    ]
    fields = [
        {
            "id": f"f{i}",
            "label": label,
            "type": "file",
            "accept": ".pdf" if i == 4 else "text/plain",
            "value_state": "present" if i == 5 else "empty",
        }
        for i, label in enumerate(labels)
    ]
    snapshot, headers = shared_page(client, fields)
    resume_id = upload_resume(client)
    letter_id = upload_cover_letter(client)
    other_letter = upload_cover_letter(client, b"Another letter")
    preparation = prepare(
        client, snapshot, resume_version_id=resume_id, cover_letter_version_id=letter_id
    )
    listed = client.get("/api/v1/browser/device/cover-letters", headers=headers).json()
    assert listed["default_version_id"] is None
    assert {row["version_id"] for row in listed["items"]} == {letter_id, other_letter}
    assert resume_id not in {row["version_id"] for row in listed["items"]}
    key = uuid4()
    body = {
        "expected_version_id": preparation["version_id"],
        "attach_resume": True,
        "attach_cover_letter": True,
    }
    path = f"browser/device/preparations/{preparation['id']}/autofill"
    response = post(client, path, body, key=key, headers=headers)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert post(client, path, body, key=key, headers=headers).json() == saved
    assert saved["upload_fields"] == ["f0"]
    assert saved["cover_letter_upload_fields"] == ["f1"]
    assert saved["cover_letter"]["version_id"] == letter_id
    command_body = {
        "snapshot_id": snapshot["id"],
        "fields": {},
        "uploads": {"f0": resume_id, "f1": letter_id},
        "preparation_version_id": saved["version_id"],
    }
    for uploads in ({"f0": letter_id}, {"f1": resume_id}, {"f1": other_letter}, {"f2": letter_id}):
        rejected = post(
            client, "browser/device/commands", {**command_body, "uploads": uploads}, headers=headers
        )
        assert rejected.status_code == 409, rejected.text
    response = post(client, "browser/device/commands", command_body, headers=headers)
    assert response.status_code == 201, response.text
    command = response.json()
    assert command["upload_files"]["f0"]["version_id"] == resume_id
    assert command["upload_files"]["f1"]["version_id"] == letter_id
    claim_path = f"/api/v1/browser/device/commands/{command['id']}"
    claimed = client.post(claim_path + "/claim", headers=headers)
    assert claimed.status_code == 200, claimed.text
    assert (
        client.get(claim_path + "/files/f0", headers=headers).content == b"Synthetic exact resume"
    )
    assert (
        client.get(claim_path + "/files/f1", headers=headers).content
        == b"Synthetic exact cover letter"
    )
    packages = client.get(f"/api/v1/applications/{preparation['task_id']}/packages").json()["items"]
    assert packages[0]["cover_letter"]["version_id"] == letter_id
    assert packages[0]["cover_letter_artifact_id"] is not None


def test_cover_letter_selection_requires_correct_type_and_explicit_autofill(client):
    snapshot, headers = shared_page(
        client, [{"id": "f0", "type": "file", "label": "Cover letter", "value_state": "empty"}]
    )
    resume_id = upload_resume(client)
    rejected = post(
        client,
        f"browser/snapshots/{snapshot['id']}/preparations",
        {"cover_letter_version_id": resume_id},
    )
    assert rejected.status_code == 409, rejected.text
    letter_id = upload_cover_letter(client)
    preparation = prepare(client, snapshot, cover_letter_version_id=letter_id)
    response = post(
        client,
        f"browser/device/preparations/{preparation['id']}/autofill",
        {"expected_version_id": preparation["version_id"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["cover_letter_upload_fields"] == []
    # The generic unbound upload path must not accept a cover letter as a résumé.
    rejected = post(
        client,
        "browser/device/commands",
        {"snapshot_id": snapshot["id"], "uploads": {"f0": letter_id}, "fields": {}},
        headers=headers,
    )
    assert rejected.status_code == 409, rejected.text


def test_reviewed_cover_letter_replacement_rechecks_availability_at_claim(client, engine):
    from command_center.db.artifacts import Artifact

    snapshot, headers = shared_page(
        client,
        [{"id": "f0", "type": "file", "label": "Supporting document", "value_state": "present"}],
    )
    letter_id = upload_cover_letter(client)
    preparation = prepare(client, snapshot, cover_letter_version_id=letter_id)
    body = {
        "expected_version_id": preparation["version_id"],
        "resume_version_id": None,
        "cover_letter_version_id": letter_id,
        "cover_letter_upload_fields": ["f0"],
    }
    path = f"browser/preparations/{preparation['id']}/revisions"
    assert post(client, path, body).status_code == 422
    overlap = post(client, path, {**body, "replace_fields": ["f0"], "upload_fields": ["f0"]})
    assert overlap.status_code == 422
    saved = post(client, path, {**body, "replace_fields": ["f0"]})
    assert saved.status_code == 201, saved.text
    response = post(
        client,
        "browser/device/commands",
        {
            "snapshot_id": snapshot["id"],
            "fields": {},
            "uploads": {"f0": letter_id},
            "replace_fields": ["f0"],
            "preparation_version_id": saved.json()["version_id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    with Session(engine) as db, db.begin():
        version = db.get(ArtifactVersion, UUID(letter_id))
        db.get(Artifact, version.artifact_id).archived_at = utc_now()
    claim = client.post(
        f"/api/v1/browser/device/commands/{response.json()['id']}/claim", headers=headers
    )
    assert claim.status_code == 409, claim.text


def test_new_optional_file_choices_preserve_pre_upgrade_receipt_hashes(client, engine):
    import hashlib
    import json

    from command_center.db.idempotency import RequestReceipt

    snapshot, headers = shared_page(client)
    key = uuid4()
    legacy_body = {
        "opportunity_id": None,
        "resume_version_id": None,
        "continue_preparation_id": None,
        "job_context": None,
    }
    path = f"browser/device/snapshots/{snapshot['id']}/preparations"
    created = post(client, path, legacy_body, key=key, headers=headers)
    assert created.status_code == 201, created.text
    with Session(engine) as db:
        receipt = db.scalar(
            select(RequestReceipt).where(
                RequestReceipt.actor_id == client.actor_id, RequestReceipt.key == key
            )
        )
        assert (
            receipt.request_hash
            == hashlib.sha256(
                json.dumps(legacy_body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
    replay = post(
        client, path, {**legacy_body, "cover_letter_version_id": None}, key=key, headers=headers
    )
    assert replay.json() == created.json()
    auto_key = uuid4()
    auto_path = f"browser/device/preparations/{created.json()['id']}/autofill"
    legacy_auto = {"expected_version_id": created.json()["version_id"], "attach_resume": False}
    saved = post(client, auto_path, legacy_auto, key=auto_key, headers=headers)
    assert saved.status_code == 201, saved.text
    with Session(engine) as db:
        receipt = db.scalar(
            select(RequestReceipt).where(
                RequestReceipt.actor_id == client.actor_id, RequestReceipt.key == auto_key
            )
        )
        assert (
            receipt.request_hash
            == hashlib.sha256(
                json.dumps(legacy_auto, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
    assert (
        post(
            client,
            auto_path,
            {**legacy_auto, "attach_cover_letter": False},
            key=auto_key,
            headers=headers,
        ).json()
        == saved.json()
    )
    letter_id = upload_cover_letter(client)
    different = post(
        client,
        path,
        {**legacy_body, "cover_letter_version_id": letter_id},
        key=key,
        headers=headers,
    )
    assert different.status_code == 409, different.text
