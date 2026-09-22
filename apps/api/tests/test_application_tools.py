import json
from uuid import uuid4

import httpx

from command_center.agents.config import AgentProfile
from command_center.agents.tools import ToolRegistry


def test_application_tools_bound_context_and_keep_review_outside_agent_grants(settings, mocker):
    preparation_id, version_id, fact_id = (str(uuid4()) for _ in range(3))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": preparation_id,
                "version_id": version_id,
                "version": 2,
                "fields": ["Large saved package" * 5000],
            },
        )

    client_type = httpx.Client
    mocker.patch(
        "command_center.agents.tools.httpx.Client",
        side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    profile = AgentProfile(
        name="Application",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Prepare grounded drafts for review.",
        tools=[
            "application_context",
            "suggest_application_answers",
            "memory_read",
            "memory_append",
        ],
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")
    registry.execute("application_context", {"preparation_id": preparation_id}, "context")
    assert requests[-1].url.path == f"/api/v1/browser/preparations/{preparation_id}/context"
    assert dict(requests[-1].url.params) == {"offset": "0", "limit": "10"}
    proposal = {
        "preparation_id": preparation_id,
        "expected_version_id": version_id,
        "answers": [
            {"field_id": "f1", "value": "Synthetic answer", "fact_revision_ids": [fact_id]}
        ],
    }
    for _ in range(2):
        result = json.loads(registry.execute("suggest_application_answers", proposal, "suggest"))
        assert result == {
            "preparation_id": preparation_id,
            "version_id": version_id,
            "version": 2,
            "suggestions_saved": 1,
            "review_required": True,
        }
    assert requests[1].headers["Idempotency-Key"] == requests[2].headers["Idempotency-Key"]
    assert json.loads(requests[1].content) == {
        "expected_version_id": version_id,
        "answers": proposal["answers"],
    }
    for arguments in (
        {"preparation_id": "../../browser/commands"},
        {"preparation_id": preparation_id, "limit": 21},
    ):
        assert "arguments invalid" in registry.execute("application_context", arguments, "bad")
    ungrounded = proposal | {"answers": [{"field_id": "f1", "value": "Unsupported"}]}
    assert "arguments invalid" in registry.execute("suggest_application_answers", ungrounded, "bad")
    assert registry.execute("approve_application", {}, "bad").startswith("Denied:")
    assert registry.execute("fill_application", {}, "bad").startswith("Denied:")
    assert len(requests) == 3

    registry.execute("memory_read", {"query": "writing preference"}, "memory-read")
    assert requests[-1].url.path == "/api/v1/memories/retrieve"
    assert dict(requests[-1].url.params) == {"q": "writing preference", "limit": "10"}
    note = {"title": "Style", "content": "Use short paragraphs", "reason": "Requested preference"}
    registry.execute("memory_append", note, "memory-proposal")
    assert json.loads(requests[-1].content) == note | {"confirm": False}
    assert "arguments invalid" in registry.execute("memory_append", note | {"confirm": True}, "bad")
    assert "arguments invalid" in registry.execute("memory_append", note | {"reason": ""}, "bad")
    assert len(requests) == 5
