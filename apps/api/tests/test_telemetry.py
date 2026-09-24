"""Synthetic tracing and prompt-size regressions; no paid models or exporter traffic."""

import asyncio
import json
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langfuse import Langfuse
from langfuse._client.span import LangfuseAgent, LangfuseGeneration
from langgraph.checkpoint.memory import InMemorySaver

from command_center.agents.config import load_profiles
from command_center.agents.mcp_catalog import add_api_tools, add_catalog_tools
from command_center.agents.runtime import run_graph
from command_center.agents.telemetry import RunTrace, current_trace
from command_center.agents.tools import ToolRegistry
from command_center.agents.trace_content import TraceContent
from command_center.db.agent_events import validate_event
from command_center.main import create_app


def sdk_client(mocker):
    client = mocker.create_autospec(Langfuse, instance=True)
    root = mocker.create_autospec(LangfuseAgent, instance=True)
    root.start_observation.return_value = mocker.create_autospec(LangfuseGeneration, instance=True)
    client.start_observation.return_value = root
    return client


def test_compact_supervisor_reduces_actual_schema_payload(settings, scripted_model, mocker):
    profile = load_profiles("agents/profiles.toml")[0]["lead"]
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-token")
    openapi = create_app(settings).openapi()
    # Match MCP's registry, including API-backed operations such as lead intake.
    add_api_tools(registry, openapi, local=False)
    add_catalog_tools(registry, openapi, local=False)
    profile = profile.model_copy(update={"specialists": {}})
    model = scripted_model([AIMessage(content="Hello.")])
    snapshots = []

    async def save(state):
        snapshots.append(state)

    trace = RunTrace(sdk_client(mocker), uuid4(), uuid4(), "lead", "synthetic")
    trace.activate()
    try:
        result = asyncio.run(
            run_graph(
                profile,
                [HumanMessage(content="Hello")],
                registry,
                save,
                model=model,
                checkpointer=InMemorySaver(),
                thread_id=str(uuid4()),
            )
        )
    finally:
        trace.finish("completed")
    assert result == "Hello." and snapshots[-1]["steps"] == 1
    sent = model._agenerate.call_args.kwargs["tools"]
    domain = [tool for tool in sent if tool["function"]["name"] in profile.tools]
    assert {tool["function"]["name"] for tool in domain} == set(profile.prompt_tools)
    before = len(json.dumps(registry.schemas))
    after = len(json.dumps(domain))
    assert after < before / 4
    print(
        f"Supervisor domain schemas: {before} -> {after} characters ({1 - after / before:.1%} less)"
    )
    generation = trace.root.start_observation.call_args
    assert generation.kwargs["metadata"]["tool_schema_chars"] > 0


def test_cached_usage_is_a_subset_and_trace_does_not_capture_content(scripted_model, mocker):
    from command_center.agents.config import AgentProfile

    class NoTools:
        schemas = []

    profile = AgentProfile(
        name="Synthetic", description="Synthetic", model="gpt-5-mini", instructions="Synthetic"
    )
    snapshots, events = [], []

    async def save(state):
        snapshots.append(state)

    async def activity(kind, role, data):
        events.append((kind, data))
        validate_event(kind, role, data)

    client = sdk_client(mocker)
    trace = RunTrace(client, uuid4(), None, "lead", "synthetic")
    trace.activate()
    model = scripted_model(
        [
            AIMessage(
                content="Synthetic private answer",
                usage_metadata={
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "total_tokens": 110,
                    "input_token_details": {"cache_read": 80},
                },
            )
        ]
    )
    try:
        asyncio.run(
            run_graph(
                profile,
                [HumanMessage(content="Synthetic private prompt")],
                NoTools(),
                save,
                model=model,
                activity=activity,
                checkpointer=InMemorySaver(),
                thread_id=str(uuid4()),
            )
        )
    finally:
        trace.finish("completed")
    usage = next(data for kind, data in events if kind == "usage")
    assert usage == {
        "input_tokens": 100,
        "output_tokens": 10,
        "total_tokens": 110,
        "cached_input_tokens": 80,
    }
    generation = trace.root.start_observation.return_value
    assert generation.update.call_args.kwargs["usage_details"] == {
        "input": 20,
        "input_cached_tokens": 80,
        "output": 10,
    }
    assert "Synthetic private" not in str(client.mock_calls)
    generation.end.assert_called_once_with()
    trace.root.end.assert_called_once_with()
    client.flush.assert_called_once_with()
    assert current_trace.get() is None


