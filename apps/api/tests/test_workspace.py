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


def test_library_searches_current_owned_content_and_document_types(client, engine):
    from command_center.db.artifacts import Artifact

    types = client.get("/api/v1/document-types").json()
    notes = next(row["id"] for row in types if row["slug"] == "notes")
    resume = next(row["id"] for row in types if row["slug"] == "resume")
    note = post(
        client,
        "artifacts",
        {
            "title": "A conversation",
            "document_type_id": notes,
            "text": "Rare needle 100%_value",
        },
    ).json()
    post(
        client,
        "artifacts",
        {
            "title": "Z resume",
            "document_type_id": resume,
            "text": "Synthetic skills",
        },
    )
    post(client, "artifacts", {"title": "Hidden snapshot", "kind": "source", "text": "Rare needle"})
    post(client, "artifacts", {"title": "Hidden email", "kind": "message", "text": "Rare needle"})
    with Session(engine) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Another synthetic owner")
        db.add(owner)
        db.flush()
        Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=owner.id,
            request_id=uuid4(),
            title="Private note",
            kind="document",
            document_type_id=notes,
            sensitivity="private",
            text="Rare needle",
        )
    base = "/api/v1/artifacts"
    found = client.get(base, params={"collection": "library", "q": "rare NEEDLE"}).json()
    assert found["total"] == 1 and found["items"][0]["id"] == note["id"]
    assert "payload" not in found["items"][0]
    assert (
        client.get(base, params={"collection": "library", "q": "100%_value"}).json()["total"] == 1
    )
    assert (
        client.get(base, params={"collection": "library", "q": "100%Zvalue"}).json()["total"] == 0
    )
    assert (
        client.get(base, params={"collection": "library", "document_type_id": resume}).json()[
            "total"
        ]
        == 1
    )
    assert client.get("/api/v1/artifacts?collection=notes").json()["total"] == 1
    first = client.get(base, params={"collection": "library", "sort": "title", "limit": 1}).json()
    assert first["total"] == 2 and first["items"][0]["id"] == note["id"]
    version_id = client.get(f"/api/v1/artifacts/{note['id']}/version-history").json()["items"][0][
        "id"
    ]
    appended = post(
        client,
        f"artifacts/{note['id']}/versions",
        {
            "text": "Current body",
            "expected_version": note["row_version"],
            "based_on_version_id": version_id,
        },
    )
    assert appended.status_code == 201, appended.text
    assert (
        client.get(base, params={"collection": "library", "q": "Rare needle"}).json()["total"] == 0
    )
    assert (
        client.get(base, params={"collection": "library", "q": "Current body"}).json()["total"] == 1
    )
    post(client, f"artifacts/{note['id']}/archive", {"expected_version": note["row_version"] + 1})
    assert (
        client.get(base, params={"collection": "library", "q": "Current body"}).json()["total"] == 0
    )


def test_document_task_is_atomic_replayable_and_owned(client, engine):
    from command_center.db.artifacts import TaskArtifact
    from command_center.db.models import Task

    document = post(
        client, "artifacts", {"title": "Interview takeaways", "kind": "research"}
    ).json()
    path = f"artifacts/{document['id']}/tasks"
    key = uuid4()
    body = {"title": "Ask about team ownership", "rationale": "Clarify the interview notes"}
    result = post(client, path, body, key)
    assert result.status_code == 201, result.text
    task = result.json()
    assert post(client, path, body, key).json() == task
    assert client.get(f"/api/v1/{path}").json()["items"][0]["id"] == task["id"]
    sources = client.get("/api/v1/artifacts", params={"task_id": task["id"]}).json()
    assert sources["items"][0]["id"] == document["id"]
    with Session(engine) as db, db.begin():
        assert (
            db.scalar(
                select(func.count())
                .select_from(TaskArtifact)
                .where(TaskArtifact.artifact_id == document["id"])
            )
            == 1
        )
        outsider = Actor(id=uuid4(), kind="human", display_name="Other task owner")
        db.add(outsider)
        db.flush()
        other_task = Task(id=uuid4(), owner_id=outsider.id, title="Private task")
        db.add(other_task)
        other_id = str(other_task.id)
    assert client.get("/api/v1/artifacts", params={"task_id": other_id}).status_code == 404
    assert post(client, f"artifacts/{uuid4()}/tasks", body).status_code == 404
    post(
        client, f"artifacts/{document['id']}/archive", {"expected_version": document["row_version"]}
    )
    assert post(client, path, body).status_code == 422


