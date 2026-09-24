"""Exercise completion budgets through the real graph, without paid providers."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from command_center.agents.config import AgentProfile
from command_center.agents.runtime import run_graph
from command_center.agents.runtime_control import (
    ModelAccounting,
    RunControl,
    SpecialistBudgetExhausted,
    WorkMiddleware,
)


def schema(name):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Synthetic {name}",
            "parameters": {"type": "object", "properties": {}},
        },
    }


@pytest.mark.parametrize("outputs", [1, 2])
@pytest.mark.parametrize("max_steps", [4, 16])
def test_research_loop_saves_and_finishes_inside_existing_model_limit(
    scripted_model, mocker, outputs, max_steps
):
    profile = AgentProfile(
        name="Bounded research",
        description="Synthetic",
        model="synthetic",
        instructions="Research the company and save a document.",
        tools=["research_search", "draft_artifact"],
        max_steps=max_steps,
        max_tool_calls=max_steps + 4,
        tool_call_limits={"research_search": max_steps + 2},
    )
    model = scripted_model([])
    offered = []

    async def generate(messages, **kwargs):
        names = {item["function"]["name"] for item in kwargs.get("tools", [])}
        offered.append(names)
        if "research_search" in names:
            reply = AIMessage(
                content="", tool_calls=[{"name": "research_search", "args": {}, "id": str(uuid4())}]
            )
        elif "draft_artifact" in names:
            reply = AIMessage(
                content="",
                tool_calls=[
                    {"name": "draft_artifact", "args": {}, "id": f"save-{i}"}
                    for i in range(outputs)
                ],
            )
        else:
            assert any(
                isinstance(item, ToolMessage) and "saved-version" in item.text for item in messages
            )
            reply = AIMessage(content="The company research document is saved.")
        return ChatResult(generations=[ChatGeneration(message=reply)])

    model._agenerate.side_effect = generate
    execute = mocker.AsyncMock(
        side_effect=lambda name, args, call_id: (
            '{"version_id":"saved-version"}'
            if name == "draft_artifact"
            else "Synthetic source claim"
        )
    )
    registry = SimpleNamespace(schemas=[schema(name) for name in profile.tools], aexecute=execute)
    snapshots = []

    async def persist(state):
        snapshots.append(state)

    output = asyncio.run(
        run_graph(
            profile,
            "Research and save a company document.",
            registry,
            persist,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
        )
    )
    assert output == "The company research document is saved."
    assert [call.args[0] for call in execute.await_args_list] == (
        ["research_search"] * (max_steps - 2) + ["draft_artifact"] * outputs
    )
    assert offered[-1] == set()
    assert snapshots[-1]["steps"] == profile.max_steps
    assert snapshots[-1]["tool_count"] == max_steps - 2 + outputs


def test_lookup_quotas_are_visible_before_search_and_after_catalog_exhaustion():
    async def persist(state):
        pass

    async def exercise():
        control = RunControl(
            AgentProfile(
                name="Quotas",
                description="Synthetic",
                model="synthetic",
                instructions="Research.",
                tools=["research_search"],
                tool_call_limits={"research_search": 1},
            ),
            persist,
        )
        middleware = WorkMiddleware(control, "lead")
        fields = {"messages": [], "tools": [schema("research_search"), schema("draft_artifact")]}
        request = SimpleNamespace(
            **fields, override=lambda **updates: SimpleNamespace(**(fields | updates))
        )
        requests = []

        async def handler(effective):
            requests.append(effective)

        await middleware.awrap_model_call(request, handler)
        assert "research_search=1" in requests[-1].messages[-1].content
        control.tools["lookup"] = {
            "name": "catalog_execute",
            "summary": "research_search",
            "attempts": 1,
        }
        control.tool_count = 1
        await middleware.awrap_model_call(request, handler)
        assert "research_search=0" in requests[-1].messages[-1].content
        assert [tool["function"]["name"] for tool in requests[-1].tools] == ["draft_artifact"]

    asyncio.run(exercise())


def test_catalog_cannot_restart_research_during_completion(mocker):
    from langgraph.prebuilt.tool_node import ToolCallRequest

    async def persist(state):
        pass

    async def exercise():
        control = RunControl(
            AgentProfile(
                name="Finish",
                description="Synthetic",
                model="synthetic",
                instructions="Research.",
                max_steps=4,
            ),
            persist,
            prior_state={"steps": 3},
        )
        middleware = WorkMiddleware(control, "lead")
        handler = mocker.AsyncMock(return_value=ToolMessage("Saved", tool_call_id="save"))
        for name, expected in [("research_search", "error"), ("draft_artifact", "success")]:
            result = await middleware.awrap_tool_call(
                ToolCallRequest(
                    tool_call={
                        "name": "catalog_execute",
                        "args": {"tool_name": name, "arguments": {}},
                        "id": name,
                    },
                    tool=None,
                    state={},
                    runtime=SimpleNamespace(config={"configurable": {}}),
                ),
                handler,
            )
            assert result.status == expected
        assert handler.await_count == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("root_limit,child_limit", [(6, 8), (10, 3)])
def test_stubborn_specialist_returns_receipts_and_leaves_supervisor_finish_calls(
    scripted_model, mocker, root_limit, child_limit
):
    child = AgentProfile(
        name="Research",
        description="Synthetic",
        model="synthetic",
        instructions="Research.",
        tools=["research_search", "draft_artifact"],
        max_steps=child_limit,
    )
    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="synthetic",
        instructions="Finish all outputs.",
        tools=child.tools,
        specialists={"research": child},
        max_steps=root_limit,
    )
    specialist = scripted_model(
        [
            AIMessage(
                content="", tool_calls=[{"name": "draft_artifact", "args": {}, "id": "child-save"}]
            ),
            *[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "research_search", "args": {}, "id": f"loop-{i}"}],
                )
                for i in range(4)
            ],
        ]
    )

    def save_remaining(messages):
        assert any(
            "specialist returned partial" in item.text and "saved-version" in item.text
            for item in messages
        )
        return AIMessage(
            content="", tool_calls=[{"name": "draft_artifact", "args": {}, "id": "lead-save"}]
        )

    lead = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {"subagent_type": "research", "description": "Save research."},
                        "id": "delegate",
                    }
                ],
            ),
            save_remaining,
            AIMessage(content="The research document and reply are saved."),
        ]
    )
    execute = mocker.AsyncMock(return_value='{"version_id":"saved-version"}')
    registry = SimpleNamespace(schemas=[schema(name) for name in child.tools], aexecute=execute)
    snapshots = []

    async def persist(state):
        snapshots.append(state)

    output = asyncio.run(
        run_graph(
            profile,
            "Research and save both outputs.",
            registry,
            persist,
            model=lead,
            specialist_models={"research": specialist},
            specialist_tools={"research": registry},
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
        )
    )
    assert output == "The research document and reply are saved."
    assert snapshots[-1]["steps"] == 6
    assert snapshots[-1]["role_steps"] == {"lead": 3, "research": 3}
    assert [call.args[0] for call in execute.await_args_list] == [
        "draft_artifact",
        "draft_artifact",
    ]


def test_concurrent_specialists_cannot_spend_supervisor_reserve_and_counts_survive_resume():
    snapshots = []

    async def persist(state):
        snapshots.append(state)

    async def exercise():
        profile = AgentProfile(
            name="Shared",
            description="Synthetic",
            model="synthetic",
            instructions="Research.",
            max_steps=6,
        )
        control = RunControl(profile, persist, prior_state={"steps": 1, "role_steps": {"lead": 1}})
        callbacks = [
            ModelAccounting(control, role, profile, None, nested=True)
            for role in ("research", "writer")
        ]
        outcomes = await asyncio.gather(
            *(callbacks[i % 2].on_chat_model_start({}, [[]], run_id=uuid4()) for i in range(10)),
            return_exceptions=True,
        )
        assert sum(outcome is None for outcome in outcomes) == 3
        assert all(
            outcome is None or isinstance(outcome, SpecialistBudgetExhausted)
            for outcome in outcomes
        )
        assert control.steps == 4
        restored = RunControl(profile, persist, prior_state=snapshots[-1])
        assert restored.role_steps == control.role_steps
        assert WorkMiddleware(restored, "lead").model_remaining() == 2

    asyncio.run(exercise())
