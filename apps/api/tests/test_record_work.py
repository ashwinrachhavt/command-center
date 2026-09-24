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
    assert post(work_client, route, {"channel": "email"}).json()["task_id"] == work["task_id"]
    assert post(work_client, route, {"channel": "linkedin"}).status_code == 409
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


def test_quick_connection_note_is_bounded_and_does_not_require_enrichment(
    work_client, settings, engine, mocker
):
    person = post(
        work_client, "contacts", {"name": "Synthetic Casey", "notes": "Developer tools"}
    ).json()
    profile_loader = mocker.patch(
        "command_center.api.record_work.available_profile",
        return_value=(
            AgentProfile(
                name="Quick",
                description="Synthetic",
                model="synthetic",
                instructions="Write a note",
                tools=["record_work_context", "save_record_work"],
            ),
            "synthetic",
        ),
    )
    route = f"record-work/contacts/{person['id']}"
    response = post(work_client, route, {"connection_note": True})
    assert response.status_code == 201, response.text
    work = response.json()
    assert profile_loader.call_args.args[1] == "connection"
    assert post(work_client, route, {"connection_note": True}).json()["task_id"] == work["task_id"]
    assert post(work_client, route, {}).status_code == 409
    token = claim(work_client, engine, settings, work)
    context = work_client.get(
        f"/api/v1/tasks/{work['task_id']}/record-work/context",
        headers={"Authorization": "Bearer " + token},
    ).json()
    assert context["connection_note"] is True
    assert context["research_requested"] is False
    output_route = f"tasks/{work['task_id']}/record-work/output"
    for oversized in ("x" * 201, "🙂" * 101):
        assert post(work_client, output_route, {"text": oversized}, token=token).status_code == 422
    saved = post(
        work_client,
        output_route,
        {"text": "Hi Casey, I’m exploring developer tools. Could we connect?"},
        token=token,
    )
    assert saved.status_code == 200, saved.text
    work_client.app.dependency_overrides[authenticate] = lambda: Identity(
        work_client.actor_id, "synthetic"
    )
    contact = work_client.get(f"/api/v1/contacts/{person['id']}").json()
    assert contact["outreach"]["message"].startswith("Hi Casey")
    assert contact["outreach"]["research"] is None
    version = work_client.get(
        f"/api/v1/artifacts/{saved.json()['output_artifact_id']}/versions/{saved.json()['output_version_id']}"
    ).json()
    assert version["payload"]["connection_note"] is True


def test_quick_note_scope_is_validated(work_client):
    contact = post(work_client, "contacts", {"name": "Synthetic Casey"}).json()
    company = post(work_client, "companies", {"name": "Synthetic Labs"}).json()
    assert (
        post(
            work_client,
            f"record-work/contacts/{contact['id']}",
            {"connection_note": True, "channel": "email"},
        ).status_code
        == 422
    )
    assert (
        post(
            work_client, f"record-work/companies/{company['id']}", {"connection_note": True}
        ).status_code
        == 422
    )


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


@pytest.fixture
def researched_contact(work_client, settings, engine, mocker):
    from command_center.db.artifacts import Artifact, ArtifactVersion
    from command_center.db.evidence import SourceRecord

    profile = AgentProfile(
        name="Synthetic outreach",
        description="Synthetic",
        model="synthetic",
        instructions="Synthetic research",
        tools=[
            "record_work_context",
            "save_record_work",
            "research_search",
            "capture_research_source",
            "document_read",
            "approved_profile",
        ],
    )
    mocker.patch("command_center.api.record_work.available_profile", return_value=(profile, "test"))
    person = post(
        work_client,
        "contacts",
        {
            "name": "Synthetic Taylor",
            "title": "Keep my saved title",
            "linkedin_url": "https://www.linkedin.com/in/synthetic-taylor",
        },
    ).json()
    work = post(
        work_client,
        f"record-work/contacts/{person['id']}",
        {
            "research_requested": True,
            "instructions": "Explore work opportunities; within 200 chars",
        },
    ).json()
    quote = "Synthetic Taylor is the founder and CEO of Example Labs."
    with Session(engine) as db, db.begin():
        artifact = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=work_client.actor_id,
            title="Official team",
            kind="source",
            sensitivity="public",
            text=quote,
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
                provider="firecrawl",
                account_scope="public",
                locator="https://example.com/team",
                extraction_method="synthetic_fixture",
            )
        )
        db.add(TaskArtifact(task_id=UUID(work["task_id"]), artifact_id=artifact.id))
    token = claim(work_client, engine, settings, work)
    evidence = [{"source_version_id": source_id, "quote": quote}]
    body = {
        "text": (
            "Hi Taylor, I'm exploring opportunities in developer tools. I'd like to connect "
            "and learn whether my experience could be useful at Example Labs."
        ),
        "source_version_ids": [source_id],
        "contact_research": {
            "identity": "matched",
            "company": "Example Labs",
            "role": "Founder and CEO",
            "summary": "Official team page matches the selected person.",
            "caveats": "Hiring needs have not been confirmed.",
            "identity_evidence": evidence,
            "employment_evidence": evidence,
        },
    }
    return person, work, body, token


