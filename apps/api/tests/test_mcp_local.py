"""Real local HTTP/stdio transports and synthetic actor-bound capability checks."""

import asyncio
import json
import os
import sys
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.agents.local_mcp import configure
from command_center.agents.mcp_policy import POLICIES, coverage, local_api_allowed
from command_center.core.capabilities import issue_run_token
from command_center.core.local_credentials import issue_client_api_token
from command_center.db.agents import AgentRun
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.base import utc_now
from command_center.db.crm import Company
from command_center.db.mcp_clients import MCPClientCredential
from command_center.db.models import Actor, AuditEvent, Task
from command_center.main import create_app


@pytest.fixture
def local_client(engine):
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic MCP owner")
        db.add(actor)
        db.flush()
        credential, token = MCPClientCredential.provision(db, actor.id, "Synthetic CLI", 7, uuid4())
        return actor.id, credential.id, token


def headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}


def rpc(client, token, name, arguments):
    response = client.post(
        "/mcp/",
        headers=headers(token),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    text = response.json()["result"]["content"][0]["text"]
    try:
        return json.loads(text)
    except ValueError:
        return text


def test_inventory_is_complete_and_unknown_routes_fail_closed(settings):
    app = create_app(settings)
    inventory = coverage(app.openapi())
    assert len(inventory) >= 191
    assert not [entry for entry in inventory if entry["policy"] == "unclassified"]
    assert len({entry["name"] for entry in inventory}) == len(inventory)
    assert not local_api_allowed("POST", "/api/v1/unknown")
    for operation, policy in POLICIES.items():
        if policy["policy"] in {"human", "runtime", "transport"}:
            method, path = operation.split(" ", 1)
            assert not local_api_allowed(method, path), operation


def test_provision_list_revoke_requires_human_and_never_lists_secrets(settings, engine):
    config = settings.model_copy(update={"auth_mode": "local"})
    human = {"Authorization": "Bearer " + config.api_token.get_secret_value()}
    with TestClient(create_app(config)) as client:
        created = client.post(
            "/api/v1/mcp-clients", headers=human, json={"name": "Synthetic setup"}
        )
        assert created.status_code == 201, created.text
        record = created.json()
        assert record["token"].startswith("cc_local.")
        assert "token_hash" not in record
        listed = client.get("/api/v1/mcp-clients", headers=human)
        assert listed.status_code == 200
        assert record["token"] not in listed.text and "token_hash" not in listed.text
        jwt = issue_client_api_token(config, UUID(record["id"]))
        denied = client.post("/api/v1/mcp-clients", headers=headers(jwt), json={"name": "Denied"})
        assert denied.status_code == 403
        revoked = client.post(f"/api/v1/mcp-clients/{record['id']}/revoke", headers=human)
        assert revoked.status_code == 200 and revoked.json()["revoked_at"]
        assert record["token"] not in revoked.text
        denied = client.post("/mcp/", headers=headers(record["token"]), json={})
        assert denied.status_code == 401


def test_client_audience_revocation_and_actor_isolation(settings, engine, local_client):
    actor_id, client_id, token = local_client
    jwt = issue_client_api_token(settings, client_id)
    with Session(engine) as db, db.begin():
        other = Actor(id=uuid4(), kind="human", display_name="Other synthetic MCP actor")
        db.add(other)
        db.flush()
        company = Company(id=uuid4(), owner_id=other.id, name="Unrelated synthetic company")
        db.add(company)
        db.flush()
        other_company_id = company.id
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/companies", headers=headers(token)).status_code == 401
        assert client.post("/mcp/", headers=headers(jwt), json={}).status_code == 401
        assert (
            client.get(f"/api/v1/companies/{other_company_id}", headers=headers(jwt)).status_code
            == 404
        )
        assert client.get("/api/v1/companies", headers=headers(jwt)).status_code == 200
        with Session(engine) as db, db.begin():
            MCPClientCredential.active(db, client_id).revoke(db, uuid4())
        assert client.get("/api/v1/companies", headers=headers(jwt)).status_code == 401
        assert client.post("/mcp/", headers=headers(token), json={}).status_code == 401


def test_expired_or_inactive_local_client_denied(settings, engine, local_client):
    actor_id, client_id, token = local_client
    with Session(engine) as db, db.begin():
        db.get(MCPClientCredential, client_id).expires_at = utc_now() - timedelta(seconds=1)
    with TestClient(create_app(settings)) as client:
        assert client.post("/mcp/", headers=headers(token), json={}).status_code == 401
    with Session(engine) as db, db.begin():
        db.get(MCPClientCredential, client_id).expires_at = utc_now() + timedelta(days=1)
        db.get(Actor, actor_id).active = False
    with TestClient(create_app(settings)) as client:
        assert client.post("/mcp/", headers=headers(token), json={}).status_code == 401


def test_local_human_review_is_guidance_and_api_cannot_approve(settings, engine, local_client):
    _, client_id, token = local_client
    jwt = issue_client_api_token(settings, client_id)
    with TestClient(create_app(settings)) as client:
        response = rpc(client, token, "cc_profile_facts_review_fact", {})
        assert response["status"] == "human_required" and response["executed"] is False
        for path in [
            f"profile/facts/{uuid4()}/reviews",
            f"memories/{uuid4()}/reviews",
            f"versions/{uuid4()}/reviews",
            f"reviewed-actions/{uuid4()}/reviews",
        ]:
            assert client.post(f"/api/v1/{path}", headers=headers(jwt), json={}).status_code == 403
        assert (
            client.post(
                "/api/v1/memories", headers=headers(jwt), json={"confirm": True}
            ).status_code
            == 403
        )
        context = rpc(client, token, "memory_append", {})
        assert context["status"] == "context_required"
        assert "cc_conversations_receive_message" in context["next_step"]


def test_http_local_typed_crm_retry_and_audit(agent_server, engine, local_client):
    actor_id, _, token = local_client
    with httpx.Client(base_url=agent_server.internal_api_url, trust_env=False) as http:
        tools = http.post(
            "/mcp/",
            headers=headers(token),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert tools.status_code == 200, tools.text
        names = {tool["name"]: tool for tool in tools.json()["result"]["tools"]}
        assert {
            "create_task",
            "cc_workspace_create_company",
            "catalog_search",
            "catalog_execute",
        } <= names.keys()
        assert "operation_id" in names["cc_workspace_create_company"]["inputSchema"]["required"]
        arguments = {"body": {"name": "Synthetic local company"}, "operation_id": "company-1"}
        first = rpc(http, token, "cc_workspace_create_company", arguments)
        assert first["name"] == "Synthetic local company", first
        assert rpc(http, token, "cc_workspace_create_company", arguments)["id"] == first["id"]
        conflicting = rpc(
            http, token, "cc_workspace_create_company", {**arguments, "body": {"name": "Different"}}
        )
        assert conflicting["status_code"] == 409 and "operation ID" in conflicting["error"]
        missing = rpc(http, token, "create_task", {"title": "No receipt"})
        assert "stable tool-call ID" in missing
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count()).select_from(Company).where(Company.owner_id == actor_id)
                )
                == 1
            )
            event = db.scalar(
                select(AuditEvent).where(
                    AuditEvent.actor_id == actor_id, AuditEvent.action == "companies.created"
                )
            )
            assert event.details["initiator"] == "local_mcp"


