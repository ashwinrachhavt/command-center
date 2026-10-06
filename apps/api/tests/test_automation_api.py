"""Device-facing automation endpoints: poll, claim, evidence, result."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.models import Actor
from command_center.main import create_app


@pytest.fixture
def client(settings, engine, tmp_path):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic automation api owner"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def human_post(client, path: str, body: dict) -> dict:
    return client.post(
        "/api/v1/" + path,
        json=body,
        headers={"Idempotency-Key": str(uuid4())},
    ).json()


def pair(client) -> dict[str, str]:
    pairing = human_post(client, "browser/pairings", {"name": "Synthetic device"})
    exchange = client.post("/api/v1/browser/pairings/exchange", json={"code": pairing["code"]})
    assert exchange.status_code == 200, exchange.text
    return {
        "device_id": exchange.json()["device_id"],
        "Authorization": "Bearer " + exchange.json()["token"],
    }


GREENHOUSE_CSV = (
    "company,job_title,job_url\n"
    "Acme,Engineer,https://boards.greenhouse.io/acme/jobs/123\n"
)


def seed_application(client) -> str:
    upload = client.post(
        "/api/v1/applications-automation/csv",
        files={"file": ("applications.csv", GREENHOUSE_CSV.encode(), "text/csv")},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert upload.status_code == 201, upload.text
    rows = client.get("/api/v1/applications-automation/applications").json()["items"]
    return rows[0]["id"]


def test_poll_claims_queued_run_with_token(client):
    device = pair(client)
    application_id = seed_application(client)
    queued = human_post(
        client, f"applications-automation/applications/{application_id}/runs", {"mode": "fill_only"}
    )
    assert queued["state"] == "queued"
    poll = client.get(
        "/api/v1/browser/device/automation/commands", headers=device
    )
    assert poll.status_code == 200, poll.text
    commands = poll.json()
    assert len(commands) == 1
    command = commands[0]
    assert command["run_id"] == queued["id"]
    assert command["application"]["job_url"] == "https://boards.greenhouse.io/acme/jobs/123"
    assert command["adapter"]["platform"] == "greenhouse"
    assert command["adapter"]["steps"][0]["kind"] == "identity"


def test_poll_is_empty_without_queued_runs(client):
    device = pair(client)
    poll = client.get("/api/v1/browser/device/automation/commands", headers=device)
    assert poll.status_code == 200
    assert poll.json() == []


def test_result_completes_run_and_updates_application(client):
    device = pair(client)
    application_id = seed_application(client)
    human_post(
        client,
        f"applications-automation/applications/{application_id}/runs",
        {"mode": "fill_only"},
    )
    command = client.get("/api/v1/browser/device/automation/commands", headers=device).json()[0]
    result = client.post(
        f"/api/v1/browser/device/automation/commands/{command['run_id']}/result",
        headers=device,
        json={
            "run_token": command["run_token"],
            "state": "completed",
            "detail": "Adapter steps finished; the application is ready for review.",
            "field_evidence": {
                "f001": {
                    "status": "filled",
                    "selector": "input#first_name",
                    "matched_label": "First name",
                    "detail": "Value applied.",
                }
            },
            "page_evidence": {"f001": {"present": True, "has_value": True}},
            "simplify_step": {
                "form_detected": False,
                "clicked": False,
                "settled": False,
                "validated_required": True,
                "missing_fields": [],
            },
        },
    )
    assert result.status_code == 200, result.text
    detail = client.get(
        f"/api/v1/applications-automation/applications/{application_id}"
    ).json()
    assert detail["status"] == "ready_for_review"
    assert detail["submit_authorized_at"] is None


def test_result_rejects_wrong_token(client):
    device = pair(client)
    application_id = seed_application(client)
    human_post(
        client,
        f"applications-automation/applications/{application_id}/runs",
        {"mode": "fill_only"},
    )
    command = client.get("/api/v1/browser/device/automation/commands", headers=device).json()[0]
    result = client.post(
        f"/api/v1/browser/device/automation/commands/{command['run_id']}/result",
        headers=device,
        json={
            "run_token": "0" * 32,
            "state": "completed",
            "detail": "",
            "field_evidence": {},
        },
    )
    assert result.status_code == 409


def test_submit_run_requires_authorization_endpoint(client):
    pair(client)
    application_id = seed_application(client)
    denied = client.post(
        "/api/v1/" + f"applications-automation/applications/{application_id}/runs",
        json={"mode": "submit"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code == 409, denied.text
    authorized = client.post(
        "/api/v1/" + f"applications-automation/applications/{application_id}/authorization",
        json={},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert authorized.status_code == 201, authorized.text
    allowed = client.post(
        "/api/v1/" + f"applications-automation/applications/{application_id}/runs",
        json={"mode": "submit"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert allowed.status_code == 201, allowed.text


def test_unsupported_platform_run_is_422(client):
    pair(client)
    upload = client.post(
        "/api/v1/applications-automation/csv",
        files={
            "file": (
                "applications.csv",
                b"company,job_title,job_url\nAcme,Engineer,https://careers.acme.example/roles/1\n",
                "text/csv",
            )
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert upload.status_code == 201
    rows = client.get("/api/v1/applications-automation/applications").json()["items"]
    denied = client.post(
        "/api/v1/" + f"applications-automation/applications/{rows[0]['id']}/runs",
        json={"mode": "fill_only"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code == 422


def test_evidence_persists_mid_run(client):
    device = pair(client)
    application_id = seed_application(client)
    human_post(
        client,
        f"applications-automation/applications/{application_id}/runs",
        {"mode": "fill_only"},
    )
    command = client.get("/api/v1/browser/device/automation/commands", headers=device).json()[0]
    evidence = client.post(
        f"/api/v1/browser/device/automation/commands/{command['run_id']}/evidence",
        headers=device,
        json={
            "run_token": command["run_token"],
            "field_evidence": {
                "f001": {
                    "status": "filled",
                    "selector": "input#first_name",
                    "matched_label": "First name",
                    "detail": "Value applied.",
                }
            },
        },
    )
    assert evidence.status_code == 200, evidence.text
