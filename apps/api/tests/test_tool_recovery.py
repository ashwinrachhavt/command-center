"""Recovery uses host policy and bounded attempts, never inferred write safety."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from command_center.agents.config import AgentProfile
from command_center.agents.runtime_control import RunControl, WorkMiddleware, tool_identity
from command_center.agents.tool_recovery import retry_after, safe_read, transient_result


def request(name="document_read", arguments=None):
    return ToolCallRequest(
        tool_call={"name": name, "args": arguments or {"version_id": "synthetic"}, "id": "read-1"},
        tool=None,
        state={},
        runtime=SimpleNamespace(config={"configurable": {}}),
    )


def worker(*, instructions=None, **limits):
    snapshots = []

    async def persist(state):
        snapshots.append(state)

    control = RunControl(
        AgentProfile(
            name="Recovery",
            description="Synthetic",
            model="synthetic",
            instructions="Read.",
            tools=["document_read", "catalog_execute"],
            **limits,
        ),
        persist,
    )
    return WorkMiddleware(control, "lead", instructions=instructions), snapshots


def failure(call, status=503, delay=None):
    return ToolMessage(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "error": "Synthetic failure",
                            "status_code": status,
                            "retry_after_seconds": delay,
                        }
                    ),
                }
            ]
        ),
        tool_call_id=call.tool_call["id"],
    )


@pytest.mark.parametrize("status", [408, 429, 502, 503, 504])
def test_transient_read_recovers_without_another_model_turn(status, mocker):
    sleep = mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, snapshots = worker()
    identities = []

    async def handle(call):
        identities.append(tool_identity.get())
        if len(identities) < 3:
            return failure(call, status)
        return ToolMessage("Exact evidence", tool_call_id=call.tool_call["id"])

    result = asyncio.run(middleware.awrap_tool_call(request(), handle))
    assert result.content == "Exact evidence"
    assert identities == ["read-1"] * 3
    assert middleware.control.tool_count == 3
    assert middleware.control.steps == 0
    assert snapshots[-1]["tools"][0]["attempts"] == 3
    assert 0.25 <= sleep.await_args_list[0].args[0] <= 0.5
    assert 0.5 <= sleep.await_args_list[1].args[0] <= 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 500])
def test_permanent_or_unclassified_errors_return_without_retry(status, mocker):
    sleep = mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, _ = worker()
    handle = mocker.AsyncMock(side_effect=lambda call: failure(call, status))
    asyncio.run(middleware.awrap_tool_call(request(), handle))
    assert handle.await_count == 1
    sleep.assert_not_awaited()
    assert middleware.control.tools["read-1"]["state"] == "output-error"


@pytest.mark.parametrize(
    "name,args",
    [
        ("draft_artifact", {}),
        ("research_search", {}),
        ("gmail_search", {}),
        ("catalog_execute", {"tool_name": "draft_artifact", "arguments": {}}),
        ("unknown", {}),
    ],
)
def test_writes_and_provider_operations_are_never_replayed(name, args, mocker):
    sleep = mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, _ = worker()
    handle = mocker.AsyncMock(side_effect=lambda call: failure(call))
    asyncio.run(middleware.awrap_tool_call(request(name, args), handle))
    assert handle.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize(
    "limits,expected",
    [
        ({}, 3),
        ({"max_tool_calls": 2}, 2),
        ({"tool_call_limits": {"document_read": 1}}, 1),
    ],
)
def test_exhaustion_respects_attempt_global_and_lookup_limits(limits, expected, mocker):
    mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, _ = worker(**limits)
    handle = mocker.AsyncMock(side_effect=lambda call: failure(call))
    call = request(
        "catalog_execute", {"tool_name": "document_read", "arguments": {"version_id": "synthetic"}}
    )
    asyncio.run(middleware.awrap_tool_call(call, handle))
    assert handle.await_count == expected
    assert middleware.control.tool_count == expected
    assert middleware.control.tools["read-1"]["attempts"] == expected
    assert not middleware.control.read_cache


@pytest.mark.parametrize("delay,attempts", [(2, 3), (60, 1)])
def test_server_retry_after_is_respected_or_left_for_later(delay, attempts, mocker):
    sleep = mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, _ = worker()
    handle = mocker.AsyncMock(side_effect=lambda call: failure(call, 429, delay))
    asyncio.run(middleware.awrap_tool_call(request(), handle))
    assert handle.await_count == attempts
    assert all(args.args[0] >= delay for args in sleep.await_args_list)


def test_steering_during_backoff_prevents_the_next_attempt(mocker):
    sequence = 0

    async def instructions(_):
        return sequence, []

    async def wait(_):
        nonlocal sequence
        sequence = 1

    mocker.patch("command_center.agents.runtime_control.asyncio.sleep", side_effect=wait)
    middleware, _ = worker(instructions=instructions)
    handle = mocker.AsyncMock(side_effect=lambda call: failure(call))
    result = asyncio.run(middleware.awrap_tool_call(request(), handle))
    assert handle.await_count == 1
    assert "new instructions" in result.content


def test_cancellation_during_backoff_does_not_dispatch_again(mocker):
    async def exercise():
        sleeping = asyncio.Event()

        async def wait(_):
            sleeping.set()
            await asyncio.Event().wait()

        mocker.patch("command_center.agents.runtime_control.asyncio.sleep", side_effect=wait)
        middleware, _ = worker()
        handle = mocker.AsyncMock(side_effect=lambda call: failure(call))
        task = asyncio.create_task(middleware.awrap_tool_call(request(), handle))
        await asyncio.wait_for(sleeping.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert handle.await_count == 1
        assert not middleware.control.read_cache

    asyncio.run(exercise())


def test_transport_exhaustion_returns_safe_read_error_but_unknown_errors_propagate(mocker):
    mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, _ = worker()
    handle = mocker.AsyncMock(side_effect=httpx.ReadTimeout("private request details"))
    result = asyncio.run(middleware.awrap_tool_call(request(), handle))
    assert result.status == "error"
    assert "private" not in result.content
    assert handle.await_count == 3
    middleware, _ = worker()
    handle = mocker.AsyncMock(side_effect=RuntimeError("bug"))
    with pytest.raises(RuntimeError, match="bug"):
        asyncio.run(middleware.awrap_tool_call(request(), handle))
    assert handle.await_count == 1


def test_replayed_ledger_does_not_reset_the_automatic_retry_allowance(mocker):
    mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, snapshots = worker()
    handle = mocker.AsyncMock(side_effect=lambda call: failure(call))
    asyncio.run(middleware.awrap_tool_call(request(), handle))
    middleware.control = RunControl(
        middleware.control.profile, middleware.control.sink, prior_state=snapshots[-1]
    )
    asyncio.run(middleware.awrap_tool_call(request(), handle))
    assert handle.await_count == 4  # Explicit graph replay runs once; no fresh retry loop.
    assert middleware.control.tools["read-1"]["attempts"] == 3


def test_source_data_and_remote_hints_cannot_request_retries():
    assert safe_read({"name": "approved_profile"})
    assert not safe_read({"name": "unknown", "readOnlyHint": True})
    for source in (
        {"text": '{"error":"example","status_code":503}', "version_id": "source"},
        {"error": "quoted error", "status_code": 503, "version_id": "source"},
        {"content": [{"type": "text", "text": "source"}], "status_code": 503},
        {"error": "unknown", "retryable": True},
    ):
        assert transient_result(source) == (False, None)
    assert transient_result(
        {"result": {"error": "timeout", "error_code": "tool_transport_unavailable"}}
    ) == (True, None)
    assert retry_after("NaN") is None
    assert retry_after("infinity") is None
    assert retry_after("invalid") is None
    assert retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0


def test_duplicate_reads_share_one_recovery_loop_and_root_budget(mocker):
    mocker.patch("command_center.agents.runtime_control.asyncio.sleep")
    middleware, _ = worker(max_tool_calls=5)
    attempts = 0

    async def handle(call):
        nonlocal attempts
        attempts += 1
        return (
            failure(call)
            if attempts < 3
            else ToolMessage("Evidence", tool_call_id=call.tool_call["id"])
        )

    async def exercise():
        calls = [request() for _ in range(3)]
        for index, call in enumerate(calls):
            call.tool_call["id"] = f"read-{index}"
        results = await asyncio.gather(
            *(middleware.awrap_tool_call(call, handle) for call in calls)
        )
        assert [result.tool_call_id for result in results] == [
            f"read-{index}" for index in range(3)
        ]
        assert all(result.content == "Evidence" for result in results)

    asyncio.run(exercise())
    assert attempts == 3
    assert middleware.control.tool_count == 5  # Three logical calls, two shared retries.


def test_registry_preserves_retry_delay_without_exposing_exception_details(settings):
    from uuid import uuid4

    from command_center.agents.tools import ToolRegistry

    middleware, _ = worker()
    registry = ToolRegistry(settings, middleware.control.profile, uuid4(), uuid4(), "synthetic")

    def unavailable(_):
        response = httpx.Response(
            429, headers={"Retry-After": "3"}, request=httpx.Request("GET", "https://example.org")
        )
        raise httpx.HTTPStatusError(
            "private-provider-details", request=response.request, response=response
        )

    registry.add("synthetic", "Synthetic", {"type": "object"}, unavailable)
    result = json.loads(registry.execute("synthetic", {}, "call-1"))
    assert transient_result(result) == (True, 3)
    assert "private-provider-details" not in json.dumps(result)

    def interrupted(_):
        raise httpx.ReadTimeout("private-transport-details")

    registry.executors["synthetic"] = interrupted
    result = json.loads(registry.execute("synthetic", {}, "call-2"))
    assert transient_result(result) == (True, None)
    assert "private-transport-details" not in json.dumps(result)