def test_shared_http_catalog_captures_linked_private_lead(agent_server, engine, local_client):
    actor_id, _, token = local_client
    original = "  Morgan at Cedar Studio needs a design partner.\n"
    arguments = {
        "operation_id": "synthetic-lead-1",
        "body": {
            "title": "Design partnership",
            "company_name": "Cedar Studio",
            "company_domain": "cedar.example",
            "contact": {"name": "Morgan", "email": "morgan@cedar.example"},
            "source_text": original,
        },
    }
    with httpx.Client(base_url=agent_server.internal_api_url, trust_env=False) as http:
        saved = rpc(http, token, "capture_lead_content", arguments)
        assert saved["contact_id"] and saved["opportunity_id"], saved
        assert saved["job_id"] is None
        assert rpc(http, token, "capture_lead_content", arguments) == saved
        assert saved["links"]["opportunity"].startswith("/opportunities?inspect=")
    with Session(engine) as db:
        version = db.get(ArtifactVersion, UUID(saved["source"]["version_id"]))
        artifact = db.get(Artifact, version.artifact_id)
        assert artifact.owner_id == actor_id and artifact.sensitivity == "private"
        assert version.payload["text"] == original


def test_real_stdio_discovery_and_call(agent_server, engine, local_client, tmp_path):
    _, _, token = local_client
    token_file = tmp_path / "client-token"
    token_file.write_text(token)
    token_file.chmod(0o600)

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "command_center.agents.local_mcp",
                "serve",
                "--url",
                agent_server.internal_api_url + "/mcp/",
                "--token-file",
                str(token_file),
            ],
            env={**os.environ, "CC_DATABASE_URL": "invalid-no-database-access-required"},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            discovered = await client.list_tools()
            assert "create_task" in {tool.name for tool in discovered.tools}
            result = await client.call_tool(
                "create_task", {"title": "Synthetic stdio task", "operation_id": "stdio-task"}
            )
            assert not result.isError, result
            saved = json.loads(result.content[0].text)
            assert saved["title"] == "Synthetic stdio task"

    asyncio.run(run())


