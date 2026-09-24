"""Progress is bounded, public, durable and independent of paid summarization."""

import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from command_center.agents.config import AgentProfile
from command_center.agents.progress import continuation_context, partial_reply, progress_text
from command_center.agents.runtime_control import RunControl, WorkMiddleware


def test_concurrent_progress_survives_restore_without_duplicate_updates():
    snapshots, events = [], []
    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="synthetic",
        instructions="Use saved receipts.",
    )

    async def persist(state):
        snapshots.append(state)

    async def activity(kind, role, data):
        events.append((kind, role, data))

    async def exercise():
        control = RunControl(profile, persist, activity=activity)
        middleware = WorkMiddleware(control, "research")

        async def handler(request):
            return ToolMessage("Synthetic result", tool_call_id=request.tool_call["id"])

        async def call(index, worker=middleware):
            await worker.awrap_tool_call(
                ToolCallRequest(
                    tool_call={"name": "research_search", "args": {}, "id": f"lookup-{index}"},
                    tool=None,
                    state={},
                    runtime=SimpleNamespace(config={"configurable": {}}),
                ),
                handler,
            )

        await asyncio.gather(*(call(index) for index in range(3)))
        updates = [event for event in events if event[0] == "text-delta"]
        assert len(updates) == 1
        assert "3 operations" in updates[0][2]["delta"]
        restored = RunControl(profile, persist, activity=activity, prior_state=snapshots[-1])
        await restored.report_progress()
        assert len([event for event in events if event[0] == "text-delta"]) == 1
        worker = WorkMiddleware(restored, "research")
        for index in range(3, 8):
            await call(index, worker)
        updates = [event for event in events if event[0] == "text-delta"]
        assert len(updates) == 2
        assert "8 operations" in updates[-1][2]["delta"]
        assert snapshots[-1]["progress_index"] == 2

    asyncio.run(exercise())


def test_slow_operation_emits_an_honest_update_without_model_calls():
    events = []

    async def persist(state):
        pass

    async def activity(kind, role, data):
        events.append(data)

    async def exercise():
        control = RunControl(
            AgentProfile(
                name="Slow",
                description="Synthetic",
                model="synthetic",
                instructions="Wait for the result.",
            ),
            persist,
            activity=activity,
        )
        control.last_progress_at -= 21
        await control.report_progress()
        await control.report_progress()
        assert len(events) == 1
        assert "still working" in events[0]["delta"]
        assert "completed" not in events[0]["delta"]
        assert control.steps == 0

    asyncio.run(exercise())


def test_catalog_cannot_bypass_lookup_quota_and_model_keeps_save_tools():
    dispatched = []
    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="synthetic",
        instructions="Save results.",
        tools=["research_search", "catalog_execute", "draft_artifact"],
        tool_call_limits={"research_search": 1},
    )

    async def persist(state):
        pass

    async def exercise():
        middleware = WorkMiddleware(RunControl(profile, persist), "lead")

        async def handler(request):
            dispatched.append(request.tool_call["id"])
            return ToolMessage("Found source", tool_call_id=request.tool_call["id"])

        for identifier in ("first", "blocked"):
            result = await middleware.awrap_tool_call(
                ToolCallRequest(
                    tool_call={
                        "name": "catalog_execute",
                        "args": {"tool_name": "research_search"},
                        "id": identifier,
                    },
                    tool=None,
                    state={},
                    runtime=SimpleNamespace(config={"configurable": {}}),
                ),
                handler,
            )
        assert result.status == "error"
        assert dispatched == ["first"]

        async def model(request):
            assert [tool.name for tool in request.tools] == ["draft_artifact"]
            return "supported draft"

        request = SimpleNamespace(
            system_message=None,
            messages=[],
            tools=[SimpleNamespace(name=name) for name in ("research_search", "draft_artifact")],
            override=lambda **values: SimpleNamespace(**values),
        )
        assert await middleware.awrap_model_call(request, model) == "supported draft"

    asyncio.run(exercise())


def test_continuation_retains_write_references_and_bounds_private_source_text():
    checkpoint = {
        "tools": [
            {
                "id": "saved",
                "name": "catalog_execute",
                "summary": "create_company",
                "state": "output-available",
                "output": '{"id":"saved-company-reference","api_key":"synthetic-secret"}',
            },
            *[
                {
                    "id": f"search-{i}",
                    "name": "research_search",
                    "state": "output-available",
                    "output": "Synthetic source " * 3000,
                }
                for i in range(20)
            ],
        ]
    }
    memory = continuation_context(checkpoint)
    assert "saved-company-reference" in memory
    assert "synthetic-secret" not in memory
    assert len(memory) <= 9000


def test_captures_do_not_evict_primary_records_and_partial_reply_shows_findings():
    tools = [
        {
            "id": "company",
            "name": "catalog_execute",
            "summary": "create_company",
            "state": "output-available",
            "output": '{"id":"company-kept"}',
        },
        {
            "id": "contact",
            "name": "catalog_execute",
            "summary": "create_contact",
            "state": "output-available",
            "output": '{"id":"contact-kept"}',
        },
        *[
            {
                "id": f"capture-{i}",
                "name": "capture_research_source",
                "state": "output-available",
                "output": '{"source_version_id":"source-kept"}',
            }
            for i in range(4)
        ],
        *[
            {
                "id": f"lookup-{i}",
                "name": "research_search",
                "state": "output-available",
                "output": '[{"title":"Synthetic company","url":"https://example.org",'
                '"content":"Builds scheduling software."}]',
            }
            for i in range(5)
        ],
    ]
    memory = continuation_context({"tools": tools})
    reply = partial_reply({"tools": tools}, "tool_limit")
    for reference in ("company-kept", "contact-kept"):
        assert reference in memory
        assert reference in reply
    assert "source-kept" in memory
    for rendered in (reply, progress_text(tools)):
        assert "Builds scheduling software" in rendered
        assert "https://example.org" in rendered
        assert "unverified source claims" in rendered


def test_progress_never_truncates_a_source_reference_away_from_its_claim():
    sources = [
        {
            "title": f"Title {i} " + "X" * 45,
            "url": f"https://example.org/{i}",
            "content": f"Claim {i} " + "Y" * 490,
        }
        for i in range(3)
    ]
    tools = [
        {
            "id": "lookup",
            "name": "research_search",
            "state": "output-available",
            "output": json.dumps(sources),
        }
    ]
    update = progress_text(tools)
    assert "Claim 0" in update
    for source in sources:
        if source["content"][:7] in update:
            assert source["url"] in update
    assert len(update) < 1500


def test_continuation_remains_valid_json_with_heavily_escaped_receipts():
    tools = [
        {
            "id": str(i),
            "name": "create_company",
            "state": "output-available",
            "output": json.dumps({"id": '\\"' * 90, "body": '\\"' * 3000}),
        }
        for i in range(20)
    ]
    memory = continuation_context({"tools": tools})
    assert len(memory) <= 9000
    assert json.loads(memory)["records"]