def test_version_history_is_bounded_with_separate_owned_bodies(client, engine):
    from command_center.db.artifacts import Artifact

    artifact = post(
        client,
        "artifacts",
        {
            "title": "Synthetic long-lived note",
            "kind": "research",
            "text": "  First line\n\n",
        },
    ).json()
    with Session(engine) as db, db.begin():
        record = db.get(Artifact, artifact["id"])
        for number in range(2, 26):
            record.append_text(f"Checkpoint {number}", version_id=uuid4(), request_id=uuid4())
    path = f"/api/v1/artifacts/{artifact['id']}"
    first = client.get(f"{path}/version-history").json()
    assert first["total"] == 25 and len(first["items"]) == 20
    assert [item["version"] for item in first["items"]] == list(range(25, 5, -1))
    assert "payload" not in first["items"][0]
    assert first["items"][0]["is_text"] and not first["items"][0]["has_file"]
    with Session(engine) as db, db.begin():
        record = db.get(Artifact, artifact["id"])
        record.append_text("Newer concurrent checkpoint", version_id=uuid4(), request_id=uuid4())
    second = client.get(f"{path}/version-history?before={first['next_before']}&limit=20").json()
    assert second["total"] == 26 and len(second["items"]) == 5
    oldest = second["items"][-1]
    assert oldest["version"] == 1
    body = client.get(f"{path}/versions/{oldest['id']}")
    assert body.status_code == 200
    assert body.json()["payload"]["text"] == "  First line\n\n"
    assert len(client.get(f"{path}/versions").json()) == 20
    assert client.get(f"{path}/version-history?limit=101").status_code == 422
    assert client.get(f"/api/v1/artifacts/{uuid4()}/versions/{oldest['id']}").status_code == 404
    another = post(client, "artifacts", {"title": "Another note", "kind": "research"}).json()
    assert (
        client.get(f"/api/v1/artifacts/{another['id']}/versions/{oldest['id']}").status_code == 404
    )
    revision = post(
        client,
        f"artifacts/{artifact['id']}/versions",
        {
            "based_on_version_id": oldest["id"],
            "expected_version": client.get(path).json()["row_version"],
            "text": "  Keep this indentation\n\n",
        },
    )
    assert revision.status_code == 201, revision.text
    assert revision.json()["payload"]["text"] == "  Keep this indentation\n\n"


def test_contact_import_history_is_paginated_and_owned(client, engine):
    from uuid import uuid5

    from command_center.db.artifacts import Artifact
    from command_center.db.crm import Contact, ContactObservation

    contact = post(client, "contacts", {"name": "Synthetic exported contact"}).json()
    with Session(engine) as db, db.begin():
        source = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=client.actor_id,
            title="Synthetic export",
            kind="source",
            sensitivity="private",
            text="First Name: Alex",
            document_type_id=None,
            request_id=uuid4(),
        )
        row = db.get(Contact, contact["id"])
        observation = ContactObservation.capture_linkedin(
            db,
            contact=row,
            source_version_id=uuid5(source.id, "version:1"),
            source_row=1,
            row={"First Name": "Alex", "Connected On": "2025"},
            request_id=uuid4(),
        )
        observation_id = str(observation.id)
    response = client.get(f"/api/v1/contacts/{contact['id']}/observations?limit=1&offset=0")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == observation_id
    assert response.json()["items"][0]["connected_on"] == "2025"
    assert "owner_id" not in response.json()["items"][0]
    assert (
        client.get(f"/api/v1/contacts/{contact['id']}/observations?limit=1&offset=1").json()[
            "items"
        ]
        == []
    )
    client.app.dependency_overrides[authenticate] = lambda: Identity(uuid4(), "other-synthetic")
    assert client.get(f"/api/v1/contacts/{contact['id']}/observations").status_code == 404


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
        {
            "based_on_version_id": version["id"],
            "text": "Second draft",
            "expected_version": artifact["row_version"],
        },
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
        "protocol_version": 2,
        "page_url": "https://example.com/apply",
        "title": "Synthetic form",
        "fields": [
            {
                "id": "f0",
                "label": "Name",
                "type": "text",
                "value_state": "empty",
            }
        ],
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
        client.post(
            path + "/result",
            json={"state": "applied", "field_results": {"f0": {"status": "filled"}}},
            headers=device_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            path + "/result",
            json={"state": "applied", "field_results": {"f0": {"status": "filled"}}},
            headers=device_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            path + "/result",
            json={"state": "failed", "field_results": {"f0": {"status": "failed"}}},
            headers=device_headers,
        ).status_code
        == 409
    )
    assert post(client, f"browser/devices/{pairing['device_id']}/revoke", {}).status_code == 200
    assert client.get("/api/v1/browser/device/commands", headers=device_headers).status_code == 401
