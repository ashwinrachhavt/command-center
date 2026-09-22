"""Agent tool boundaries without network providers or database fixtures."""

import json
from uuid import uuid4

import httpx

from command_center.agents.config import AgentProfile
from command_center.agents.tools import ToolRegistry


def test_lead_tools_preserve_retry_receipts_and_reject_path_injection(settings, mocker):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"saved": True})

    client_type = httpx.Client
    mocker.patch(
        "command_center.agents.tools.httpx.Client",
        side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    profile = AgentProfile(
        name="Research",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Capture the requested lead.",
        tools=["capture_lead", "enrich_lead", "lead_evidence"],
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")
    capture = {
        "url": "https://example.com/jobs/engineer",
        "title": "Engineer",
        "company_name": "Synthetic Company",
        "snippet": "A public search result.",
    }
    for _ in range(2):
        assert json.loads(registry.execute("capture_lead", capture, "capture-1"))["saved"]
    assert requests[0].url.path == "/api/v1/leads/capture"
    assert requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]
    assert json.loads(requests[0].content) == capture

    opportunity_id = str(uuid4())
    registry.execute("enrich_lead", {"opportunity_id": opportunity_id}, "enrich-1")
    registry.execute("lead_evidence", {"opportunity_id": opportunity_id}, "evidence-1")
    assert requests[2].method == "POST"
    assert requests[2].url.path == f"/api/v1/opportunities/{opportunity_id}/enrich"
    assert requests[2].headers["Idempotency-Key"] != requests[0].headers["Idempotency-Key"]
    assert requests[3].url.path == f"/api/v1/opportunities/{opportunity_id}/research"
    assert requests[3].url.params["limit"] == "3"

    for invalid in ("../../artifacts", f"{opportunity_id}/../tasks", "https://example.com"):
        result = registry.execute("enrich_lead", {"opportunity_id": invalid}, "invalid")
        assert "unavailable or arguments invalid" in result
    assert len(requests) == 4

    reader = ToolRegistry(
        settings,
        profile.model_copy(update={"tools": ["lead_evidence"]}),
        uuid4(),
        uuid4(),
        "synthetic-reader",
    )
    assert reader.execute("capture_lead", capture, "denied").startswith("Denied:")
    assert len(requests) == 4


def test_outreach_artifact_is_a_private_unsent_message(settings, mocker):
    profile = AgentProfile(
        name="Outreach",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Save the requested draft.",
        tools=["draft_artifact"],
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")
    request = mocker.patch.object(registry, "request", return_value={"id": "draft"})
    registry.execute(
        "draft_artifact",
        {
            "title": "Outreach draft",
            "text": "Subject: Engineering role\n\nHello",
            "kind": "message",
        },
        "draft-1",
    )
    request.assert_called_once_with(
        "POST",
        "artifacts",
        {
            "title": "Outreach draft",
            "text": "Subject: Engineering role\n\nHello",
            "kind": "message",
            "sensitivity": "private",
        },
    )
