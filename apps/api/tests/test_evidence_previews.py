"""Agent-visible previews keep durable source references and actionable results."""

import json
from uuid import uuid4

from command_center.agents.config import AgentProfile
from command_center.agents.evidence_previews import (
    LEAD_EVIDENCE_PREVIEW_CHARS,
    project_lead_evidence,
)
from command_center.agents.mcp_catalog import add_catalog_tools
from command_center.agents.tools import ToolRegistry


def registry(settings, tools):
    profile = AgentProfile(
        name="Reader",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Read synthetic evidence.",
        tools=tools,
    )
    return ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-capability")


def saved_evidence():
    return {
        "items": [
            {
                "id": str(uuid4()),
                "artifact_id": str(uuid4()),
                "version_id": str(uuid4()),
                "version": 1,
                "url": "https://example.test/source",
                "title": "Synthetic source",
                "provider": "public_http",
                "retrieved_at": "2026-09-24T00:00:00Z",
                "excerpt": "Evidence " * 333,
            }
            for _ in range(3)
        ],
        "total": 3,
        "offset": 0,
        "limit": 3,
    }


def test_saved_lead_evidence_previews_preserve_provenance_and_pagination(settings, mocker):
    reader = registry(settings, ["lead_evidence", "document_read"])
    evidence = saved_evidence()
    mocker.patch.object(reader, "request", return_value=evidence)

    projected = json.loads(
        reader.execute("lead_evidence", {"opportunity_id": str(uuid4())}, "evidence-1")
    )
    assert projected["total"] == evidence["total"]
    assert projected["offset"] == evidence["offset"]
    assert projected["limit"] == evidence["limit"]
    assert "document_read" in projected["source_text_access"]
    for original, preview in zip(evidence["items"], projected["items"], strict=True):
        assert preview["excerpt"] == original["excerpt"][:LEAD_EVIDENCE_PREVIEW_CHARS]
        assert preview["excerpt_truncated"] is True
        metadata = {
            key: value
            for key, value in preview.items()
            if key not in {"excerpt", "excerpt_truncated"}
        }
        assert metadata == {key: value for key, value in original.items() if key != "excerpt"}
        assert original["excerpt"] == "Evidence " * 333
    assert len(json.dumps(projected).encode()) < len(json.dumps(evidence).encode())


def test_unsaved_or_unreadable_evidence_and_write_receipts_stay_complete(settings, mocker):
    reader = registry(settings, ["lead_evidence", "research_search", "capture_lead"])
    evidence = saved_evidence()
    search = [{"title": "Synthetic", "url": "https://example.test", "content": "x" * 3000}]
    receipt = {"created": True, "source": evidence["items"][0], "review_required": True}
    responses = iter([evidence, search, receipt, {"error": "Read failed", "status_code": 503}])
    mocker.patch.object(reader, "request", side_effect=lambda *args, **kwargs: next(responses))

    opportunity_id = str(uuid4())
    initial = reader.execute("lead_evidence", {"opportunity_id": opportunity_id}, "read")
    assert json.loads(initial) == evidence
    assert json.loads(reader.execute("research_search", {"query": "synthetic"}, "search")) == search
    capture = {
        "url": "https://example.test",
        "title": "Synthetic",
        "company_name": "Synthetic Company",
    }
    assert json.loads(reader.execute("capture_lead", capture, "write")) == receipt
    failure = reader.execute("lead_evidence", {"opportunity_id": opportunity_id}, "fail")
    assert json.loads(failure) == {
        "error": "Read failed",
        "status_code": 503,
    }


def test_nested_catalog_execution_projects_saved_evidence(settings, mocker):
    catalog = registry(settings, ["catalog_execute"])
    add_catalog_tools(catalog, {"paths": {}}, local=False)
    evidence = saved_evidence()
    mocker.patch.object(ToolRegistry, "request", return_value=evidence)

    projected = json.loads(
        catalog.execute(
            "catalog_execute",
            {"tool_name": "lead_evidence", "arguments": {"opportunity_id": str(uuid4())}},
            "catalog-read",
        )
    )
    assert len(projected["items"]) == 3
    assert all(len(item["excerpt"]) == LEAD_EVIDENCE_PREVIEW_CHARS for item in projected["items"])
    assert "document_read" in projected["source_text_access"]


def test_evidence_without_exact_version_reference_is_not_projected():
    evidence = saved_evidence()
    evidence["items"][0]["version_id"] = "not-a-version"
    assert project_lead_evidence(evidence, can_read_versions=True) is evidence
    evidence["items"][0]["version_id"] = uuid4().hex
    assert project_lead_evidence(evidence, can_read_versions=True) is evidence


def test_evidence_can_reach_subsequent_pages(settings, mocker):
    reader = registry(settings, ["lead_evidence", "document_read"])
    evidence = saved_evidence()
    evidence.update(total=7, offset=3)
    request = mocker.patch.object(reader, "request", return_value=evidence)
    result = json.loads(
        reader.execute("lead_evidence", {"opportunity_id": str(uuid4()), "offset": 3}, "page-2")
    )
    assert request.call_args.kwargs["params"] == {"offset": 3, "limit": 3}
    assert result["next_offset"] == 6
    assert result["total"] == 7
