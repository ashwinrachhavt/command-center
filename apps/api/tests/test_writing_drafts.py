"""Draft recovery and concurrency use real PostgreSQL, never personal text."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import Artifact
from command_center.db.models import Actor, AuditEvent
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic writer"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic-writer")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def save(client, version, data, *, key=None, scope="email-new"):
    return client.put(
        f"/api/v1/writing-drafts/{scope}",
        json={"expected_version": version, "data": data},
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def test_autosave_recovers_without_creating_versions_or_per_keystroke_history(client, engine):
    url = "/api/v1/writing-drafts/email-new"
    assert client.get(url).json() == {
        "scope_key": "email-new",
        "row_version": 0,
        "data": None,
        "updated_at": None,
        "last_save_key": None,
    }
    key = uuid4()
    first = save(client, 0, {"body": "Synthetic first sentence"}, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["row_version"] == 1
    assert save(client, 0, {"body": "Synthetic first sentence"}, key=key).json() == first.json()
    assert save(client, 0, {"body": "Different text"}, key=key).status_code == 409
    second = save(
        client, 1, {"body": "Synthetic second sentence", "editor": {"type": "doc", "content": []}}
    )
    assert second.status_code == 200
    assert second.json()["row_version"] == 2
    assert client.get(url).json()["data"] == second.json()["data"]
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.owner_id == client.actor_id)
            )
            == 0
        )
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.actor_id == client.actor_id, AuditEvent.subject_type == "writing_drafts"
            )
        ).all()
        assert [event.action for event in events] == ["writing_draft.started"]


def test_stale_tab_cannot_overwrite_clear_or_recreate_another_draft(client):
    first = save(client, 0, {"body": "Newer writing"}).json()
    stale = save(client, 0, {"body": "Old tab"})
    assert stale.status_code == 409
    clear_key = str(uuid4())
    clear = client.post(
        "/api/v1/writing-drafts/email-new/clear",
        json={"expected_version": first["row_version"]},
        headers={"Idempotency-Key": clear_key},
    )
    assert clear.status_code == 200
    assert clear.json()["data"] is None
    assert clear.json()["row_version"] == 2
    assert (
        client.post(
            "/api/v1/writing-drafts/email-new/clear",
            json={"expected_version": 1},
            headers={"Idempotency-Key": clear_key},
        ).json()
        == clear.json()
    )
    assert save(client, 1, {"body": "Do not resurrect discarded text"}).status_code == 409
    assert save(client, 2, {"body": "A new draft"}).json()["row_version"] == 3
    assert (
        client.post(
            "/api/v1/writing-drafts/email-new/clear",
            json={"expected_version": 1},
            headers={"Idempotency-Key": clear_key},
        ).status_code
        == 409
    )
    assert client.get("/api/v1/writing-drafts/email-new").json()["data"] == {"body": "A new draft"}


def test_drafts_are_actor_scoped_and_agents_cannot_read_or_edit_them(client, engine):
    save(client, 0, {"body": "Private synthetic draft"})
    other = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other, kind="human", display_name="Other synthetic writer"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other, "other-writer")
    assert client.get("/api/v1/writing-drafts/email-new").json()["data"] is None
    assert save(client, 0, {"body": "Other person's own draft"}).status_code == 200
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic-agent", run_id=uuid4()
    )
    assert client.get("/api/v1/writing-drafts/email-new").status_code == 403
    assert save(client, 1, {"body": "Agent overwrite"}).status_code == 403


def test_oversized_working_copy_does_not_replace_saved_writing(client):
    save(client, 0, {"body": "Keep this synthetic text"})
    rejected = save(client, 1, {"body": "x" * 1_000_001})
    assert rejected.status_code == 422
    assert client.get("/api/v1/writing-drafts/email-new").json()["data"] == {
        "body": "Keep this synthetic text"
    }


def test_autosave_preserves_spaces_line_breaks_and_exact_editor_nodes(client):
    data = {
        "body": "  Synthetic writing \n\n ",
        "editor": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}],
        },
    }
    response = save(client, 0, data)
    assert response.status_code == 200
    assert response.json()["data"] == data
    assert client.get("/api/v1/writing-drafts/email-new").json()["data"] == data


def test_recovery_is_periodic_bounded_and_survives_checkpoint_clear(client, mocker):
    clock = mocker.patch("command_center.db.writing.utc_now")
    clock.return_value = datetime(2026, 9, 22, tzinfo=UTC)
    url = "/api/v1/writing-drafts/email-new"
    first_key = uuid4()
    first = save(client, 0, {"body": "First copy"}, key=first_key)
    assert first.status_code == 200
    assert save(client, 0, {"body": "First copy"}, key=first_key).status_code == 200
    for revision in range(1, 4):
        assert save(client, revision, {"body": f"Quick edit {revision}"}).status_code == 200
    history = client.get(f"{url}/recovery").json()
    assert history["total"] == 1
    assert "data" not in history["items"][0]
    for revision in range(4, 27):
        clock.return_value += timedelta(minutes=5)
        assert save(client, revision, {"body": f"Periodic copy {revision}"}).status_code == 200
    page = client.get(f"{url}/recovery?limit=7").json()
    assert page["total"] == 20
    assert [row["row_version"] for row in page["items"]] == list(range(27, 20, -1))
    next_page = client.get(f"{url}/recovery?before={page['next_before']}&limit=20").json()
    assert len(next_page["items"]) == 13
    assert next_page["next_before"] is None
    final = {"body": "  Final writing\n\n "}
    assert save(client, 27, final).status_code == 200
    assert (
        client.post(
            f"{url}/clear",
            json={"expected_version": 28},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 200
    )
    assert client.get(url).json()["data"] is None
    copies = client.get(f"{url}/recovery").json()
    assert copies["total"] == 20
    latest = client.get(f"{url}/recovery/{copies['items'][0]['id']}").json()
    assert latest["row_version"] == 28
    assert latest["data"] == final
    assert client.get(f"{url}/recovery?limit=21").status_code == 422


def test_recovery_is_scoped_to_the_human_and_exact_writer(client, engine):
    assert save(client, 0, {"body": "Private synthetic copy"}).status_code == 200
    url = "/api/v1/writing-drafts/email-new/recovery"
    copy_id = client.get(url).json()["items"][0]["id"]
    assert (
        client.get(f"/api/v1/writing-drafts/another-writer/recovery/{copy_id}").status_code == 404
    )
    other = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other, kind="human", display_name="Other recovery reader"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other, "other-writer")
    assert client.get(url).json()["items"] == []
    assert client.get(f"{url}/{copy_id}").status_code == 404
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic-agent", run_id=uuid4()
    )
    assert client.get(url).status_code == 403
    assert client.get(f"{url}/{copy_id}").status_code == 403