def test_researched_note_projects_evidence_and_preserves_human_edits(
    work_client,
    engine,
    researched_contact,
):
    person, work, body, token = researched_contact
    saved = post(work_client, f"tasks/{work['task_id']}/record-work/output", body, token=token)
    assert saved.status_code == 200, saved.text
    work_client.app.dependency_overrides[authenticate] = lambda: Identity(
        work_client.actor_id, "test"
    )
    contact = work_client.get(f"/api/v1/contacts/{person['id']}").json()
    assert contact["title"] == "Keep my saved title" and contact["company_id"] is None
    outreach = contact["outreach"]
    assert outreach["message"] == body["text"]
    assert outreach["research"]["company"] == "Example Labs"
    assert outreach["sources"][0]["url"] == "https://example.com/team"
    listed = work_client.get("/api/v1/contacts").json()["items"]
    assert next(row for row in listed if row["id"] == person["id"])["outreach"] == outreach
    detail = work_client.get(f"/api/v1/follow-ups/{outreach['artifact_id']}").json()
    edited = "Hi Taylor, I'm exploring work in developer tools. Could we connect?"
    update = {
        "expected_version": detail["artifact"]["row_version"],
        "based_on_version_id": detail["version"]["id"],
        "text": edited,
        "channel": "linkedin",
    }
    invalid = work_client.patch(
        f"/api/v1/follow-ups/{outreach['artifact_id']}",
        json={**update, "text": "x" * 201},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert invalid.status_code == 422
    response = work_client.patch(
        f"/api/v1/follow-ups/{outreach['artifact_id']}",
        json=update,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    latest = work_client.get(f"/api/v1/contacts/{person['id']}").json()["outreach"]
    assert latest["message"] == edited
    assert latest["research"] == outreach["research"]
    assert latest["version_id"] != outreach["version_id"]
    with Session(engine) as db, db.begin():
        db.get(AgentRun, UUID(work["run_id"])).finish("completed")
    refresh = post(
        work_client, f"record-work/contacts/{person['id']}", {"research_requested": True}
    ).json()
    with Session(engine) as db, db.begin():
        db.get(AgentRun, UUID(refresh["run_id"])).finish("failed", error_code="synthetic")
    retained = work_client.get(f"/api/v1/contacts/{person['id']}").json()["outreach"]
    assert retained["state"] == "failed" and retained["message"] == edited


@pytest.mark.parametrize(
    "problem", ["missing", "long", "quote", "employment", "unlisted", "other_task"]
)
def test_researched_notes_reject_unbacked_claims_and_excess_length(
    work_client,
    engine,
    researched_contact,
    problem,
):
    person, work, body, token = researched_contact
    if problem == "missing":
        body.pop("contact_research")
    elif problem == "long":
        body["text"] = "x" * 201
    elif problem == "quote":
        body["contact_research"]["identity_evidence"][0]["quote"] = (
            "An invented quote that is not on the page"
        )
    elif problem == "employment":
        body["contact_research"]["employment_evidence"] = []
    elif problem == "unlisted":
        body["source_version_ids"] = []
    else:
        with Session(engine) as db, db.begin():
            link = db.scalar(
                select(TaskArtifact).where(TaskArtifact.task_id == UUID(work["task_id"]))
            )
            db.delete(link)
    response = post(work_client, f"tasks/{work['task_id']}/record-work/output", body, token=token)
    assert response.status_code == 422, response.text
    with Session(engine) as db:
        assert db.get(Task, UUID(work["task_id"])).state != "done"


def test_email_work_reuses_dated_saved_research(work_client, engine, researched_contact):
    person, work, body, token = researched_contact
    saved = post(work_client, f"tasks/{work['task_id']}/record-work/output", body, token=token)
    assert saved.status_code == 200, saved.text
    with Session(engine) as db, db.begin():
        db.get(AgentRun, UUID(work["run_id"])).finish("completed")
    work_client.app.dependency_overrides[authenticate] = lambda: Identity(
        work_client.actor_id, "synthetic"
    )
    email = post(work_client, f"record-work/contacts/{person['id']}", {"channel": "email"})
    assert email.status_code == 201, email.text
    context = work_client.get(f"/api/v1/tasks/{email.json()['task_id']}/record-work/context").json()
    assert context["saved_research"]["company"] == "Example Labs"
    assert context["saved_research"]["saved_at"]
    assert context["saved_research"]["source_version_ids"] == body["source_version_ids"]
    assert "not treat it as a fresh" in context["saved_research"]["meaning"]


def test_uncertain_identity_is_visible_without_inventing_current_employment(
    work_client, researched_contact
):
    person, work, body, token = researched_contact
    body["source_version_ids"] = []
    body["text"] = "Hi Taylor, I'm exploring new work opportunities and would be glad to connect."
    body["contact_research"] = {
        "identity": "uncertain",
        "summary": "Could not reliably identify this person.",
        "caveats": "Public pages describe two people with the same name.",
    }
    response = post(work_client, f"tasks/{work['task_id']}/record-work/output", body, token=token)
    assert response.status_code == 200, response.text
    work_client.app.dependency_overrides[authenticate] = lambda: Identity(
        work_client.actor_id, "test"
    )
    outreach = work_client.get(f"/api/v1/contacts/{person['id']}").json()["outreach"]
    assert outreach["research"]["identity"] == "uncertain"
    assert not outreach["research"]["company"] and not outreach["sources"]
