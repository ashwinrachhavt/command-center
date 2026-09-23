"""Explicit next-page choices retain one owned application and immutable page packages."""

import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_application_context import job_description
from test_application_preparations import client as client
from test_application_preparations import opportunity, post, prepare, shared_page

from command_center.core.identity import Identity, authenticate
from command_center.db.application_preparations import ApplicationPreparation
from command_center.db.applications import ApplicationTrack
from command_center.db.artifacts import ArtifactVersion
from command_center.db.browser import BrowserSnapshot
from command_center.db.conversations import AgentSession
from command_center.db.idempotency import RequestReceipt
from command_center.db.models import Actor, AuditEvent, Task


def capture_page(client, snapshot, headers, page_url=None):
    body = {key: snapshot[key] for key in ("protocol_version", "page_url", "title", "fields")}
    body.update(id=str(uuid4()), page_url=page_url or snapshot["page_url"])
    response = post(client, "browser/snapshots", body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "page_url",
    ["https://jobs.example.test/apply/experience", "https://ats.example.test/application/2"],
)
def test_confirmed_page_keeps_application_context_and_immutable_packages(client, engine, page_url):
    snapshot, headers = shared_page(client)
    original = prepare(
        client, snapshot, opportunity_id=opportunity(client), job_context=job_description()
    )
    context_path = f"/api/v1/applications/{original['task_id']}/job-context"
    saved_context = client.get(context_path).json()
    conversation = post(client, "agent-sessions", {"task_id": original["task_id"]})
    assert conversation.status_code == 201, conversation.text
    with Session(engine) as db:
        original_payload = deepcopy(db.get(ArtifactVersion, UUID(original["version_id"])).payload)

    next_page = capture_page(client, snapshot, headers, page_url)
    continued = post(
        client,
        f"browser/device/snapshots/{next_page['id']}/preparations",
        {
            "continue_preparation_id": original["id"],
            "continue_on_new_page": True,
            "job_context": job_description(text="Page two instructions are not the original job."),
        },
        headers=headers,
    )
    assert continued.status_code == 201, continued.text
    latest = continued.json()
    assert latest["task_id"] == original["task_id"]
    assert latest["opportunity_id"] == original["opportunity_id"]
    assert latest["snapshot_id"] == next_page["id"]
    assert latest["artifact_id"] != original["artifact_id"]
    assert latest["version_id"] != original["version_id"]
    assert client.get(context_path).json() == saved_context
    reopened = post(client, "agent-sessions", {"task_id": latest["task_id"]})
    assert reopened.status_code == 201, reopened.text
    assert reopened.json()["id"] == conversation.json()["id"]
    applications = client.get("/api/v1/applications").json()
    assert applications["total"] == 1
    assert applications["items"][0]["preparation_count"] == 2
    assert applications["items"][0]["preparation_id"] == latest["id"]
    assert client.get(f"/api/v1/browser/preparations/{original['id']}").json() == original
    history = client.get(f"/api/v1/applications/{original['task_id']}/packages").json()
    packages = {item["id"]: item for item in history["items"]}
    assert history["total"] == 2
    assert packages[latest["id"]]["continued_from_preparation_id"] == original["id"]
    assert packages[latest["id"]]["continuation_mode"] == "confirmed_page"
    assert packages[original["id"]]["continued_from_preparation_id"] is None
    assert packages[original["id"]]["continuation_mode"] is None

    with Session(engine) as db:
        assert db.get(ArtifactVersion, UUID(original["version_id"])).payload == original_payload
        payload = db.get(ArtifactVersion, UUID(latest["version_id"])).payload
        assert payload["continued_from_preparation_id"] == original["id"]
        assert payload["continuation_mode"] == "confirmed_page"
        assert payload["snapshot_id"] == next_page["id"]
        assert (
            db.get(BrowserSnapshot, UUID(original["snapshot_id"])).page_url == snapshot["page_url"]
        )
        assert db.get(BrowserSnapshot, UUID(latest["snapshot_id"])).page_url == page_url
        for model in (Task, ApplicationTrack, AgentSession):
            assert (
                db.scalar(
                    select(func.count()).select_from(model).where(model.owner_id == client.actor_id)
                )
                == 1
            )
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_id == UUID(latest["id"]),
                AuditEvent.action == "application.prepared",
            )
        )
        assert event.details["continued_from_preparation_id"] == original["id"]
        assert event.details["continuation_mode"] == "confirmed_page"


@pytest.mark.parametrize("flag", [None, False])
def test_different_page_requires_explicit_confirmation(client, flag):
    snapshot, headers = shared_page(client)
    original = prepare(client, snapshot)
    next_page = capture_page(client, snapshot, headers, "https://jobs.example.test/apply/2")
    body = {"continue_preparation_id": original["id"]}
    if flag is not None:
        body["continue_on_new_page"] = flag
    response = post(client, f"browser/snapshots/{next_page['id']}/preparations", body)
    assert response.status_code == 409, response.text
    assert client.get("/api/v1/applications").json()["items"][0]["preparation_count"] == 1


