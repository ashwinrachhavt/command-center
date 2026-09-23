"""Record agent work creates canonical tasks and attaches exact outputs without sends."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.core.capabilities import issue_run_token
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.artifacts import TaskArtifact
from command_center.db.correspondence import FollowUp
from command_center.db.models import Actor, Task
from command_center.db.reviewed_actions import ReviewedAction
from command_center.main import create_app


@pytest.fixture
def work_client(settings, engine, mocker):
    owner = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner, kind="human", display_name="Synthetic record work owner"))
    profile = AgentProfile(
        name="Synthetic record specialist",
        description="Synthetic",
        model="synthetic",
        instructions="Use synthetic evidence",
        tools=["record_work_context", "save_record_work"],
    )
    mocker.patch(
        "command_center.api.record_work.available_profile", return_value=(profile, "synthetic")
    )
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner, "synthetic")
    with TestClient(app) as client:
        client.actor_id = owner
        yield client


def post(client, route, body, key=None, token=None):
    headers = {"Idempotency-Key": str(key or uuid4())}
    if token:
        headers["Authorization"] = "Bearer " + token
    return client.post(f"/api/v1/{route}", json=body, headers=headers)


def claim(client, engine, settings, work):
    with Session(engine, expire_on_commit=False) as db, db.begin():
        run = AgentRun.claim(db, UUID(work["run_id"]))
        assert run is not None
        token = issue_run_token(settings, run.id, run.lease_id)
    client.app.dependency_overrides.pop(authenticate)
    return token


def test_requested_follow_up_is_one_task_and_one_scoped_saved_draft(work_client, settings, engine):
    contact = post(
        work_client,
        "contacts",
        {
            "name": "Synthetic Taylor",
            "email": "taylor@example.com",
            "notes": "Discuss the infrastructure role",
        },
    ).json()
    route = f"record-work/contacts/{contact['id']}"
    key = uuid4()
    response = post(work_client, route, {"instructions": "Be concise", "channel": "email"}, key)
    assert response.status_code == 201, response.text
    work = response.json()
    assert (
        post(work_client, route, {"instructions": "Be concise", "channel": "email"}, key).json()
        == work
    )
    assert post(work_client, route, {}).json()["task_id"] == work["task_id"]
    assert work_client.get(f"/api/v1/{route}").json()[0] == work
    token = claim(work_client, engine, settings, work)
    context = work_client.get(
        f"/api/v1/tasks/{work['task_id']}/record-work/context",
        headers={"Authorization": "Bearer " + token},
    )
    assert context.status_code == 200, context.text
    assert context.json()["record"]["notes"] == "Discuss the infrastructure role"
    output_route = f"tasks/{work['task_id']}/record-work/output"
    body = {
        "text": "Hi Taylor, could we explore the infrastructure role?",
        "subject": "Infrastructure conversation",
    }
    output_key = uuid4()
    saved = post(work_client, output_route, body, output_key, token)
    assert saved.status_code == 200, saved.text
    assert post(work_client, output_route, body, output_key, token).json() == saved.json()
    assert post(work_client, output_route, body, token=token).status_code == 409
    with Session(engine) as db:
        assert db.get(Task, UUID(work["task_id"])).state == "done"
        facet = db.get(FollowUp, UUID(saved.json()["output_artifact_id"]))
        assert facet.contact_id == UUID(contact["id"])
        assert db.get(TaskArtifact, (UUID(work["task_id"]), facet.artifact_id))
        assert (
            db.scalar(
                select(func.count())
                .select_from(ReviewedAction)
                .where(ReviewedAction.owner_id == work_client.actor_id)
            )
            == 0
        )
    assert (
        work_client.get(
            f"/api/v1/tasks/{uuid4()}/record-work/context",
            headers={"Authorization": "Bearer " + token},
        ).status_code
        == 403
    )
    assert post(work_client, route, {}, token=token).status_code == 403


def test_company_output_needs_public_evidence_and_cancelled_runs_cannot_write(
    work_client, settings, engine
):
    company = post(
        work_client,
        "companies",
        {"name": "Synthetic Example", "description": "Keep my own context"},
    ).json()
    work = post(work_client, f"record-work/companies/{company['id']}", {}).json()
    token = claim(work_client, engine, settings, work)
    route = f"tasks/{work['task_id']}/record-work/output"
    assert post(work_client, route, {"text": "Uncited claims"}, token=token).status_code == 422
    with Session(engine) as db, db.begin():
        db.get(AgentRun, UUID(work["run_id"])).finish("cancelled")
    assert post(work_client, route, {"text": "Late output"}, token=token).status_code == 401


def test_cited_company_brief_appears_on_company_without_overwriting_manual_context(
    work_client, settings, engine
):
    from command_center.db.artifacts import Artifact, ArtifactVersion
    from command_center.db.evidence import SourceRecord

    company = post(
        work_client,
        "companies",
        {"name": "Synthetic Example", "domain": "example.com", "description": "My company notes"},
    ).json()
    work = post(work_client, f"record-work/companies/{company['id']}", {}).json()
    source_url = "https://example.com/careers"
    with Session(engine) as db, db.begin():
        artifact = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=work_client.actor_id,
            title="Synthetic careers evidence",
            kind="source",
            sensitivity="public",
            text="The synthetic careers page lists platform engineering roles.",
            document_type_id=None,
            request_id=uuid4(),
        )
        version = db.scalar(
            select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
        )
        source_id = str(version.id)
        db.add(
            SourceRecord(
                artifact_version_id=version.id,
                provider="synthetic",
                account_scope="public",
                locator=source_url,
                extraction_method="synthetic_fixture",
            )
        )
    token = claim(work_client, engine, settings, work)
    saved = post(
        work_client,
        f"tasks/{work['task_id']}/record-work/output",
        {
            "text": (
                "# Company brief\n\nBuilds infrastructure; platform roles are listed.\n\n"
                f"[Careers]({source_url})\n\nEligibility and exact fit still need review."
            ),
            "source_version_ids": [source_id],
        },
        token=token,
    )
    assert saved.status_code == 200, saved.text
    work_client.app.dependency_overrides[authenticate] = lambda: Identity(
        work_client.actor_id, "synthetic"
    )
    row = work_client.get(f"/api/v1/companies/{company['id']}").json()
    assert (
        row["description"] == company["description"]
        and row["row_version"] == company["row_version"]
    )
    assert row["latest_research"]["summary"] == "Builds infrastructure; platform roles are listed."
    assert row["latest_research"]["version_id"] == saved.json()["output_version_id"]
    listed = work_client.get("/api/v1/companies").json()["items"]
    assert (
        next(item for item in listed if item["id"] == company["id"])["latest_research"]
        == row["latest_research"]
    )
    output = work_client.get(
        f"/api/v1/artifacts/{saved.json()['output_artifact_id']}/versions/{saved.json()['output_version_id']}"
    ).json()
    assert output["input_version_ids"] == [source_id]
    assert source_url in output["payload"]["text"]

    # Several unsuccessful refreshes retain the last useful brief.
    with Session(engine) as db, db.begin():
        db.get(AgentRun, UUID(work["run_id"])).finish("completed")
    for _ in range(6):
        refresh = post(work_client, f"record-work/companies/{company['id']}", {}).json()
        with Session(engine) as db, db.begin():
            db.get(AgentRun, UUID(refresh["run_id"])).finish("failed", error_code="synthetic")
    recent = work_client.get(f"/api/v1/record-work/companies/{company['id']}").json()
    assert len(recent) == 6
    assert recent[0]["state"] == "failed"
    assert recent[-1]["output_version_id"] == output["id"]
    with Session(engine) as db, db.begin():
        db.get(Artifact, UUID(saved.json()["output_artifact_id"])).archive(request_id=uuid4())
    assert work_client.get(f"/api/v1/companies/{company['id']}").json()["latest_research"] is None
    assert len(work_client.get(f"/api/v1/record-work/companies/{company['id']}").json()) == 5


def test_record_work_mcp_tools_dispatch_only_to_scoped_endpoints(
    work_client, settings, engine, mocker
):
    from command_center.agents.tools import ToolRegistry

    person = post(work_client, "contacts", {"name": "Synthetic person"}).json()
    work = post(work_client, f"record-work/contacts/{person['id']}", {}).json()
    claim(work_client, engine, settings, work)
    with Session(engine) as db:
        run = db.get(AgentRun, UUID(work["run_id"]))
        mcp_token = issue_run_token(settings, run.id, run.lease_id, audience="command-center-mcp")
    headers = {
        "Authorization": "Bearer " + mcp_token,
        "Accept": "application/json, text/event-stream",
    }
    discovered = work_client.post(
        "/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert discovered.status_code == 200, discovered.text
    tools = {tool["name"]: tool for tool in discovered.json()["result"]["tools"]}
    assert set(tools) == {"record_work_context", "save_record_work"}
    assert tools["record_work_context"]["annotations"]["readOnlyHint"] is True
    assert tools["save_record_work"]["annotations"]["readOnlyHint"] is False
    request = mocker.patch.object(
        ToolRegistry, "request", return_value={"task_id": work["task_id"]}
    )
    response = work_client.post(
        "/mcp/",
        headers={**headers, "X-Tool-Call-ID": "synthetic-save"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "save_record_work",
                "arguments": {"task_id": work["task_id"], "text": "A private draft"},
            },
        },
    )
    assert response.status_code == 200 and 'isError":true' not in response.text, response.text
    request.assert_called_once_with(
        "POST", f"tasks/{work['task_id']}/record-work/output", {"text": "A private draft"}
    )
