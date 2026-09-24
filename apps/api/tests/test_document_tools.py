import json
from uuid import uuid4

import httpx

from command_center.agents.config import AgentProfile
from command_center.agents.tools import ToolRegistry


def test_document_tools_bound_passages_require_evidence_and_do_not_grant_review(settings, mocker):
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
        name="Application",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Propose evidence for review.",
        tools=["document_read", "propose_profile_fact", "approved_profile"],
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")
    version_id = str(uuid4())
    registry.execute("document_read", {"version_id": version_id, "offset": 12}, "read-1")
    assert requests[-1].url.path == f"/api/v1/documents/versions/{version_id}/text"
    assert dict(requests[-1].url.params) == {"offset": "12", "limit": "4000"}
    proposal = {
        "field": "skill",
        "value": "Python",
        "source_version_id": version_id,
        "source_excerpt": "Python",
    }
    for _ in range(2):
        registry.execute("propose_profile_fact", proposal, "propose-1")
    assert requests[1].headers["Idempotency-Key"] == requests[2].headers["Idempotency-Key"]
    assert json.loads(requests[1].content) == proposal
    registry.execute("approved_profile", {}, "approved-1")
    assert requests[-1].url.path == "/api/v1/profile/facts/approved"
    assert requests[-1].url.params["limit"] == "10"
    for arguments in (
        {"version_id": "../../profile/facts"},
        {"version_id": version_id, "limit": 12001},
    ):
        assert "arguments invalid" in registry.execute("document_read", arguments, "bad")
    missing_evidence = {"field": "skill", "value": "Python"}
    assert "arguments invalid" in registry.execute("propose_profile_fact", missing_evidence, "bad")
    assert registry.execute("approve_profile_fact", {}, "bad").startswith("Denied:")
    assert len(requests) == 4


def test_escaped_document_passages_keep_valid_json_and_exact_continuation(settings, mocker):
    profile = AgentProfile(
        name="Reader",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Read exact passages.",
        tools=["document_read"],
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")
    version_id = str(uuid4())
    original = '\\"\n' * 4000

    def page(method, path, *, params):
        offset = params["offset"]
        end = min(offset + params["limit"], len(original))
        text = original[offset:end]
        return {
            "version_id": version_id,
            "text": text,
            "offset": offset,
            "next_offset": end if end < len(original) else None,
            "total_chars": len(original),
        }

    mocker.patch.object(registry, "request", side_effect=page)
    first = registry.execute("document_read", {"version_id": version_id, "limit": 12000}, "read-1")
    assert len(first) <= 20000
    parsed = json.loads(first)
    assert parsed["version_id"] == version_id
    assert parsed["next_offset"] == len(parsed["text"]) < len(original)
    pages = [parsed]
    while pages[-1]["next_offset"] is not None:
        pages.append(
            json.loads(
                registry.execute(
                    "document_read",
                    {"version_id": version_id, "offset": pages[-1]["next_offset"]},
                    f"read-{len(pages) + 1}",
                )
            )
        )
    assert "".join(page["text"] for page in pages) == original
    assert [page["offset"] for page in pages] == [
        sum(len(previous["text"]) for previous in pages[:index]) for index in range(len(pages))
    ]
    assert pages[-1]["next_offset"] is None


def test_document_read_explicit_limit_preserves_full_requested_page(settings, mocker):
    profile = AgentProfile(
        name="Reader",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Read exact passages.",
        tools=["document_read"],
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")
    version_id = str(uuid4())
    source = "x" * 220000

    def page(method, path, *, params):
        offset, limit = params["offset"], params["limit"]
        end = min(offset + limit, len(source))
        return {
            "version_id": version_id,
            "text": source[offset:end],
            "offset": offset,
            "next_offset": end if end < len(source) else None,
            "total_chars": len(source),
        }

    request = mocker.patch.object(registry, "request", side_effect=page)
    first = json.loads(
        registry.execute("document_read", {"version_id": version_id, "limit": 12000}, "read-1")
    )
    assert len(first["text"]) == 12000
    assert first["next_offset"] == 12000
    assert first["total_chars"] == 220000
    assert request.call_args.kwargs["params"] == {"offset": 0, "limit": 12000}
    tail = json.loads(
        registry.execute("document_read", {"version_id": version_id, "offset": 212000}, "tail")
    )
    assert tail["version_id"] == version_id
    assert tail["offset"] == 212000
    assert tail["next_offset"] == 216000
    assert tail["text"] == source[212000:216000]


def test_large_approved_fact_pages_keep_whole_records_and_correct_offset(settings, mocker):
    profile = AgentProfile(
        name="Reader",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Read approved facts.",
        tools=["approved_profile"],
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")
    facts = [
        {"id": str(uuid4()), "value": "x" * 4000, "source_excerpt": "y" * 4000} for _ in range(3)
    ]
    mocker.patch.object(
        registry,
        "request",
        return_value={
            "items": facts,
            "total": 3,
            "offset": 0,
            "limit": 10,
        },
    )
    encoded = registry.execute("approved_profile", {}, "facts")
    parsed = json.loads(encoded)
    assert len(encoded) <= 20000
    assert parsed["items"] == facts[:2]
    assert parsed["next_offset"] == parsed["limit"] == 2
    assert parsed["total"] == 3
