"""The saved follow-up is exact, versioned, contact-owned and independent of delivery."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import ArtifactVersion
from command_center.db.models import Actor
from command_center.db.reviewed_actions import ReviewedAction
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    owner = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner, kind="human", display_name="Synthetic follow-up writer"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner, "synthetic")
    with TestClient(app) as http:
        http.actor_id = owner
        yield http


def post(client, path, body, key=None):
    return client.post(
        f"/api/v1/{path}", json=body, headers={"Idempotency-Key": str(key or uuid4())}
    )


def test_linkedin_and_email_follow_ups_are_saved_once_without_delivery(client, engine):
    contact = post(
        client, "contacts", {"name": "Synthetic Taylor", "email": "taylor@example.com"}
    ).json()
    path = f"contacts/{contact['id']}/follow-ups"
    body = {
        "channel": "linkedin",
        "text": "<p>Hello <strong>Taylor</strong></p><p>A useful next step.</p>",
        "format": "html",
    }
    key = uuid4()
    created = post(client, path, body, key)
    assert created.status_code == 201, created.text
    saved = created.json()
    assert saved["plain_text"] == "Hello Taylor\nA useful next step."
    assert saved["version"]["payload"]["text"] == body["text"]
    assert post(client, path, body, key).json() == saved
    assert post(client, path, {**body, "text": "Different"}, key).status_code == 409
    artifact_id = saved["artifact"]["id"]
    listed = client.get(f"/api/v1/{path}").json()
    assert listed["total"] == 1
    assert listed["items"][0]["artifact_id"] == artifact_id
    assert "text" not in listed["items"][0]
    assert client.get(f"/api/v1/follow-ups/{artifact_id}").json() == saved
    revision = client.patch(
        f"/api/v1/follow-ups/{artifact_id}",
        json={
            "channel": "email",
            "subject": "A thoughtful introduction",
            "text": "  Keep my writing\n\n ",
            "format": "text",
            "recipient_email": "taylor@example.com",
            "based_on_version_id": saved["version"]["id"],
            "expected_version": saved["artifact"]["row_version"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert revision.status_code == 200, revision.text
    assert revision.json()["version"]["version"] == 2
    assert revision.json()["plain_text"] == "  Keep my writing\n\n "
    assert revision.json()["version"]["input_version_ids"] == [saved["version"]["id"]]
    assert (
        client.get(f"/api/v1/artifacts/{artifact_id}/versions/{saved['version']['id']}").json()[
            "payload"
        ]
        == saved["version"]["payload"]
    )
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ReviewedAction)
                .where(ReviewedAction.owner_id == client.actor_id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ArtifactVersion)
                .where(ArtifactVersion.artifact_id == artifact_id)
            )
            == 2
        )


def test_follow_up_rejects_foreign_contacts_sources_bases_and_stale_revisions(client, engine):
    contact = post(client, "contacts", {"name": "First contact"}).json()
    saved = post(client, f"contacts/{contact['id']}/follow-ups", {"text": "A real sentence"}).json()
    artifact_id = saved["artifact"]["id"]
    target = f"/api/v1/follow-ups/{artifact_id}"
    body = {
        "text": "Edited message",
        "based_on_version_id": str(uuid4()),
        "expected_version": saved["artifact"]["row_version"],
    }
    assert (
        client.patch(target, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code
        == 422
    )
    body["based_on_version_id"] = saved["version"]["id"]
    body["expected_version"] = 999
    assert (
        client.patch(target, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code
        == 409
    )
    assert (
        post(
            client,
            f"contacts/{contact['id']}/follow-ups",
            {"text": "Evidence", "source_version_ids": [str(uuid4())]},
        ).status_code
        == 422
    )
    other = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other, kind="human", display_name="Other writer"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other, "other")
    assert client.get(target).status_code == 404
    assert client.get(f"/api/v1/contacts/{contact['id']}/follow-ups").status_code == 404
    assert (
        post(
            client, f"contacts/{contact['id']}/follow-ups", {"text": "Another message"}
        ).status_code
        == 404
    )


def test_empty_or_hidden_only_content_cannot_be_checkpointed(client):
    contact = post(client, "contacts", {"name": "Synthetic contact"}).json()
    for content in ("<p></p>", "<script>hidden</script>", "<p>  </p>"):
        assert (
            post(
                client, f"contacts/{contact['id']}/follow-ups", {"format": "html", "text": content}
            ).status_code
            == 422
        )