@pytest.mark.parametrize("previous_id,status", [(None, 409), (str(uuid4()), 404)])
def test_confirmed_page_requires_an_existing_preparation(client, previous_id, status):
    snapshot, _ = shared_page(client)
    response = post(
        client,
        f"browser/snapshots/{snapshot['id']}/preparations",
        {"continue_preparation_id": previous_id, "continue_on_new_page": True},
    )
    assert response.status_code == status, response.text
    assert client.get("/api/v1/applications").json()["total"] == 0


def test_confirmed_page_cannot_switch_device_or_owner(client, engine):
    snapshot, _ = shared_page(client)
    original = prepare(client, snapshot)
    other_device, _ = shared_page(client)
    body = {"continue_preparation_id": original["id"], "continue_on_new_page": True}
    wrong_device = post(client, f"browser/snapshots/{other_device['id']}/preparations", body)
    assert wrong_device.status_code == 404, wrong_device.text

    other_owner = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other_owner, kind="human", display_name="Other synthetic applicant"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other_owner, "synthetic")
    foreign_page, _ = shared_page(client)
    wrong_owner = post(client, f"browser/snapshots/{foreign_page['id']}/preparations", body)
    assert wrong_owner.status_code == 404, wrong_owner.text
    assert client.get("/api/v1/applications").json()["total"] == 0


@pytest.mark.parametrize("state", ["done", "cancelled"])
def test_confirmed_page_cannot_reopen_finished_application(client, engine, state):
    snapshot, headers = shared_page(client)
    original = prepare(client, snapshot)
    next_page = capture_page(client, snapshot, headers, "https://jobs.example.test/apply/2")
    with Session(engine) as db, db.begin():
        task = db.get(Task, UUID(original["task_id"]))
        if state == "done":
            task.complete(actor_id=client.actor_id, request_id=uuid4())
        else:
            task.state = state
    response = post(
        client,
        f"browser/snapshots/{next_page['id']}/preparations",
        {"continue_preparation_id": original["id"], "continue_on_new_page": True},
    )
    assert response.status_code == 409, response.text
    assert "no longer active" in response.json()["detail"]


def test_confirmed_page_cannot_change_opportunity(client):
    snapshot, headers = shared_page(client)
    original = prepare(client, snapshot, opportunity_id=opportunity(client))
    next_page = capture_page(client, snapshot, headers, "https://jobs.example.test/apply/2")
    response = post(
        client,
        f"browser/snapshots/{next_page['id']}/preparations",
        {
            "continue_preparation_id": original["id"],
            "continue_on_new_page": True,
            "opportunity_id": opportunity(client),
        },
    )
    assert response.status_code == 409, response.text
    assert "same opportunity" in response.json()["detail"]


def test_confirmed_page_retry_is_stable_and_changed_choice_conflicts(client, engine):
    snapshot, headers = shared_page(client)
    original = prepare(client, snapshot)
    next_page = capture_page(client, snapshot, headers, "https://jobs.example.test/apply/2")
    path = f"browser/device/snapshots/{next_page['id']}/preparations"
    body = {"continue_preparation_id": original["id"], "continue_on_new_page": True}
    key = uuid4()
    created = post(client, path, body, key=key, headers=headers)
    assert created.status_code == 201, created.text
    replay = post(client, path, body, key=key, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json() == created.json()
    changed = post(client, path, {**body, "continue_on_new_page": False}, key=key, headers=headers)
    assert changed.status_code == 409, changed.text
    assert changed.json()["detail"] == (
        "This request conflicts with an earlier change. Refresh before trying again."
    )
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationPreparation)
                .where(ApplicationPreparation.owner_id == client.actor_id)
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.subject_id == UUID(created.json()["id"]),
                    AuditEvent.action == "application.prepared",
                )
            )
            == 1
        )


def test_same_page_legacy_request_hash_and_false_retry_are_preserved(client, engine):
    snapshot, headers = shared_page(client)
    original = prepare(client, snapshot)
    recaptured = capture_page(client, snapshot, headers)
    path = f"browser/device/snapshots/{recaptured['id']}/preparations"
    legacy_body = {
        "opportunity_id": None,
        "resume_version_id": None,
        "continue_preparation_id": original["id"],
        "job_context": None,
    }
    key = uuid4()
    created = post(client, path, legacy_body, key=key, headers=headers)
    assert created.status_code == 201, created.text
    replay = post(
        client,
        path,
        {**legacy_body, "continue_on_new_page": False},
        key=key,
        headers=headers,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json() == created.json()
    assert created.json()["task_id"] == original["task_id"]
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
        payload = db.get(ArtifactVersion, UUID(created.json()["version_id"])).payload
        assert payload["continued_from_preparation_id"] == original["id"]
        assert payload["continuation_mode"] == "same_page"
