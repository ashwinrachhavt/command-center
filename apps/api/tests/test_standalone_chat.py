"""The Agents composer continues one owned conversation across runs."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.models import Actor
from command_center.main import create_app


@pytest.fixture
def chat_client(settings, engine, mocker):
    owner = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner, kind="human", display_name="Synthetic chat owner"))
    profile = AgentProfile(
        name="Synthetic", description="Synthetic", model="synthetic", instructions="Synthetic"
    )
    mocker.patch("command_center.api.agents.available_profile", return_value=(profile, "synthetic"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner, "synthetic")
    with TestClient(app) as client:
        client.owner_id = owner
        yield client


def send(client, prompt, previous=None, key=None):
    return client.post(
        "/api/v1/agent-runs",
        json={
            "profile": "research",
            "prompt": prompt,
            **({"continue_run_id": previous} if previous else {}),
        },
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def test_replies_stay_in_one_conversation_and_new_run_starts_another(chat_client, engine):
    first = send(chat_client, "What can you help with?").json()
    with Session(engine) as db, db.begin():
        run = db.get(AgentRun, UUID(first["id"]))
        run.consumed_sequence = run.input_sequence
        run.finish("completed", output="I can help with research.")
    reply = send(chat_client, "What about applications?", first["id"])
    assert reply.status_code == 201, reply.text
    second = reply.json()
    assert first["session_id"] and second["session_id"] == first["session_id"]
    assert second["id"] != first["id"]
    history = chat_client.get(f"/api/v1/agent-sessions/{first['session_id']}/messages").json()
    assert [item["content"] for item in history["items"]] == [
        "What can you help with?",
        "I can help with research.",
        "What about applications?",
    ]
    fresh = send(chat_client, "A separate conversation").json()
    assert fresh["session_id"] != first["session_id"]


def test_reply_while_running_is_one_instruction_and_idempotent(chat_client):
    first = send(chat_client, "Research a synthetic company").json()
    key = uuid4()
    response = send(chat_client, "Focus on its engineering team", first["id"], key)
    assert response.status_code == 201, response.text
    assert response.json()["id"] == first["id"]
    assert (
        send(chat_client, "Focus on its engineering team", first["id"], key).json()
        == response.json()
    )
    history = chat_client.get(f"/api/v1/agent-sessions/{first['session_id']}/messages").json()
    assert history["total"] == 2


def test_reply_cannot_attach_to_another_owners_conversation(chat_client, engine):
    with Session(engine) as db, db.begin():
        other = Actor(id=uuid4(), kind="human", display_name="Other synthetic owner")
        db.add(other)
        other_id = other.id
    first = send(chat_client, "Private synthetic request").json()
    chat_client.app.dependency_overrides[authenticate] = lambda: Identity(other_id, "other")
    response = send(chat_client, "Must not join", first["id"])
    assert response.status_code == 404


def test_reply_adopts_legacy_run_with_original_prompt_and_answer(chat_client, engine):
    with Session(engine) as db, db.begin():
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=chat_client.owner_id,
            prompt="Original standalone prompt",
            profile="research",
            configuration={"model": "synthetic"},
            revision="synthetic",
            request_id=uuid4(),
        )
        run.finish("completed", output="Original answer")
        original_id = str(run.id)
    response = send(chat_client, "Continue the same topic", original_id)
    assert response.status_code == 201, response.text
    conversation_id = response.json()["session_id"]
    history = chat_client.get(f"/api/v1/agent-sessions/{conversation_id}/messages").json()
    assert [item["content"] for item in history["items"]] == [
        "Original standalone prompt",
        "Original answer",
        "Continue the same topic",
    ]
    with Session(engine) as db:
        assert str(db.get(AgentRun, UUID(original_id)).session_id) == conversation_id
