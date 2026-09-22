"""Authentication, scoped MCP discovery, leases and synthetic Deep Agents execution."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile, load_profiles
from command_center.agents.tools import ToolRegistry
from command_center.core.capabilities import issue_run_token
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.models import Actor
from command_center.main import create_app


@pytest.fixture
def clerk_client(settings, engine, mocker):
    configured = settings.model_copy(
        update={"clerk_issuer": "https://synthetic.clerk.accounts.dev"}
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    mocker.patch(
        "command_center.core.identity.jwks_client",
        return_value=SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
        ),
    )
    with TestClient(create_app(configured)) as client:

        def token(**changes):
            now = utc_now()
            claims = {
                "iss": configured.clerk_issuer,
                "sub": "user_" + str(uuid4()),
                "sid": "sess_synthetic",
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(minutes=5),
                "azp": "http://localhost:3001",
            }
            claims.update(changes)
            return {"Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256")}

        yield client, token


def test_clerk_verified_identity_is_stable(clerk_client):
    client, token = clerk_client
    headers = token()
    first = client.get("/api/v1/me", headers=headers)
    assert first.status_code == 200, first.text
    assert client.get("/api/v1/me", headers=headers).json() == first.json()
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"azp": "https://attacker.example"},
        {"iss": "https://other.clerk.accounts.dev"},
        {"exp": utc_now() - timedelta(minutes=1)},
        {"sts": "pending"},
        {"sub": "service_synthetic"},
    ],
)
def test_clerk_invalid_session_rejected(clerk_client, changes):
    client, token = clerk_client
    assert client.get("/api/v1/me", headers=token(**changes)).status_code == 401


@pytest.fixture
def running(settings, engine):
    profile = AgentProfile(
        name="Synthetic",
        description="Test",
        model="synthetic",
        instructions="Use only test tools",
        tools=["create_task", "memory_read"],
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic agent owner")
        db.add(actor)
        db.flush()
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            prompt="Synthetic task",
            profile="test",
            configuration=profile.model_dump(),
            revision="test",
            request_id=uuid4(),
        )
        db.flush()
        assert AgentRun.claim(db, run.id)
        db.flush()
        yield_data = (run.id, run.lease_id)
    return yield_data


def test_agent_api_capability_replay_and_cancel(settings, engine, running):
    run_id, lease_id = running
    headers = {
        "Authorization": "Bearer " + issue_run_token(settings, run_id, lease_id),
        "Idempotency-Key": str(uuid4()),
    }
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/memories", headers=headers).status_code == 200
        assert client.get("/api/v1/companies", headers=headers).status_code == 403
        first = client.post(
            "/api/v1/tasks", json={"title": "Synthetic agent task"}, headers=headers
        )
        assert first.status_code == 201, first.text
        assert (
            client.post(
                "/api/v1/tasks", json={"title": "Synthetic agent task"}, headers=headers
            ).json()
            == first.json()
        )
        with Session(engine) as db, db.begin():
            db.get(AgentRun, run_id).finish("cancelled")
        assert client.get("/api/v1/memories", headers=headers).status_code == 401


def test_mcp_discovery_is_scoped_and_token_audiences_are_separate(
    settings, engine, running, mocker
):
    run_id, lease_id = running
    mcp_headers = {
        "Authorization": "Bearer "
        + issue_run_token(settings, run_id, lease_id, audience="command-center-mcp"),
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/memories", headers=mcp_headers).status_code == 401
        result = client.post(
            "/mcp/", headers=mcp_headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert result.status_code == 200, result.text
        assert {t["name"] for t in result.json()["result"]["tools"]} == {
            "create_task",
            "memory_read",
        }
        assert client.post("/mcp/", json={}).status_code == 401
        api_headers = {
            **mcp_headers,
            "Authorization": "Bearer " + issue_run_token(settings, run_id, lease_id),
        }
        assert client.post("/mcp/", headers=api_headers, json={}).status_code == 401
        denied = client.post(
            "/mcp/",
            headers={**mcp_headers, "X-Tool-Call-ID": "call_1"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "draft_artifact", "arguments": {}},
            },
        )
        assert "Denied" in denied.text, denied.text
        request = mocker.patch.object(ToolRegistry, "request", return_value={"id": "synthetic"})
        result = client.post(
            "/mcp/",
            headers={**mcp_headers, "X-Tool-Call-ID": "call_2"},
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "create_task", "arguments": {"title": "Test task"}},
            },
        )
        assert "synthetic" in result.text, result.text
        request.assert_called_once_with("POST", "tasks", {"title": "Test task"})
        with Session(engine) as db, db.begin():
            db.get(AgentRun, run_id).finish("cancelled")
        assert (
            client.post(
                "/mcp/",
                headers=mcp_headers,
                json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            ).status_code
            == 401
        )


def test_duplicate_delivery_and_expired_lease_do_not_restart(engine, running):
    run_id, _ = running
    with Session(engine) as db, db.begin():
        assert AgentRun.claim(db, run_id) is None
        run = db.get(AgentRun, run_id)
        run.lease_expires_at = utc_now() - timedelta(seconds=1)
    with Session(engine) as db, db.begin():
        AgentRun.expire_stale(db)
        assert db.get(AgentRun, run_id).error_code == "worker_interrupted"
        assert AgentRun.claim(db, run_id) is None


def test_profiles_pin_skills_separately_from_directives():
    profiles, revision = load_profiles("agents/profiles.toml")
    profile = profiles["research"]
    assert revision and profile.skill_files["research"]
    assert profile.skill_files["research"] not in profile.instructions
    assert profiles["lead"].specialists["research"] == profile


def test_worker_uses_real_mcp_discovery_and_api_with_mocked_model(
    agent_server,
    engine,
    mocker,
    scripted_model,
):
    """Only paid generation is mocked; MCP, HTTP authorization and SQL writes are real."""
    from sqlalchemy import select

    from command_center.agents.worker import perform_next
    from command_center.db.models import Task

    profile = AgentProfile(
        name="Test",
        description="Test",
        model="gpt-5-mini",
        instructions="Synthetic test only",
        tools=["create_task"],
        max_steps=3,
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic worker owner")
        db.add(actor)
        db.flush()
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            prompt="Create a synthetic task",
            profile="test",
            configuration=profile.model_dump(),
            revision="test",
            request_id=uuid4(),
        )
        db.flush()
        run_id, actor_id = run.id, actor.id
    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_task",
                        "args": {"title": "MCP integration task"},
                        "id": "call_mcp_test",
                    }
                ],
            ),
            AIMessage(content="Created the task."),
        ]
    )
    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        completed = db.get(AgentRun, run_id)
        assert completed.state == "completed", completed.error_code
        assert completed.output == "Created the task."
        assert completed.tool_steps()[0]["state"] == "output-available"
        assert completed.tool_steps()[0]["id"] == "call_mcp_test"
        assert (
            db.scalar(select(Task).where(Task.owner_id == actor_id)).title == "MCP integration task"
        )
    assert not perform_next(engine, agent_server, run_id)
