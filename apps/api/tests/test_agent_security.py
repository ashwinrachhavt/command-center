"""Authentication, scoped MCP discovery, leases and synthetic Deep Agents execution."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr
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
def running(settings, engine, request):
    profile = AgentProfile(
        name="Synthetic",
        description="Test",
        model="synthetic",
        instructions="Use only test tools",
        tools=getattr(request, "param", ["create_task", "memory_read"]),
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
        assert client.get("/api/v1/memories/retrieve", headers=headers).status_code == 200
        assert client.get("/api/v1/memories", headers=headers).status_code == 403
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
        assert client.get("/api/v1/memories/retrieve", headers=headers).status_code == 401


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
        assert client.get("/api/v1/memories/retrieve", headers=mcp_headers).status_code == 401
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


@pytest.mark.parametrize("running", [["connected_context"]], indirect=True)
def test_connected_context_grant_does_not_grant_mail_or_external_changes(settings, engine, running):
    run_id, lease_id = running
    mcp_headers = {
        "Authorization": "Bearer "
        + issue_run_token(settings, run_id, lease_id, audience="command-center-mcp"),
        "Accept": "application/json, text/event-stream",
    }
    api_headers = {
        "Authorization": "Bearer " + issue_run_token(settings, run_id, lease_id),
        "Idempotency-Key": str(uuid4()),
    }
    with TestClient(create_app(settings)) as client:
        discovered = client.post(
            "/mcp/", headers=mcp_headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert discovered.status_code == 200, discovered.text
        tools = discovered.json()["result"]["tools"]
        assert [tool["name"] for tool in tools] == ["connected_context"]
        assert tools[0]["annotations"]["readOnlyHint"] is True
        assert tools[0]["annotations"]["openWorldHint"] is True
        for path in (
            "gmail/search",
            "integrations/composio/accounts/sync",
            "reviewed-actions",
        ):
            denied = client.post(f"/api/v1/{path}", headers=api_headers, json={})
            assert denied.status_code == 403, denied.text
        unscoped = client.post(
            "/api/v1/integrations/composio/context",
            headers=api_headers,
            json={
                "account_id": str(uuid4()),
                "query": {"kind": "notion_page", "page_id": str(uuid4())},
            },
        )
        assert unscoped.status_code == 403, unscoped.text
        assert unscoped.json() == {"detail": "Agent run has no owned work scope"}


@pytest.mark.parametrize("running", [["gmail_search"]], indirect=True)
def test_even_a_legacy_mail_tool_grant_requires_an_explicit_human_pull(settings, running):
    run_id, lease_id = running
    headers = {
        "Authorization": "Bearer " + issue_run_token(settings, run_id, lease_id),
        "Idempotency-Key": str(uuid4()),
    }
    with TestClient(create_app(settings)) as client:
        denied = client.post(
            "/api/v1/gmail/search",
            headers=headers,
            json={"query": "from:synthetic@example.test", "max_results": 1},
        )
    assert denied.status_code == 403, denied.text
    assert "Pull email explicitly" in denied.json()["detail"]


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


@pytest.mark.parametrize("routing_started", [False, True])
def test_worker_uses_real_mcp_discovery_and_api_with_mocked_model(
    agent_server,
    engine,
    mocker,
    scripted_model,
    routing_started,
):
    """Only paid generation is mocked; MCP, HTTP authorization and SQL writes are real."""
    from sqlalchemy import select

    from command_center.agents.worker import perform_next
    from command_center.db.models import Task
    from command_center.db.spending import SpendingPolicy, SpendingRateCard

    profile = AgentProfile(
        name="Test",
        description="Test",
        model="gpt-5-mini",
        instructions="Synthetic test only",
        tools=["create_task"],
        max_steps=3,
        jev_routing=True,
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic worker owner")
        db.add(actor)
        db.flush()
        card = SpendingRateCard.create(
            db,
            owner_id=actor.id,
            name="Synthetic worker rates",
            source_label="Synthetic test fixture",
            rates={
                "models": [
                    {
                        "provider": profile.provider,
                        "model": profile.model,
                        "input_per_million_micros": 0,
                        "output_per_million_micros": 0,
                        "fixed_micros": 1,
                    }
                ],
                "tools": [],
            },
            request_id=uuid4(),
        )
        SpendingPolicy.configure(
            db,
            owner_id=actor.id,
            rate_card_id=card.id,
            monthly_limit_micros=1_000_000,
            default_work_limit_micros=1_000_000,
            active=True,
            request_id=uuid4(),
            expected_version=None,
        )
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
        if routing_started:
            run.checkpoint = {"routing": {"status": "started"}}
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
    agent_server = agent_server.model_copy(
        update={
            "jev_enabled": True,
            "jev_api_key": SecretStr("synthetic-jev-key"),
        }
    )

    async def routed(*args):
        with Session(engine) as db:
            assert db.get(AgentRun, run_id).checkpoint["routing"]["status"] == "started"
        return {"status": "suggested", "hint": "Discover create task", "route": "crm"}

    router = mocker.patch("command_center.agents.worker.suggest_route", side_effect=routed)
    factory = mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, run_id)
    assert factory.call_args.kwargs["http_async_client"].is_closed
    with Session(engine) as db:
        completed = db.get(AgentRun, run_id)
        assert completed.state == "completed", completed.error_code
        assert completed.output == "Created the task."
        assert completed.checkpoint["routing"]["status"] == (
            "started" if routing_started else "suggested"
        )
        assert completed.tool_steps()[0]["state"] == "output-available"
        assert completed.tool_steps()[0]["id"] == "call_mcp_test"
        assert (
            db.scalar(select(Task).where(Task.owner_id == actor_id)).title == "MCP integration task"
        )
    assert not perform_next(engine, agent_server, run_id)

    assert router.await_count == (0 if routing_started else 1)


@pytest.mark.parametrize("running", [["catalog_search", "catalog_execute"]], indirect=True)
@pytest.mark.parametrize("steering", [False, True])
def test_explicit_chat_mail_pull_reuses_scoped_session_and_rejects_foreign_input(
    settings, engine, running, mocker, steering
):
    from sqlalchemy import select

    from command_center.db.conversations import AgentMessage, AgentSession
    from command_center.db.reviewed_actions import ExternalAccount, ProviderObservation
    from command_center.integrations.composio_actions import (
        AccountMetadata,
        ComposioActionClient,
        VerifiedIdentity,
    )

    run_id, lease_id = running
    with Session(engine) as db, db.begin():
        run = db.get(AgentRun, run_id)
        run.prompt = "Read Gmail from Synthetic Jordan and create a lead and contact"
        conversation = AgentSession.for_run(db, run=run, request_id=uuid4())
        owner_id = run.owner_id
        message_id = db.scalar(select(AgentMessage.id).where(AgentMessage.run_id == run.id))
        if steering:
            message_id = conversation.receive(
                content="Read Gmail from Synthetic Jordan and create a contact",
                profile=run.profile,
                configuration=run.config_snapshot["profile"],
                revision=run.config_snapshot["revision"],
                request_id=uuid4(),
            ).id
        account = ExternalAccount(
            id=uuid4(),
            owner_id=owner_id,
            toolkit="gmail",
            composio_connected_account_id="ca_synthetic_mail",
            composio_auth_config_id="ac_synthetic_mail",
            display_name="Synthetic Gmail",
            provider_identity={"email": "owner@example.test"},
            connection_status="ACTIVE",
            selected_purpose="outreach",
            identity_verified_at=utc_now(),
        )
        db.add(account)
    metadata = AccountMetadata(
        "ca_synthetic_mail",
        "gmail",
        "ac_synthetic_mail",
        "ACTIVE",
        False,
        None,
        {"email": "owner@example.test"},
    )
    adapter = ComposioActionClient(api_key="synthetic")
    mocker.patch.object(adapter, "account_metadata", return_value=metadata)
    mocker.patch.object(
        adapter,
        "verify_identity",
        return_value=VerifiedIdentity("Synthetic Gmail", {"email": "owner@example.test"}),
    )
    create = mocker.patch.object(adapter, "create_gmail_session", return_value="session-synthetic")
    search = mocker.patch.object(
        adapter,
        "gmail_search",
        return_value={
            "messages": [{"sender": "jordan@example.test", "messageText": "Synthetic lead"}],
            "next_page_token": None,
            "result_size_estimate": 1,
        },
    )
    headers = {"Authorization": "Bearer " + issue_run_token(settings, run_id, lease_id)}
    body = {"query": "from:jordan@example.test", "request_message_id": str(message_id)}
    with TestClient(create_app(settings)) as client:
        client.app.state.composio_actions = adapter
        if steering:
            unread = client.post(
                "/api/v1/gmail/search",
                headers=headers | {"Idempotency-Key": str(uuid4())},
                json=body,
            )
            assert unread.status_code == 403, unread.text
            search.assert_not_called()
            create.assert_not_called()
            with Session(engine) as db, db.begin():
                # The worker persists this cursor before invoking tools planned
                # from the newly consumed steering message.
                db.get(AgentRun, run_id).consumed_sequence = db.get(
                    AgentMessage, message_id
                ).sequence
        key = str(uuid4())
        first = client.post(
            "/api/v1/gmail/search", headers=headers | {"Idempotency-Key": key}, json=body
        )
        assert first.status_code == 200, first.text
        replay = client.post(
            "/api/v1/gmail/search", headers=headers | {"Idempotency-Key": key}, json=body
        )
        assert replay.json() == first.json()
        second = client.post(
            "/api/v1/gmail/search", headers=headers | {"Idempotency-Key": str(uuid4())}, json=body
        )
        assert second.status_code == 200, second.text
        assert create.call_count == 1
        assert search.call_count == 2
        assert all(
            call.kwargs["session_id"] == "session-synthetic" for call in search.call_args_list
        )
        with Session(engine) as db, db.begin():
            run = db.get(AgentRun, run_id)
            conversation = db.get(AgentSession, run.session_id)
            future = conversation.receive(
                content="Another unread request",
                profile=run.profile,
                configuration=run.config_snapshot["profile"],
                revision=run.config_snapshot["revision"],
                request_id=uuid4(),
            )
            future_id = future.id
        for request_message_id in (None, str(uuid4()), str(future_id)):
            denied = client.post(
                "/api/v1/gmail/search",
                headers=headers | {"Idempotency-Key": str(uuid4())},
                json=body | {"request_message_id": request_message_id},
            )
            assert denied.status_code == 403, denied.text
        assert search.call_count == 2
    with Session(engine) as db:
        assert (
            len(
                db.scalars(
                    select(ProviderObservation).where(ProviderObservation.owner_id == owner_id)
                ).all()
            )
            == 2
        )