def test_exporter_failure_does_not_change_result_or_leave_context(mocker):
    client = sdk_client(mocker)
    client.flush.side_effect = RuntimeError("synthetic outage")
    trace = RunTrace(client, uuid4(), None, "lead", "synthetic")
    trace.activate()
    trace.finish("cancelled")
    assert current_trace.get() is None


def test_unknown_usage_is_not_reported_as_free(mocker):
    trace = RunTrace(sdk_client(mocker), uuid4(), None, "lead", "synthetic")
    call = uuid4()
    trace.model_start(call, "lead", "openai", "gpt-5-mini", 5, 2, 0)
    trace.model_end(call, {}, error=True)
    generation = trace.root.start_observation.return_value
    assert generation.update.call_args.kwargs["usage_details"] is None
    assert generation.update.call_args.kwargs["metadata"]["usage_status"] == "unknown"
    generation.end.assert_called_once_with()


def test_tool_observations_close_with_installed_sdk_contract(mocker):
    trace = RunTrace(sdk_client(mocker), uuid4(), None, "lead", "synthetic")
    data = {"tool_call_id": "synthetic-call", "tool_name": "catalog_search"}
    trace.activity("tool-input-available", "lead", data)
    trace.activity("tool-output-error", "lead", data)
    observation = trace.root.start_observation.return_value
    observation.update.assert_called_once_with(level="ERROR", output={"capture": "disabled"})
    observation.end.assert_called_once_with()


def test_content_capture_redacts_credentials_and_excludes_reasoning():
    content = TraceContent(True, ("synthetic-provider-credential",))
    result = content.capture(
        [
            HumanMessage(content="Email jordan@example.test with api_key=private-value"),
            AIMessage(
                content=[
                    {"type": "text", "text": "Useful answer synthetic-provider-credential"},
                    {"type": "reasoning", "reasoning": "Hidden internal reasoning"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,private"}},
                ],
                tool_calls=[{"id": "c1", "name": "example", "args": {"password": "private"}}],
            ),
            '{"authorization": "Bearer private", "result": "Useful result"}',
        ]
    )
    encoded = json.dumps(result)
    assert "Useful answer" in encoded and "Useful result" in encoded
    for value in ("jordan@", "private", "Hidden internal", "data:image", "synthetic-provider"):
        assert value not in encoded
    assert not result["truncated"]
    large = content.capture({"body": "x" * 50_000})
    assert large["truncated"] and len(json.dumps(large)) < 13_000


def test_root_model_and_tools_have_bounded_content_when_enabled(mocker):
    client = sdk_client(mocker)
    trace = RunTrace(
        client,
        uuid4(),
        uuid4(),
        "lead",
        "synthetic",
        content=TraceContent(True),
        request="Read my latest document",
    )
    assert (
        client.start_observation.call_args.kwargs["input"]["content"] == "Read my latest document"
    )
    call = uuid4()
    trace.model_start(
        call,
        "lead",
        "openai",
        "synthetic",
        12,
        0,
        0,
        messages=[HumanMessage(content="Read my document")],
    )
    generation = trace.root.start_observation.return_value
    assert trace.root.start_observation.call_args.kwargs["input"]["content"][0]["role"] == "human"
    trace.model_end(
        call, {"input_tokens": 10, "output_tokens": 2}, output=[AIMessage(content="Summary")]
    )
    assert generation.update.call_args.kwargs["output"]["content"][0]["content"] == "Summary"
    trace.activity(
        "tool-input-available",
        "lead",
        {
            "tool_call_id": "tool1",
            "tool_name": "document_read",
            "input": {"version_id": "synthetic"},
        },
    )
    assert trace.root.start_observation.call_args.kwargs["input"]["content"] == {
        "version_id": "synthetic"
    }
    trace.activity(
        "tool-output-available", "lead", {"tool_call_id": "tool1", "output": "Document text"}
    )
    assert generation.update.call_args.kwargs["output"]["content"] == "Document text"
    trace.finish("completed", output="Saved summary")
    assert trace.root.update.call_args.kwargs["output"]["content"]["answer"] == "Saved summary"
