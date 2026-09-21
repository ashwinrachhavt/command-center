"""Real PostgreSQL requests with synthetic identities; no provider calls."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.models import Actor, AuditEvent
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic tester"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def post(client, path, body, key=None):
    return client.post(
        "/api/v1/" + path, json=body, headers={"Idempotency-Key": str(key or uuid4())}
    )


def patch(client, path, body):
    return client.patch("/api/v1/" + path, json=body, headers={"Idempotency-Key": str(uuid4())})


def test_idempotent_create_rejects_key_reuse_and_stale_edits(client, engine):
    key = uuid4()
    first = post(client, "companies", {"name": "Synthetic Orbit"}, key)
    assert first.status_code == 201, first.text
    record = first.json()
    assert post(client, "companies", {"name": "Synthetic Orbit"}, key).json() == record
    assert post(client, "companies", {"name": "Changed"}, key).status_code == 409
    changed = patch(
        client,
        "companies/" + record["id"],
        {"name": "New name", "expected_version": record["row_version"]},
    )
    assert changed.status_code == 200, changed.text
    stale = patch(
        client,
        "companies/" + record["id"],
        {"name": "Stale", "expected_version": record["row_version"]},
    )
    assert stale.status_code == 409
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.subject_id == record["id"], AuditEvent.action == "companies.created"
                )
            )
            == 1
        )


def test_owner_isolation_and_cross_owner_links(client, engine):
    company = post(client, "companies", {"name": "Private synthetic company"}).json()
    stranger_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=stranger_id, kind="human", display_name="Other synthetic tester"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(stranger_id, "other")
    assert client.get("/api/v1/companies/" + company["id"]).status_code == 404
    assert client.get("/api/v1/companies").json()["total"] == 0
    assert (
        post(client, "contacts", {"name": "Test", "company_id": company["id"]}).status_code == 404
    )


def test_company_labels_resolve_beyond_first_page_and_preserve_ownership(client, engine):
    from uuid import UUID

    from command_center.db.base import utc_now
    from command_center.db.crm import Company

    company = post(client, "companies", {"name": "Synthetic oldest company"}).json()
    other = uuid4()
    private_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other, kind="human", display_name="Other synthetic actor"))
        db.flush()
        db.add(Company(id=private_id, owner_id=other, name="Private synthetic company"))
        db.add_all(
            Company(owner_id=client.actor_id, name=f"Synthetic newer {i}") for i in range(100)
        )
    page = client.get("/api/v1/companies?limit=100").json()
    assert company["id"] not in {row["id"] for row in page["items"]}
    response = client.get(
        "/api/v1/company-labels", params=[("ids", company["id"]), ("ids", str(private_id))]
    )
    assert response.status_code == 200
    assert response.json() == [{"id": company["id"], "name": company["name"]}]
    assert client.get("/api/v1/company-labels").json() == []
    assert client.get("/api/v1/company-labels?ids=invalid").status_code == 422
    assert (
        client.get("/api/v1/company-labels", params=[("ids", company["id"])] * 101).status_code
        == 422
    )
    with Session(engine) as db, db.begin():
        db.get(Company, UUID(company["id"])).archived_at = utc_now()
    assert client.get("/api/v1/company-labels", params={"ids": company["id"]}).json() == []


def test_task_completion_and_artifact_reviews(client):
    task = post(client, "tasks", {"title": "Review synthetic role"}).json()
    done = patch(
        client, "tasks/" + task["id"], {"state": "done", "expected_version": task["row_version"]}
    )
    assert done.status_code == 200, done.text
    assert done.json()["completed_at"]
    artifact_response = post(
        client,
        "artifacts",
        {"title": "Synthetic research", "kind": "research", "text": "First draft"},
    )
    assert artifact_response.status_code == 201, artifact_response.text
    artifact = artifact_response.json()
    version = client.get(f"/api/v1/artifacts/{artifact['id']}/versions").json()[0]
    review = post(
        client,
        f"versions/{version['id']}/reviews",
        {"decision": "approved", "reason": "Checked synthetic text"},
    )
    assert review.status_code == 201, review.text
    newer = post(
        client,
        f"artifacts/{artifact['id']}/versions",
        {"text": "Second draft", "expected_version": artifact["row_version"]},
    )
    assert newer.status_code == 201, newer.text
    assert client.get(f"/api/v1/versions/{newer.json()['id']}/reviews").json() == []
    assert (
        post(
            client,
            "artifacts",
            {"title": "Invalid document", "kind": "document", "text": "No type"},
        ).status_code
        == 422
    )


def test_memory_revision_and_archive(client):
    note = post(
        client,
        "memories",
        {
            "title": "Work preference",
            "content": "Synthetic remote preference",
            "kind": "preference",
        },
    ).json()
    assert note["source"] == "human"
    response = patch(
        client,
        "memories/" + note["id"],
        {
            "title": note["title"],
            "content": "Updated preference",
            "kind": "preference",
            "expected_version": note["row_version"],
        },
    )
    assert response.status_code == 200, response.text
    archived = post(
        client,
        f"memories/{note['id']}/archive",
        {"expected_version": response.json()["row_version"]},
    )
    assert archived.status_code == 200, archived.text
    assert client.get("/api/v1/memories").json()["total"] == 0


def test_browser_pairing_single_use_and_fill_cannot_replay(client):
    pairing = post(client, "browser/pairings", {"name": "Synthetic browser"}).json()
    exchanged = client.post("/api/v1/browser/pairings/exchange", json={"code": pairing["code"]})
    assert exchanged.status_code == 200, exchanged.text
    assert (
        client.post("/api/v1/browser/pairings/exchange", json={"code": pairing["code"]}).status_code
        == 401
    )
    device_headers = {"Authorization": "Bearer " + exchanged.json()["token"]}
    snapshot = {
        "id": str(uuid4()),
        "page_url": "https://example.com/apply",
        "title": "Synthetic form",
        "fields": [{"id": "f0", "label": "Name", "type": "text"}],
    }
    captured = client.post("/api/v1/browser/snapshots", json=snapshot, headers=device_headers)
    assert captured.status_code == 201, captured.text
    assert (
        client.post("/api/v1/browser/snapshots", json=snapshot, headers=device_headers).json()
        == captured.json()
    )
    invalid = post(
        client, "browser/commands", {"snapshot_id": snapshot["id"], "fields": {"f99": "Bad field"}}
    )
    assert invalid.status_code == 422
    command = post(
        client,
        "browser/commands",
        {"snapshot_id": snapshot["id"], "fields": {"f0": "Synthetic person"}},
    ).json()
    path = f"/api/v1/browser/device/commands/{command['id']}"
    assert client.post(path + "/claim", headers=device_headers).status_code == 200
    assert client.post(path + "/claim", headers=device_headers).status_code == 409
    assert (
        client.post(path + "/result", json={"state": "applied"}, headers=device_headers).status_code
        == 200
    )
    assert (
        client.post(path + "/result", json={"state": "applied"}, headers=device_headers).status_code
        == 200
    )
    assert (
        client.post(path + "/result", json={"state": "failed"}, headers=device_headers).status_code
        == 409
    )
    assert post(client, f"browser/devices/{pairing['device_id']}/revoke", {}).status_code == 200
    assert client.get("/api/v1/browser/device/commands", headers=device_headers).status_code == 401
