"""Synthetic PostgreSQL coverage for owned, persistent work contexts."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.artifacts import Artifact
from command_center.db.crm import Company, Contact, Opportunity
from command_center.db.errors import RecordConflict
from command_center.db.idempotency import RequestReceipt
from command_center.db.models import Actor, AuditEvent, Task
from command_center.db.spaces import Space, SpaceLink
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic Space owner"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic-spaces")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def post(client, path, body, key=None):
    return client.post(
        "/api/v1/" + path, json=body, headers={"Idempotency-Key": str(key or uuid4())}
    )


def patch(client, path, body, key=None):
    return client.patch(
        "/api/v1/" + path, json=body, headers={"Idempotency-Key": str(key or uuid4())}
    )


def make_space(client, title="Synthetic research"):
    response = post(client, "spaces", {"title": title, "purpose": "Track a synthetic objective"})
    assert response.status_code == 201, response.text
    return response.json()


def make_records(db, owner_id):
    company = Company(id=uuid4(), owner_id=owner_id, name="Synthetic company")
    contact = Contact(id=uuid4(), owner_id=owner_id, name="Synthetic contact")
    task = Task(id=uuid4(), owner_id=owner_id, title="Synthetic task")
    artifact = Artifact(
        id=uuid4(),
        owner_id=owner_id,
        created_by_id=owner_id,
        title="Synthetic source",
        kind="source",
    )
    db.add_all([company, contact, task, artifact])
    db.flush()
    opportunity = Opportunity(
        id=uuid4(), owner_id=owner_id, company_id=company.id, title="Synthetic opportunity"
    )
    db.add(opportunity)
    db.flush()
    return {
        "company": company.id,
        "contact": contact.id,
        "task": task.id,
        "artifact": artifact.id,
        "opportunity": opportunity.id,
    }


def test_space_create_edit_conflict_retry_and_search(client, engine):
    key = uuid4()
    body = {"title": "Research 100%_fit", "purpose": "Keep context"}
    created = post(client, "spaces", body, key)
    assert created.status_code == 201, created.text
    space = created.json()
    assert space["row_version"] == 1 and space["state"] == "active"
    assert space["links"] == []
    assert "owner_id" not in space
    assert post(client, "spaces", body, key).json() == space
    assert post(client, "spaces", {**body, "title": "Changed"}, key).status_code == 409
    assert client.get("/api/v1/spaces?q=100%25_fit").json()["total"] == 1
    assert client.get("/api/v1/spaces?q=100Xfit").json()["total"] == 0
    assert client.get("/api/v1/spaces?limit=1&offset=1").json()["items"] == []
    revision = {"expected_version": 1, "title": "Research result", "purpose": None}
    edit_key = uuid4()
    edited = patch(client, f"spaces/{space['id']}", revision, edit_key)
    assert edited.status_code == 200, edited.text
    assert edited.json()["row_version"] == 2
    assert edited.json()["purpose"] is None
    assert patch(client, f"spaces/{space['id']}", revision, edit_key).json() == edited.json()
    assert patch(client, f"spaces/{space['id']}", revision).status_code == 409
    assert (
        patch(client, f"spaces/{space['id']}", {"expected_version": 2, "title": None}).status_code
        == 422
    )
    assert post(client, "spaces", {"title": "   "}).status_code == 422
    with Session(engine) as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.subject_id == space["id"])).all()
        assert [event.action for event in events] == ["spaces.created", "spaces.updated"]
        assert "Keep context" not in str([event.details for event in events])


def test_spaces_and_all_memberships_are_owner_scoped(client, engine):
    space = make_space(client)
    with Session(engine) as db, db.begin():
        outsider = Actor(id=uuid4(), kind="human", display_name="Other synthetic owner")
        db.add(outsider)
        db.flush()
        other_space = Space.create(
            db,
            record_id=uuid4(),
            owner_id=outsider.id,
            title="Private context",
            purpose=None,
            request_id=uuid4(),
        )
        other_records = make_records(db, outsider.id)
        other_link = other_space.link("task", other_records["task"], request_id=uuid4())
        db.flush()
        other_id, other_link_id = other_space.id, other_link.id
    assert client.get("/api/v1/spaces?state=all").json()["total"] == 1
    assert client.get(f"/api/v1/spaces/{other_id}").status_code == 404
    assert (
        patch(client, f"spaces/{other_id}", {"expected_version": 2, "title": "Changed"}).status_code
        == 404
    )
    for action in ("archive", "restore"):
        assert (
            post(client, f"spaces/{other_id}/{action}", {"expected_version": 2}).status_code == 404
        )
    assert (
        post(
            client, f"spaces/{other_id}/tasks?expected_version=2", {"title": "Bad capture"}
        ).status_code
        == 404
    )
    for record_type, record_id in other_records.items():
        body = {"expected_version": 1, "record_type": record_type, "record_id": str(record_id)}
        assert post(client, f"spaces/{space['id']}/links", body).status_code == 404
        assert post(client, f"spaces/{other_id}/links", body).status_code == 404
    assert (
        post(
            client,
            f"spaces/{space['id']}/links/{other_link_id}/unlink",
            {"expected_version": 1},
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/spaces/{space['id']}").json()["row_version"] == 1


def test_links_share_records_are_unique_and_unlink_is_audited(client, engine):
    space = make_space(client)
    with Session(engine) as db, db.begin():
        records = make_records(db, client.actor_id)
    for record_type, record_id in records.items():
        body = {
            "expected_version": space["row_version"],
            "record_type": record_type,
            "record_id": str(record_id),
        }
        key = uuid4()
        linked = post(client, f"spaces/{space['id']}/links", body, key)
        assert linked.status_code == 200, linked.text
        space = linked.json()
        assert post(client, f"spaces/{space['id']}/links", body, key).json() == space
        duplicate = post(
            client,
            f"spaces/{space['id']}/links",
            {**body, "expected_version": space["row_version"]},
        )
        assert duplicate.json() == space
        link = next(link for link in space["links"] if link["record_type"] == record_type)
        assert link["record"]["id"] == str(record_id)
        assert "owner_id" not in link["record"]
    assert len(space["links"]) == 5 and space["row_version"] == 6
    task_link = next(link for link in space["links"] if link["record_type"] == "task")
    completed = patch(
        client,
        f"tasks/{task_link['record_id']}",
        {"expected_version": task_link["record"]["row_version"], "state": "done"},
    )
    assert completed.status_code == 200, completed.text
    refreshed = client.get(f"/api/v1/spaces/{space['id']}").json()
    assert (
        next(link for link in refreshed["links"] if link["record_type"] == "task")["record"][
            "state"
        ]
        == "done"
    )
    body = {"expected_version": space["row_version"]}
    path = f"spaces/{space['id']}/links/{task_link['id']}/unlink"
    key = uuid4()
    removed = post(client, path, body, key)
    assert removed.status_code == 200, removed.text
    assert removed.json()["row_version"] == 7 and len(removed.json()["links"]) == 4
    assert post(client, path, body, key).json() == removed.json()
    assert client.get(f"/api/v1/tasks/{task_link['record_id']}").json()["state"] == "done"
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(SpaceLink).where(SpaceLink.space_id == space["id"])
            )
            == 4
        )
        actions = db.scalars(
            select(AuditEvent.action).where(AuditEvent.subject_id == space["id"])
        ).all()
        assert actions.count("spaces.linked") == 5 and actions.count("spaces.unlinked") == 1


def test_archive_preserves_context_blocks_capture_and_can_restore(client, engine):
    space = make_space(client)
    task = post(client, "tasks", {"title": "Keep existing task"}).json()
    linked = post(
        client,
        f"spaces/{space['id']}/links",
        {"expected_version": 1, "record_type": "task", "record_id": task["id"]},
    ).json()
    body = {"expected_version": 2}
    key = uuid4()
    archived = post(client, f"spaces/{space['id']}/archive", body, key)
    assert archived.status_code == 200, archived.text
    assert archived.json()["state"] == "archived" and archived.json()["row_version"] == 3
    assert archived.json()["links"] == linked["links"]
    assert post(client, f"spaces/{space['id']}/archive", body, key).json() == archived.json()
    assert client.get("/api/v1/spaces").json()["total"] == 0
    assert client.get("/api/v1/spaces?state=archived").json()["total"] == 1
    assert client.get(f"/api/v1/spaces/{space['id']}").json() == archived.json()
    assert (
        post(
            client, f"spaces/{space['id']}/tasks?expected_version=3", {"title": "Blocked capture"}
        ).status_code
        == 409
    )
    assert (
        patch(
            client, f"spaces/{space['id']}", {"expected_version": 3, "title": "Blocked edit"}
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            f"spaces/{space['id']}/links",
            {"expected_version": 3, "record_type": "task", "record_id": task["id"]},
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            f"spaces/{space['id']}/links/{linked['links'][0]['id']}/unlink",
            {"expected_version": 3},
        ).status_code
        == 409
    )
    assert post(client, f"spaces/{space['id']}/restore", {"expected_version": 2}).status_code == 409
    restore_key = uuid4()
    restored = post(client, f"spaces/{space['id']}/restore", {"expected_version": 3}, restore_key)
    assert restored.status_code == 200, restored.text
    assert restored.json()["state"] == "active" and restored.json()["archived_at"] is None
    assert restored.json()["row_version"] == 4
    assert (
        post(client, f"spaces/{space['id']}/restore", {"expected_version": 3}, restore_key).json()
        == restored.json()
    )
    assert client.get("/api/v1/spaces").json()["total"] == 1
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Task).where(Task.owner_id == client.actor_id)
            )
            == 1
        )


def test_capture_is_atomic_replayable_versioned_and_does_not_dispatch(client, engine, mocker):
    space = make_space(client)
    body = {"title": "Capture a next step", "priority": 2, "due_date": "2026-10-01"}
    path = f"spaces/{space['id']}/tasks?expected_version=1"
    key = uuid4()
    captured = post(client, path, body, key)
    assert captured.status_code == 201, captured.text
    result = captured.json()
    assert result["space"]["row_version"] == 2
    assert result["task"]["state"] == "open"
    assert result["space"]["links"][0]["record_id"] == result["task"]["id"]
    assert post(client, path, body, key).json() == result
    assert post(client, path, body).status_code == 409
    assert (
        post(client, f"spaces/{space['id']}/tasks?expected_version=2", body, key).status_code == 409
    )
    failure_key = uuid4()
    mocker.patch.object(Space, "link", side_effect=RecordConflict("Synthetic link failure"))
    failed = post(client, f"spaces/{space['id']}/tasks?expected_version=2", body, failure_key)
    assert failed.status_code == 409
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Task).where(Task.owner_id == client.actor_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(SpaceLink)
                .where(SpaceLink.owner_id == client.actor_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.owner_id == client.actor_id)
            )
            == 0
        )
        assert db.get(RequestReceipt, (client.actor_id, failure_key)) is None
        assert db.get(Space, UUID(space["id"])).row_version == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.actor_id == client.actor_id, AuditEvent.action == "tasks.created")
            )
            == 1
        )


def test_invalid_or_archived_targets_and_capture_opportunities_are_rejected(client, engine):
    space = make_space(client)
    company = post(client, "companies", {"name": "Archive target"}).json()
    post(client, f"companies/{company['id']}/archive", {"expected_version": 1})
    assert (
        post(
            client,
            f"spaces/{space['id']}/links",
            {"expected_version": 1, "record_type": "company", "record_id": company["id"]},
        ).status_code
        == 422
    )
    assert (
        post(
            client,
            f"spaces/{space['id']}/links",
            {"expected_version": 1, "record_type": "task", "record_id": str(uuid4())},
        ).status_code
        == 404
    )
    assert (
        post(
            client,
            f"spaces/{space['id']}/tasks?expected_version=1",
            {"title": "Bad reference", "opportunity_id": str(uuid4())},
        ).status_code
        == 404
    )
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Task).where(Task.owner_id == client.actor_id)
            )
            == 0
        )


def test_concurrent_space_edits_require_current_version(client):
    space = make_space(client)

    def edit(title):
        return patch(client, f"spaces/{space['id']}", {"expected_version": 1, "title": title})

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(edit, ["First change", "Second change"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert client.get(f"/api/v1/spaces/{space['id']}").json()["row_version"] == 2


def test_database_rejects_cross_owner_duplicate_and_multiple_target_links(session):
    owners = [Actor(id=uuid4(), kind="human", display_name="Synthetic owner") for _ in range(2)]
    session.add_all(owners)
    session.flush()
    space = Space.create(
        session,
        record_id=uuid4(),
        owner_id=owners[0].id,
        title="Database constraints",
        purpose=None,
        request_id=uuid4(),
    )
    own_records = make_records(session, owners[0].id)
    other_records = make_records(session, owners[1].id)
    invalid_links = [
        {"owner_id": owners[0].id, "task_id": other_records["task"]},
        {"owner_id": owners[1].id, "task_id": other_records["task"]},
        {"owner_id": owners[0].id},
        {
            "owner_id": owners[0].id,
            "task_id": own_records["task"],
            "artifact_id": own_records["artifact"],
        },
    ]
    for fields in invalid_links:
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(SpaceLink(space_id=space.id, **fields))
            session.flush()
    space.link("task", own_records["task"], request_id=uuid4())
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            SpaceLink(space_id=space.id, owner_id=owners[0].id, task_id=own_records["task"])
        )
        session.flush()
