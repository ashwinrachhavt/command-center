"""Durable task and opportunity conversations over real PostgreSQL."""

import threading
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from command_center.agents.worker import leased
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.conversations import AgentMessage, AgentSession
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor, Task
from command_center.main import create_app


@pytest.fixture
def client(settings, engine, tmp_path: Path):
    directives = tmp_path / "directives"
    directives.mkdir()
    (directives / "lead.md").write_text("Coordinate this synthetic test conversation.")
    (directives / "writer.md").write_text("Write within this synthetic test conversation.")
    config = tmp_path / "profiles.toml"
    config.write_text(
        """
[profiles.lead]
name = "Synthetic lead"
description = "Coordinates synthetic work."
model = "gpt-5-mini"
tools = []
skills = []
max_steps = 4
max_output_tokens = 1000
directive = "lead"

[profiles.writer]
name = "Synthetic writer"
description = "Writes synthetic drafts."
model = "gpt-5-mini"
tools = []
skills = []
max_steps = 4
max_output_tokens = 1000
directive = "writer"
""".strip()
    )
    configured = settings.model_copy(
        update={
            "agent_config": str(config),
            "agent_skills_dir": str(tmp_path / "skills"),
            "openai_api_key": SecretStr("synthetic-openai-key"),
        }
    )
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic conversation owner"))
    app = create_app(configured)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def post(client, path, body, key=None):
    return client.post(
        "/api/v1/" + path,
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def create_opportunity(client):
    company = post(client, "companies", {"name": "Synthetic conversation company"}).json()
    return post(
        client,
        "opportunities",
        {
            "company_id": company["id"],
            "title": "Synthetic conversation opportunity",
        },
    ).json()


def create_session(client, *, task_id=None, opportunity_id=None):
    response = post(
        client,
        "agent-sessions",
        {"task_id": task_id, "opportunity_id": opportunity_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_task_session_is_created_through_the_http_contract(client):
    task = post(client, "tasks", {"title": "Research a synthetic role"}).json()

    response = post(client, "agent-sessions", {"task_id": task["id"], "opportunity_id": None})

    assert response.status_code == 201, response.text
    assert response.json()["task_id"] == task["id"]


def test_tool_steps_prefers_the_bounded_public_projection():
    projected = [
        {
            "id": "tool_1",
            "name": "research_search",
            "role": "researcher",
            "state": "output-available",
            "output": "Synthetic result",
        }
    ]
    run = AgentRun(
        title="Synthetic projection",
        prompt="Test the public projection",
        profile="lead",
        config_snapshot={},
        checkpoint={
            "steps": 1,
            "tool_count": 1,
            "instruction_sequence": 3,
            "tools": projected,
        },
    )

    assert run.tool_steps() == projected


def test_canonical_session_reuse_keeps_task_and_opportunity_scopes_separate(client):
    opportunity = create_opportunity(client)
    task = post(
        client,
        "tasks",
        {"title": "Prepare synthetic materials", "opportunity_id": opportunity["id"]},
    ).json()

    task_session = create_session(client, task_id=task["id"])
    replayed_scope = create_session(client, task_id=task["id"])
    opportunity_session = create_session(client, opportunity_id=opportunity["id"])

    assert replayed_scope["id"] == task_session["id"]
    assert opportunity_session["id"] != task_session["id"]
    assert opportunity_session["task_id"] is None
    page = client.get("/api/v1/agent-sessions", params={"task_id": task["id"]}).json()
    assert page["total"] == 1
    assert page["items"] == [task_session]
    assert client.get("/api/v1/agent-sessions/" + task_session["id"]).json() == task_session


def test_session_scope_validation_and_owner_isolation(client, engine):
    task = post(client, "tasks", {"title": "Private synthetic task"}).json()
    opportunity = create_opportunity(client)
    empty = post(client, "agent-sessions", {"task_id": None, "opportunity_id": None})
    assert empty.status_code == 422
    assert (
        post(
            client,
            "agent-sessions",
            {"task_id": task["id"], "opportunity_id": opportunity["id"]},
        ).status_code
        == 422
    )
    blank = post(client, "agent-sessions", {"task_id": " ", "opportunity_id": None})
    assert blank.status_code == 422

    stranger_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=stranger_id, kind="human", display_name="Other synthetic owner"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(stranger_id, "other")
    private = post(client, "agent-sessions", {"task_id": task["id"], "opportunity_id": None})
    assert private.status_code == 404
    assert client.get("/api/v1/agent-sessions").json()["total"] == 0


def test_inactive_scope_is_rejected(client):
    task = post(client, "tasks", {"title": "Cancelled synthetic task"}).json()
    cancelled = client.patch(
        "/api/v1/tasks/" + task["id"],
        json={"state": "cancelled", "expected_version": task["row_version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert cancelled.status_code == 200, cancelled.text
    response = post(client, "agent-sessions", {"task_id": task["id"], "opportunity_id": None})
    assert response.status_code == 422


def test_messages_are_idempotent_and_share_one_active_root_run(client):
    task = post(client, "tasks", {"title": "Synthetic messaging task"}).json()
    conversation = create_session(client, task_id=task["id"])
    key = uuid4()

    first = post(
        client,
        f"agent-sessions/{conversation['id']}/messages",
        {"content": "Begin synthetic research.", "profile": "lead"},
        key,
    )
    assert first.status_code == 201, first.text
    replay = post(
        client,
        f"agent-sessions/{conversation['id']}/messages",
        {"content": "Begin synthetic research.", "profile": "lead"},
        key,
    )
    assert replay.json() == first.json()
    assert (
        post(
            client,
            f"agent-sessions/{conversation['id']}/messages",
            {"content": "Changed instruction.", "profile": "lead"},
            key,
        ).status_code
        == 409
    )

    second = post(
        client,
        f"agent-sessions/{conversation['id']}/messages",
        {"content": "Also compare the synthetic alternatives.", "profile": "lead"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["run_id"] == first.json()["run_id"]
    runs = client.get(f"/api/v1/agent-sessions/{conversation['id']}/runs").json()
    assert runs["total"] == 1
    messages = client.get(f"/api/v1/agent-sessions/{conversation['id']}/messages").json()
    assert [message["sequence"] for message in messages["items"]] == [1, 2]
    assert messages["total"] == 2


def test_active_run_rejects_profile_change_and_message_validation(client):
    task = post(client, "tasks", {"title": "Synthetic profile task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    assert post(client, path, {"content": "   ", "profile": "lead"}).status_code == 422
    assert post(client, path, {"content": "x" * 20001, "profile": "lead"}).status_code == 422
    assert post(client, path, {"content": "Start.", "profile": "lead"}).status_code == 201
    assert post(client, path, {"content": "Switch.", "profile": "writer"}).status_code == 409


def test_standalone_and_conversation_queues_share_profile_availability(client):
    missing_run = post(
        client,
        "agent-runs",
        {"prompt": "Synthetic standalone work.", "profile": "missing"},
    )
    assert missing_run.status_code == 422
    queued_run = post(
        client,
        "agent-runs",
        {"prompt": "Synthetic standalone work.", "profile": "lead"},
    )
    assert queued_run.status_code == 201, queued_run.text

    custom_model_run = post(
        client,
        "agent-runs",
        {
            "prompt": "Synthetic model test.",
            "profile": "lead",
            "provider": "openai",
            "model": "gpt-4o",
        },
    )
    assert custom_model_run.status_code == 201, custom_model_run.text

    task = post(client, "tasks", {"title": "Synthetic shared profile task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    assert post(client, path, {"content": "Missing.", "profile": "missing"}).status_code == 422
    queued_message = post(client, path, {"content": "Known.", "profile": "lead"})
    assert queued_message.status_code == 201, queued_message.text


@pytest.mark.parametrize(
    ("content", "profile"),
    [("   ", "lead"), ("Synthetic instruction.", "   ")],
)
def test_receive_rejects_blank_direct_input_before_advancing_sequence(
    client, engine, content, profile
):
    task = post(client, "tasks", {"title": "Synthetic direct validation task"}).json()
    conversation = create_session(client, task_id=task["id"])

    with Session(engine) as db, db.begin():
        persisted = db.get(AgentSession, UUID(conversation["id"]))
        assert persisted is not None
        with pytest.raises(ValueError, match="blank"):
            persisted.receive(
                content=content,
                profile=profile,
                configuration={},
                revision="synthetic",
                request_id=uuid4(),
            )
        assert persisted.last_sequence == 0


def test_receive_does_not_request_an_active_run_row_lock(client):
    task = post(client, "tasks", {"title": "Synthetic lock-order task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    assert post(client, path, {"content": "Begin.", "profile": "lead"}).status_code == 201

    def reject_inverted_lock_order(connection, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.upper().split())
        if "FROM AGENT_RUNS" in normalized and "STATE IN" in normalized:
            assert "FOR UPDATE" not in normalized

    event.listen(client.app.state.engine, "before_cursor_execute", reject_inverted_lock_order)
    try:
        response = post(
            client,
            path,
            {"content": "Arrive while the root run is active.", "profile": "lead"},
        )
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", reject_inverted_lock_order)

    assert response.status_code == 201, response.text


def test_expire_stale_uses_a_non_key_row_lock(client, engine):
    with Session(engine) as db, db.begin():
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=client.actor_id,
            prompt="Synthetic stale work",
            profile="lead",
            configuration={},
            revision="synthetic",
            request_id=uuid4(),
        )
        db.flush()
        claimed = AgentRun.claim(db, run.id)
        assert claimed is not None
        claimed.lease_expires_at = utc_now() - timedelta(seconds=1)

    statements = []

    def capture_reaper_lock(connection, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.upper().split())
        if "FROM AGENT_RUNS" in normalized and "LEASE_EXPIRES_AT" in normalized:
            statements.append(normalized)

    event.listen(engine, "before_cursor_execute", capture_reaper_lock)
    try:
        with Session(engine) as db, db.begin():
            AgentRun.expire_stale(db)
    finally:
        event.remove(engine, "before_cursor_execute", capture_reaper_lock)

    assert statements
    assert any("FOR NO KEY UPDATE SKIP LOCKED" in statement for statement in statements)


def test_receive_commits_while_actual_worker_lease_holds_the_run(client, engine):
    task = post(client, "tasks", {"title": "Synthetic leased race task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    first = post(client, path, {"content": "Begin.", "profile": "lead"}).json()
    run_id = UUID(first["run_id"])
    with Session(engine) as db, db.begin():
        claimed = AgentRun.claim(db, run_id)
        assert claimed is not None and claimed.lease_id is not None
        lease_id = claimed.lease_id

    run_locked = threading.Event()
    message_committed = threading.Event()
    worker_errors = []

    def finish_under_real_lease():
        try:
            with Session(engine) as db, db.begin():
                current = leased(db, run_id, lease_id)
                run_locked.set()
                message_committed.wait(timeout=2)
                current.finish("completed", output="Synthetic concurrent result.")
        except BaseException as exc:
            worker_errors.append(exc)

    worker = threading.Thread(target=finish_under_real_lease, daemon=True)
    worker.start()
    assert run_locked.wait(timeout=2)
    try:
        response = post(
            client,
            path,
            {"content": "Arrive while finish holds its lease.", "profile": "lead"},
        )
    finally:
        message_committed.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert worker_errors == []
    assert response.status_code == 201, response.text
    runs = client.get(f"/api/v1/agent-sessions/{conversation['id']}/runs").json()
    assert runs["total"] == 2
    assert runs["items"][0]["state"] == "queued"


def test_messages_use_ascending_after_sequence_pagination(client):
    task = post(client, "tasks", {"title": "Synthetic paginated task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    post(client, path, {"content": "First.", "profile": "lead"})
    post(client, path, {"content": "Second.", "profile": "lead"})

    page = client.get(
        f"/api/v1/agent-sessions/{conversation['id']}/messages",
        params={"after_sequence": 1, "limit": 1},
    ).json()
    assert page["total"] == 1
    assert [message["content"] for message in page["items"]] == ["Second."]
    assert (
        client.get(
            f"/api/v1/agent-sessions/{conversation['id']}/messages",
            params={"limit": 101},
        ).status_code
        == 422
    )


def test_finish_appends_visible_output_without_completing_task_and_continues_pending_work(
    client, engine
):
    task = post(client, "tasks", {"title": "Synthetic durable task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    first = post(client, path, {"content": "Begin the work.", "profile": "lead"}).json()

    with Session(engine) as db, db.begin():
        run = AgentRun.claim(db, first["run_id"])
        assert run is not None
        assert run.consumed_sequence == run.input_sequence == 1

    second = post(client, path, {"content": "Include the new constraint.", "profile": "lead"})
    assert second.status_code == 201, second.text
    with Session(engine) as db, db.begin():
        run = db.get(AgentRun, first["run_id"])
        assert run is not None
        run.finish("completed", output="Synthetic work is ready.")

    messages = client.get(f"/api/v1/agent-sessions/{conversation['id']}/messages").json()
    assert [(row["author"], row["sequence"]) for row in messages["items"]] == [
        ("user", 1),
        ("user", 2),
        ("assistant", 3),
    ]
    assert messages["items"][-1]["content"] == "Synthetic work is ready."
    runs = client.get(f"/api/v1/agent-sessions/{conversation['id']}/runs").json()
    assert runs["total"] == 2
    assert runs["items"][0]["state"] == "queued"
    with Session(engine) as db:
        continued = db.get(AgentRun, runs["items"][0]["id"])
        finished = db.get(AgentRun, first["run_id"])
        assert continued is not None and finished is not None
        assert continued.input_sequence == 2
        assert continued.config_snapshot == finished.config_snapshot
        persisted_task = db.get(Task, task["id"])
        assert persisted_task is not None and persisted_task.state == "open"


@pytest.mark.parametrize("terminal_state", ["failed", "cancelled"])
def test_unsuccessful_finish_does_not_silently_replay_pending_messages(
    client, engine, terminal_state
):
    task = post(client, "tasks", {"title": f"Synthetic {terminal_state} task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    first = post(client, path, {"content": "Begin.", "profile": "lead"}).json()
    with Session(engine) as db, db.begin():
        assert AgentRun.claim(db, first["run_id"]) is not None
    post(client, path, {"content": "Pending instruction.", "profile": "lead"})

    with Session(engine) as db, db.begin():
        run = db.get(AgentRun, first["run_id"])
        assert run is not None
        error_code = "synthetic_failure" if terminal_state == "failed" else None
        run.finish(terminal_state, error_code=error_code)

    assert client.get(f"/api/v1/agent-sessions/{conversation['id']}/runs").json()["total"] == 1
    assert client.get(f"/api/v1/agent-sessions/{conversation['id']}/messages").json()["total"] == 2


def test_database_rejects_cross_owner_scope_and_duplicate_message_sequence(client, engine):
    task = post(client, "tasks", {"title": "Database-owned synthetic task"}).json()
    conversation = create_session(client, task_id=task["id"])
    path = f"agent-sessions/{conversation['id']}/messages"
    message = post(client, path, {"content": "Synthetic constraint.", "profile": "lead"}).json()
    other_id = uuid4()

    with pytest.raises(IntegrityError), Session(engine) as db, db.begin():
        db.add(Actor(id=other_id, kind="human", display_name="Constraint owner"))
        db.flush()
        db.add(
            AgentSession(
                owner_id=other_id,
                title="Invalid owner",
                task_id=task["id"],
                opportunity_id=None,
            )
        )
        db.flush()

    with pytest.raises(IntegrityError), Session(engine) as db, db.begin():
        original = db.scalar(select(AgentMessage).where(AgentMessage.id == message["id"]))
        assert original is not None
        db.add(
            AgentMessage(
                owner_id=original.owner_id,
                session_id=original.session_id,
                run_id=original.run_id,
                sequence=original.sequence,
                author="user",
                profile="lead",
                content="Duplicate sequence.",
            )
        )
        db.flush()


def test_finish_is_single_use_for_visible_output(client, engine):
    task = post(client, "tasks", {"title": "Synthetic exactly-once task"}).json()
    conversation = create_session(client, task_id=task["id"])
    first = post(
        client,
        f"agent-sessions/{conversation['id']}/messages",
        {"content": "Finish once.", "profile": "lead"},
    ).json()
    with Session(engine) as db, db.begin():
        run = db.get(AgentRun, first["run_id"])
        assert run is not None
        run.finish("completed", output="One visible result.")
        with pytest.raises(RecordConflict):
            run.finish("completed", output="Duplicate result.")

    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentMessage)
                .where(
                    AgentMessage.session_id == conversation["id"],
                    AgentMessage.author == "assistant",
                )
            )
            == 1
        )