def test_parallel_local_calls_keep_actor_and_retry_identity(agent_server, engine, local_client):
    actor_id, _, token = local_client
    with Session(engine, expire_on_commit=False) as db, db.begin():
        other = Actor(id=uuid4(), kind="human", display_name="Concurrent synthetic actor")
        db.add(other)
        db.flush()
        _, other_token = MCPClientCredential.provision(db, other.id, "Parallel CLI", 7, uuid4())
        other_id = other.id

    async def call(credential, title):
        async with (
            streamablehttp_client(
                agent_server.internal_api_url + "/mcp/", headers=headers(credential)
            ) as (read, write, _),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool(
                "create_task", {"title": title, "operation_id": "shared-operation-label"}
            )
            return json.loads(result.content[0].text)

    async def parallel():
        return await asyncio.gather(
            call(token, "Owner A"), call(other_token, "Owner B"), call(token, "Owner A")
        )

    first, second, replay = asyncio.run(parallel())
    assert first["id"] == replay["id"] != second["id"]
    with Session(engine) as db:
        assert db.get(Task, UUID(first["id"])).owner_id == actor_id
        assert db.get(Task, UUID(second["id"])).owner_id == other_id


def test_progressive_catalog_preserves_grants_and_executes_owned_writes(agent_server, engine):
    profile = AgentProfile(
        name="Catalog lead",
        description="Synthetic",
        model="synthetic",
        instructions="Synthetic",
        tools=["catalog_search", "catalog_execute"],
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic catalog owner")
        db.add(actor)
        db.flush()
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            prompt="Synthetic",
            profile="test",
            configuration=profile.model_dump(),
            revision="test",
            request_id=uuid4(),
        )
        db.flush()
        AgentRun.claim(db, run.id)
        db.flush()
        token = issue_run_token(agent_server, run.id, run.lease_id, audience="command-center-mcp")
    with httpx.Client(
        base_url=agent_server.internal_api_url,
        headers={"X-Tool-Call-ID": "catalog-call"},
        trust_env=False,
    ) as http:
        tools = http.post(
            "/mcp/",
            headers=headers(token),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert {entry["name"] for entry in tools.json()["result"]["tools"]} == {
            "catalog_search",
            "catalog_execute",
        }
        found = rpc(http, token, "catalog_search", {"query": "create company"})
        assert any(item["name"] == "cc_workspace_create_company" for item in found["items"])
        saved = rpc(
            http,
            token,
            "catalog_execute",
            {
                "tool_name": "cc_workspace_create_company",
                "arguments": {"body": {"name": "Synthetic progressive company"}},
            },
        )
        assert saved["name"] == "Synthetic progressive company", saved
        denied = rpc(
            http,
            token,
            "catalog_execute",
            {"tool_name": "unrestricted_http", "arguments": {"path": "/me"}},
        )
        assert "Denied" in denied["message"]
        human = rpc(
            http,
            token,
            "catalog_execute",
            {"tool_name": "cc_profile_facts_review_fact", "arguments": {}},
        )
        assert human["status"] == "human_required"


def test_configure_uses_hidden_prompt_and_private_file(tmp_path, mocker):
    token_file = tmp_path / "config" / "token"
    prompt = mocker.patch("getpass.getpass", return_value="cc_local.synthetic.synthetic-value")
    configure(token_file)
    prompt.assert_called_once()
    assert token_file.stat().st_mode & 0o777 == 0o600
    assert token_file.read_text().strip() == "cc_local.synthetic.synthetic-value"
