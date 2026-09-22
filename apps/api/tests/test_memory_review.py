"""Synthetic regressions for reviewed, scoped reusable memory."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.core.capabilities import issue_run_token
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.conversations import AgentSession
from command_center.db.models import Actor, Task
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic memory owner"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic-memory-owner")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def request(client, method, path, body=None, *, headers=None, key=None):
    return client.request(
        method,
        "/api/v1/" + path,
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())} | (headers or {}),
    )


def create_memory(client, **overrides):
    body = {
        "title": "Synthetic working preference",
        "content": "Use concise synthetic status updates.",
        "kind": "preference",
        "confirm": True,
    } | overrides
    response = request(client, "POST", "memories", body)
    assert response.status_code == 201, response.text
    return response.json()


def review(client, memory, *, revision_id=None, decision="approved", reason=None):
    return request(
        client,
        "POST",
        f"memories/{memory['id']}/reviews",
        {
            "expected_version": memory["row_version"],
            "revision_id": revision_id or memory["current"]["id"],
            "decision": decision,
            "reason": reason,
        },
    )


def running_agent(engine, owner_id, *, task_id=None):
    profile = AgentProfile(
        name="Synthetic memory agent",
        description="Proposes and retrieves synthetic memory",
        model="synthetic",
        instructions="Use only synthetic fixtures",
        tools=["memory_read", "memory_append"],
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        session_id = None
        if task_id is not None:
            conversation = AgentSession.open(
                db,
                record_id=uuid4(),
                owner_id=owner_id,
                task_id=task_id,
                opportunity_id=None,
                request_id=uuid4(),
            )
            db.flush()
            session_id = conversation.id
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=owner_id,
            prompt="Remember a synthetic preference",
            profile="synthetic",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
            session_id=session_id,
        )
        db.flush()
        claimed = AgentRun.claim(db, run.id)
        assert claimed is not None and claimed.lease_id is not None
        return claimed.id, claimed.lease_id


def test_human_confirmed_memory_is_retrievable_and_idempotent(client):
    key = uuid4()
    body = {
        "title": "Synthetic editor preference",
        "content": "Prefer short synthetic examples.",
        "kind": "preference",
        "confirm": True,
    }
    first = request(client, "POST", "memories", body, key=key)
    assert first.status_code == 201, first.text
    memory = first.json()
    assert memory["current"]["review_state"] == "approved"
    assert memory["active"]["id"] == memory["current"]["id"]
    assert memory["source"] == "human"
    assert request(client, "POST", "memories", body, key=key).json() == memory
    assert (
        request(
            client,
            "POST",
            "memories",
            body | {"content": "Different"},
            key=key,
        ).status_code
        == 409
    )

    retrieved = client.get("/api/v1/memories/retrieve?q=short+examples").json()
    assert retrieved["total"] == 1
    assert retrieved["items"][0]["memory_id"] == memory["id"]
    assert retrieved["items"][0]["content"] == body["content"]


def test_agent_memory_stays_proposed_and_human_review_is_required(client, engine, settings):
    run_id, lease_id = running_agent(engine, client.actor_id)
    client.app.dependency_overrides.pop(authenticate)
    agent_headers = {
        "Authorization": "Bearer " + issue_run_token(settings, run_id, lease_id),
    }
    response = request(
        client,
        "POST",
        "memories",
        {
            "title": "Synthetic reusable observation",
            "content": "The owner requested concise synthetic summaries.",
            "kind": "preference",
            "reason": "This preference recurred during the synthetic task.",
        },
        headers=agent_headers,
    )
    assert response.status_code == 201, response.text
    proposal = response.json()
    assert proposal["current"]["source"] == "agent"
    assert proposal["current"]["source_run_id"] == str(run_id)
    assert proposal["current"]["review_state"] == "proposed"
    assert proposal["active"] is None
    assert client.get("/api/v1/memories", headers=agent_headers).status_code == 403
    assert client.get("/api/v1/memories/retrieve", headers=agent_headers).json()["items"] == []
    assert (
        request(
            client,
            "POST",
            f"memories/{proposal['id']}/reviews",
            {
                "expected_version": proposal["row_version"],
                "revision_id": proposal["current"]["id"],
                "decision": "approved",
            },
            headers=agent_headers,
        ).status_code
        == 403
    )

    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic-memory-owner"
    )
    approved_response = review(client, proposal)
    assert approved_response.status_code == 200, approved_response.text
    assert approved_response.json()["active"]["id"] == proposal["current"]["id"]
    assert client.get("/api/v1/memories/retrieve").json()["total"] == 1


def test_pending_edit_and_rejection_preserve_old_active_then_revoke_clears_it(client):
    memory = create_memory(client)
    original_revision_id = memory["active"]["id"]
    edited_response = request(
        client,
        "PATCH",
        f"memories/{memory['id']}",
        {
            "expected_version": memory["row_version"],
            "title": memory["title"],
            "content": "A pending synthetic replacement.",
            "kind": memory["kind"],
            "confirm": False,
        },
    )
    assert edited_response.status_code == 200, edited_response.text
    edited = edited_response.json()
    assert edited["current"]["review_state"] == "proposed"
    assert edited["active"]["id"] == original_revision_id
    assert (
        client.get("/api/v1/memories/retrieve").json()["items"][0]["content"] == memory["content"]
    )

    rejected_response = review(
        client,
        edited,
        decision="rejected",
        reason="Keep the approved wording.",
    )
    assert rejected_response.status_code == 200, rejected_response.text
    rejected = rejected_response.json()
    assert rejected["current"]["review_state"] == "rejected"
    assert rejected["active"]["id"] == original_revision_id

    revoked_response = review(
        client,
        rejected,
        revision_id=original_revision_id,
        decision="revoked",
        reason="This preference no longer applies.",
    )
    assert revoked_response.status_code == 200, revoked_response.text
    assert revoked_response.json()["active"] is None
    assert client.get("/api/v1/memories/retrieve").json()["items"] == []


def test_retrieval_uses_run_scope_full_text_expiry_and_archive(client, engine, settings, mocker):
    task_id, other_task_id = uuid4(), uuid4()
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                Task(id=task_id, owner_id=client.actor_id, title="Synthetic scoped task"),
                Task(id=other_task_id, owner_id=client.actor_id, title="Other synthetic task"),
            ]
        )
    global_memory = create_memory(
        client,
        title="Global synthetic formatting",
        content="Use compact tables for synthetic comparisons.",
    )
    scoped = create_memory(
        client,
        title="Task synthetic formatting",
        content="Use compact tables for this synthetic task.",
        scope_type="task",
        scope_id=str(task_id),
        valid_until=(utc_now() + timedelta(hours=1)).isoformat(),
    )
    create_memory(
        client,
        title="Unrelated synthetic formatting",
        content="Use verbose tables in the other synthetic task.",
        scope_type="task",
        scope_id=str(other_task_id),
    )
    run_id, lease_id = running_agent(engine, client.actor_id, task_id=task_id)
    client.app.dependency_overrides.pop(authenticate)
    agent_headers = {
        "Authorization": "Bearer " + issue_run_token(settings, run_id, lease_id),
    }
    retrieved = client.get(
        "/api/v1/memories/retrieve?q=compact+tables&limit=10", headers=agent_headers
    )
    assert retrieved.status_code == 200, retrieved.text
    assert [item["memory_id"] for item in retrieved.json()["items"]] == [
        scoped["id"],
        global_memory["id"],
    ]
    proposed = request(
        client,
        "POST",
        "memories",
        {
            "title": "Synthetic task-only proposal",
            "content": "Reuse only within the current synthetic task.",
            "scope_type": "task",
            "reason": "The preference is specific to this synthetic task.",
        },
        headers=agent_headers,
    )
    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["current"]["scope_id"] == str(task_id)
    assert proposed.json()["active"] is None
    assert (
        client.get(
            f"/api/v1/memories/retrieve?task_id={other_task_id}",
            headers=agent_headers,
        ).status_code
        == 403
    )

    mocker.patch(
        "command_center.db.memory.utc_now",
        return_value=utc_now() + timedelta(hours=2),
    )
    expired = client.get("/api/v1/memories/retrieve?q=compact+tables", headers=agent_headers).json()
    assert [item["memory_id"] for item in expired["items"]] == [global_memory["id"]]

    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic-memory-owner"
    )
    archived = request(
        client,
        "POST",
        f"memories/{global_memory['id']}/archive",
        {"expected_version": global_memory["row_version"]},
    )
    assert archived.status_code == 200, archived.text
    assert client.get("/api/v1/memories/retrieve?q=compact+tables").json()["items"] == []
