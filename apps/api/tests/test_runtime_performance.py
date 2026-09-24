"""Deterministic performance contracts: fewer reads and smaller prompts, same evidence."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from command_center.agents.config import AgentProfile
from command_center.agents.mcp_client import MCPTools
from command_center.agents.read_cache import compact_read_results, immutable_read_key
from command_center.agents.runtime_control import RunControl, WorkMiddleware


def test_duplicate_immutable_reads_share_work_but_writes_and_steering_do_not():
    dispatched = []

    async def persist(state):
        pass

    async def exercise():
        control = RunControl(
            AgentProfile(
                name="Read cache",
                description="Synthetic",
                model="synthetic",
                instructions="Reuse evidence.",
            ),
            persist,
        )
        worker = WorkMiddleware(control, "lead")

        async def handler(request):
            dispatched.append(request.tool_call["id"])
            await asyncio.sleep(0.01)
            # Source text resembling an error is data, not a failed API operation.
            passage = json.dumps(
                {
                    "version_id": "immutable-version",
                    "text": json.dumps({"error": "Synthetic log example"}),
                }
            )
            return ToolMessage(
                json.dumps([{"type": "text", "text": passage}]),
                tool_call_id=request.tool_call["id"],
            )

        async def call(identifier, *, name="document_read", role=worker):
            return await role.awrap_tool_call(
                ToolCallRequest(
                    tool_call={
                        "name": name,
                        "args": {"version_id": "immutable-version"},
                        "id": identifier,
                    },
                    tool=None,
                    state={},
                    runtime=SimpleNamespace(config={"configurable": {}}),
                ),
                handler,
            )

        replies = await asyncio.gather(*(call(f"read-{i}") for i in range(3)))
        assert dispatched == ["read-0"]
        assert [reply.tool_call_id for reply in replies] == [f"read-{i}" for i in range(3)]
        assert all(tool["state"] == "output-available" for tool in control.tools.values())
        await call("different-role", role=WorkMiddleware(control, "research"))
        control.sequence = 1
        await call("after-steering")
        await call("write-1", name="create_task")
        await call("write-2", name="create_task")
        assert dispatched == ["read-0", "different-role", "after-steering", "write-1", "write-2"]

    asyncio.run(exercise())


@pytest.mark.parametrize("envelope", ["status", "json", "mcp", "catalog", "catalog_timeout"])
def test_errors_are_not_cached_and_cached_reads_do_not_survive_a_new_run(envelope):
    calls = 0

    async def persist(state):
        pass

    async def exercise():
        nonlocal calls
        profile = AgentProfile(
            name="Catalog",
            description="Synthetic",
            model="synthetic",
            instructions="Discover tools.",
        )

        async def handler(request):
            nonlocal calls
            calls += 1
            failure = {"error": "Synthetic temporary service failure. " * 20, "status_code": 503}
            error = {
                "status": "Unavailable",
                "json": json.dumps(failure),
                "mcp": json.dumps([{"type": "text", "text": json.dumps(failure)}]),
                "catalog": json.dumps(
                    {"result": {"content": [{"type": "text", "text": json.dumps(failure)}]}}
                ),
                "catalog_timeout": json.dumps(
                    {
                        "message": "Tool unavailable or arguments invalid. "
                        "Do not infer a successful result."
                    }
                ),
            }[envelope]
            return ToolMessage(
                error if calls == 1 else "Synthetic immutable passage",
                status="error" if calls == 1 and envelope == "status" else "success",
                tool_call_id=request.tool_call["id"],
            )

        for ids in (("failed", "retried", "cached"), ("new-run",)):
            worker = WorkMiddleware(RunControl(profile, persist), "lead")
            name, arguments = "document_read", {"version_id": "immutable-version"}
            if envelope.startswith("catalog"):
                name, arguments = "catalog_execute", {"tool_name": name, "arguments": arguments}
            for identifier in ids:
                reply = await worker.awrap_tool_call(
                    ToolCallRequest(
                        tool_call={
                            "name": name,
                            "args": arguments,
                            "id": identifier,
                        },
                        tool=None,
                        state={},
                        runtime=SimpleNamespace(config={"configurable": {}}),
                    ),
                    handler,
                )
                if identifier == "failed":
                    assert list(worker.control.tools.values())[-1]["state"] == "output-error"
                    # Error evidence must also remain complete in the effective model context.
                    messages = []
                    for index in range(2):
                        messages.extend(
                            [
                                AIMessage(
                                    content="",
                                    tool_calls=[
                                        {
                                            "name": "document_read",
                                            "args": {"version_id": "immutable-version"},
                                            "id": str(index),
                                        }
                                    ],
                                ),
                                reply.model_copy(update={"tool_call_id": str(index)}),
                            ]
                        )
                    assert compact_read_results(messages) == messages
                else:
                    assert reply.content == "Synthetic immutable passage"
        assert calls == 3

    asyncio.run(exercise())


def test_prompt_projection_removes_duplicate_payload_without_losing_source_or_protocol():
    source = "Exact source-version evidence. " * 400
    messages = []
    for index in range(3):
        messages.extend(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": str(index),
                            "name": "document_read",
                            "args": {"version_id": "source-v1"},
                        }
                    ],
                ),
                ToolMessage(source, tool_call_id=str(index), id=f"message-{index}"),
            ]
        )
    projected = compact_read_results(messages)
    assert len(projected) == len(messages)
    assert projected[1].content == source
    assert projected[3].tool_call_id == "1"
    assert projected[3].id == "message-1"
    assert "tool call 0" in projected[3].content
    assert sum(len(str(message.content)) for message in projected) < len(source) * 1.1
    assert messages[3].content == source
    # A summary may remove an earlier result; the remaining first read must be complete.
    assert compact_read_results(messages[2:])[1].content == source


def test_discovery_runs_concurrently_without_exceeding_the_profile_limit(mocker):
    active = peak = 0

    async def connect(url, token):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return token
        finally:
            active -= 1

    mocker.patch.object(MCPTools, "connect", side_effect=connect)
    tokens = {None: "root", **{f"role-{i}": f"scoped-{i}" for i in range(4)}}
    connected = asyncio.run(MCPTools.connect_many("https://example.org", tokens, concurrency=3))
    assert connected == tokens
    assert peak == 3


def test_discovery_failure_cancels_and_awaits_other_connections(mocker):
    stopped = []

    async def exercise():
        started = asyncio.Event()

        async def connect(url, token):
            if token == "broken":
                await started.wait()
                raise ValueError("Synthetic connection failure")
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(token)

        mocker.patch.object(MCPTools, "connect", side_effect=connect)
        with pytest.raises(ExceptionGroup):
            await MCPTools.connect_many(
                "https://example.org", {None: "broken", "research": "waiting"}, concurrency=2
            )
        assert stopped == ["waiting"]

    asyncio.run(exercise())


def test_cancelled_shared_read_leaves_no_background_work_or_cached_failure():
    async def persist(state):
        pass

    async def exercise():
        control = RunControl(
            AgentProfile(
                name="Cancel", description="Synthetic", model="synthetic", instructions="Read."
            ),
            persist,
        )
        worker = WorkMiddleware(control, "lead")
        started, finished = asyncio.Event(), asyncio.Event()
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finished.set()
            return ToolMessage("Recovered", tool_call_id=request.tool_call["id"])

        async def call(identifier):
            return await worker.awrap_tool_call(
                ToolCallRequest(
                    tool_call={
                        "name": "document_read",
                        "args": {"version_id": "immutable"},
                        "id": identifier,
                    },
                    tool=None,
                    state={},
                    runtime=SimpleNamespace(config={"configurable": {}}),
                ),
                handler,
            )

        first = asyncio.create_task(call("first"))
        await started.wait()
        second = asyncio.create_task(call("second"))
        await asyncio.sleep(0)
        first.cancel()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert finished.is_set()
        assert not control.read_cache
        assert (await call("retry")).content == "Recovered"
        assert calls == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "arguments", [[], {"tool_name": []}, {"tool_name": "document_read", "arguments": []}]
)
def test_invalid_catalog_arguments_bypass_cache_for_normal_schema_validation(arguments):
    assert immutable_read_key({"name": "catalog_execute", "args": arguments}) is None


def test_budget_guidance_keeps_the_system_prefix_and_original_history_unchanged():
    async def persist(state):
        pass

    async def exercise():
        control = RunControl(
            AgentProfile(
                name="Prefix",
                description="Synthetic",
                model="synthetic",
                instructions="Use a stable prefix.",
            ),
            persist,
        )
        worker = WorkMiddleware(control, "lead")
        system = SystemMessage(content="Pinned system instructions")
        messages = [HumanMessage(content="Research synthetic sources")]
        fields = {"system_message": system, "messages": messages, "tools": []}
        request = SimpleNamespace(
            **fields, override=lambda **updates: SimpleNamespace(**(fields | updates))
        )

        async def model(effective):
            assert effective.system_message is system
            assert effective.messages[0] is messages[0]
            assert len(effective.messages) == (2 if control.tool_count else 1)
            return "answer"

        await worker.awrap_model_call(request, model)
        control.tool_count = 3
        await worker.awrap_model_call(request, model)
        assert len(messages) == 1

    asyncio.run(exercise())
