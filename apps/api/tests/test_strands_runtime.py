"""Exercise the real optional SDK without network access or provider spend."""

import asyncio
import json
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field, ValidationError

pytest.importorskip("strands_harness")

from command_center.agents.config import AgentProfile  # noqa: E402
from command_center.agents.runtime_control import ExecutionStopped  # noqa: E402
from command_center.agents.spending import ModelSpendingGate  # noqa: E402
from command_center.agents.strands_runtime import run_strands  # noqa: E402


class ScriptedModel(BaseChatModel):
    seen: list[Any] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)
    fail: bool = False
    pause: float = 0

    @property
    def _llm_type(self):
        return "synthetic-strands"

    def bind_tools(self, tools, **kwargs):
        self.bound_tools.append(tools)
        return self

    def _generate(self, *args, **kwargs):
        raise AssertionError("Async only")

    async def _astream(self, messages, **kwargs):
        self.seen.append(messages)
        if self.fail:
            raise RuntimeError("synthetic provider failure")
        if not any(isinstance(message, ToolMessage) for message in messages):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="Reading evidence. ",
                    tool_call_chunks=[
                        {
                            "name": "document_read",
                            "args": json.dumps(
                                {"version_id": "00000000-0000-0000-0000-000000000001"}
                            ),
                            "id": "read-1",
                            "index": 0,
                        }
                    ],
                    usage_metadata={
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "total_tokens": 25,
                        "input_token_details": {"cache_read": 10},
                    },
                )
            )
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content="Supported "))
            await asyncio.sleep(self.pause)
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="answer.",
                    usage_metadata={"input_tokens": 30, "output_tokens": 5, "total_tokens": 35},
                )
            )


class EvidenceTools:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "document_read",
                "description": "Read immutable evidence.",
                "parameters": {
                    "type": "object",
                    "properties": {"version_id": {"type": "string"}},
                    "required": ["version_id"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    def __init__(self, results=None):
        self.calls = []
        self.results = results or ['{"text":"Synthetic evidence", "version_id":"v1"}']

    async def aexecute(self, name, arguments, call_id):
        self.calls.append((name, arguments, call_id))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


def profile(**kwargs):
    return AgentProfile(
        name="Experiment",
        description="Synthetic",
        runtime="strands",
        model="synthetic",
        instructions="Use evidence.",
        tools=["document_read"],
        **kwargs,
    )


def test_real_harness_streams_tools_and_accounts_all_usage():
    states, events = [], []
    model, tools = ScriptedModel(pause=0.1), EvidenceTools()

    async def save(state):
        states.append(state)

    async def activity(kind, role, payload):
        events.append((kind, payload))

    result = asyncio.run(
        run_strands(
            profile(), "Read", tools, save, model=model, thread_id="test", activity=activity
        )
    )
    assert result == "Supported answer."
    assert len(tools.calls) == 1
    assert states[-1]["usage"] == {
        "input_tokens": 50,
        "output_tokens": 10,
        "cached_input_tokens": 10,
    }
    assert states[-1]["steps"] == 2
    assert states[-1]["tool_count"] == 1
    assert [kind for kind, _ in events].count("tool-output-available") == 1
    assert "".join(payload["delta"] for kind, payload in events if kind == "text-delta") == (
        "Reading evidence. Supported answer."
    )
    assert len({payload["message_id"] for kind, payload in events if kind == "text-delta"}) == 2


@pytest.mark.parametrize(
    "setting",
    [
        {"skills": ["test"]},
        {"jev_routing": True},
        {"tools": ["ask_user"]},
        {
            "specialists": {
                "child": {
                    "name": "Child",
                    "description": "test",
                    "model": "test",
                    "instructions": "test",
                }
            }
        },
    ],
)
def test_experimental_profile_rejects_unimplemented_capabilities(setting):
    values = profile().model_dump() | setting
    with pytest.raises(ValidationError):
        AgentProfile.model_validate(values)


@pytest.mark.parametrize("state", [{"steps": 1}, {"tools": []}])
def test_interrupted_experiment_never_replays_tools(state):
    async def save(state):
        raise AssertionError("Must reject before work")

    with pytest.raises(ExecutionStopped, match="strands_resume_unsupported"):
        asyncio.run(
            run_strands(
                profile(),
                "Read",
                EvidenceTools(),
                save,
                model=ScriptedModel(),
                thread_id="test",
                prior_state=state,
            )
        )


def test_model_limit_stops_without_implicit_paid_retries():
    states = []

    async def save(state):
        states.append(state)

    with pytest.raises(ExecutionStopped, match="model_limit"):
        asyncio.run(
            run_strands(
                profile(max_steps=1),
                "Read",
                EvidenceTools(),
                save,
                model=ScriptedModel(),
                thread_id="test",
            )
        )
    assert states[-1]["steps"] == 1


def test_transient_read_retries_are_counted_and_permanent_errors_are_not_retried():
    async def exercise(status):
        states = []
        tools = EvidenceTools(
            [json.dumps({"error": "Unavailable", "status_code": status}), '{"text":"Recovered"}']
        )

        async def save(state):
            states.append(state)

        await run_strands(profile(), "Read", tools, save, model=ScriptedModel(), thread_id="test")
        return len(tools.calls), states[-1]["tool_count"]

    assert asyncio.run(exercise(503)) == (2, 2)
    assert asyncio.run(exercise(403)) == (1, 1)


def test_spending_failure_stops_before_provider_io():
    from command_center.db.spending import SpendingDenied

    async def denied(*args, **kwargs):
        raise SpendingDenied("spending_limit")

    async def unused(*args, **kwargs):
        raise AssertionError("Not reserved")

    async def save(state):
        pass

    model = ScriptedModel()
    gate = ModelSpendingGate(denied, unused, unused)
    with pytest.raises(ExecutionStopped, match="spending_limit"):
        asyncio.run(
            run_strands(
                profile(),
                "Read",
                EvidenceTools(),
                save,
                model=model,
                thread_id="test",
                spending=gate,
            )
        )
    assert model.seen == []


def test_cancellation_closes_inflight_stream_without_followup_call():
    async def exercise():
        model = ScriptedModel(pause=10)
        tools = EvidenceTools()

        async def save(state):
            pass

        task = asyncio.create_task(
            run_strands(profile(), "Read", tools, save, model=model, thread_id="cancel")
        )
        while len(model.seen) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert len(model.seen) == 2

    asyncio.run(exercise())


def test_summary_calls_are_accounted_and_hidden_from_public_stream(scripted_model):
    states, summaries, events = [], [], []
    usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}

    def final(messages):
        assert any(message.name == "conversation_summary" for message in messages)
        return AIMessage(content="Final answer.", usage_metadata=usage)

    model = scripted_model(
        [
            AIMessage(content="Preserved synthetic constraint.", usage_metadata=usage),
            final,
        ]
    )

    async def save(state):
        states.append(state)

    async def summary(text, references):
        summaries.append((text, references))

    async def activity(kind, role, payload):
        if kind == "text-delta":
            events.append(payload["delta"])

    result = asyncio.run(
        run_strands(
            profile(max_context_chars=10000),
            [
                HumanMessage(content="Old constraint: " + "x" * 5800, id="old"),
                AIMessage(content="Previous discussion: " + "y" * 1800, id="discussion"),
                HumanMessage(content="Now answer briefly.", id="new"),
            ],
            EvidenceTools(),
            save,
            model=model,
            thread_id="summary",
            summary_sink=summary,
            activity=activity,
        )
    )
    assert result == "Final answer."
    assert summaries and "old" in summaries[0][1]
    assert states[-1]["steps"] == 2
    assert states[-1]["usage"]["input_tokens"] == 200
    assert "".join(events) == "Final answer."


def test_steering_is_retained_and_stops_stale_tool_execution(scripted_model):
    calls, states = [], []
    usage = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}

    def stale_plan(messages):
        calls.append("model")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "document_read",
                    "args": {"version_id": "v1"},
                    "id": "old-plan",
                }
            ],
            usage_metadata=usage,
        )

    def revised_plan(messages):
        assert any(message.content == "New constraint" for message in messages)
        assert any(
            isinstance(message, ToolMessage) and message.status == "error" for message in messages
        )
        return AIMessage(content="Done with new constraint.", usage_metadata=usage)

    async def instructions(after):
        if calls and after == 0:
            return 1, [HumanMessage(content="New constraint")]
        return after, []

    async def save(state):
        states.append(state)

    tools = EvidenceTools()
    asyncio.run(
        run_strands(
            profile(),
            "Read",
            tools,
            save,
            model=scripted_model([stale_plan, revised_plan]),
            thread_id="steering",
            instructions=instructions,
        )
    )
    assert tools.calls == []
    assert states[-1]["instruction_sequence"] == 1


def test_host_tool_failure_terminates_without_another_model_call():
    class LostLeaseTools(EvidenceTools):
        async def aexecute(self, *args):
            raise ExecutionStopped("lease_lost")

    async def save(state):
        pass

    model = ScriptedModel()
    with pytest.raises(ExecutionStopped, match="lease_lost"):
        asyncio.run(
            run_strands(profile(), "Read", LostLeaseTools(), save, model=model, thread_id="lease")
        )
    assert len(model.seen) == 1


def test_provider_failure_is_not_retried_and_keeps_unknown_spend_reserved():
    from uuid import uuid4

    states, reservations, unknown = [], [], []
    reservation_id = uuid4()

    async def reserve(*args, **kwargs):
        reservations.append(kwargs)
        return reservation_id

    async def settle(*args):
        raise AssertionError("No usage was returned")

    async def mark_unknown(*args):
        unknown.append(args)

    async def save(state):
        states.append(state)

    model = ScriptedModel(fail=True)
    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        asyncio.run(
            run_strands(
                profile(),
                "Read",
                EvidenceTools(),
                save,
                model=model,
                thread_id="failure",
                spending=ModelSpendingGate(reserve, settle, mark_unknown),
            )
        )
    assert len(model.seen) == len(reservations) == len(unknown) == 1
    assert unknown[0][0] == reservation_id
    assert states[-1]["steps"] == 1


def test_worker_dispatches_strands_and_persists_events_and_spending(
    engine,
    agent_server,
    mocker,
    scripted_model,
):
    from uuid import uuid4

    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_deep_agents import enqueue

    from command_center.agents.worker import perform_next
    from command_center.db.agent_events import AgentEvent
    from command_center.db.agents import AgentRun
    from command_center.db.spending import SpendingReservation

    selected = profile().model_copy(update={"tools": [], "model": "gpt-5-mini"})
    run_id = enqueue(engine, selected.model_dump()).id
    model = scripted_model(
        [
            AIMessage(
                content="Synthetic finished task.",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
                id=str(uuid4()),
            )
        ]
    )
    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        run = db.get(AgentRun, run_id)
        assert run.state == "completed", run.error_code
        assert run.output == "Synthetic finished task."
        events = db.scalars(select(AgentEvent).where(AgentEvent.run_id == run_id)).all()
        assert {event.type for event in events} >= {"text-delta", "usage", "run-status"}
        reservations = db.scalars(
            select(SpendingReservation).where(SpendingReservation.agent_run_id == run_id)
        ).all()
        assert len(reservations) == 1
        assert reservations[0].state == "settled"


def test_whitespace_tool_reply_keeps_provider_metadata_through_sdk_normalization(scripted_model):
    usage = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}

    def check_messages(messages):
        planned = next(message for message in messages if isinstance(message, AIMessage))
        assert planned.content == "\n\n"
        assert planned.additional_kwargs["synthetic_signature"] == "retain-me"
        return AIMessage(content="Done.", usage_metadata=usage)

    model = scripted_model(
        [
            AIMessage(
                content="\n\n",
                additional_kwargs={"synthetic_signature": "retain-me"},
                tool_calls=[
                    {"name": "document_read", "args": {"version_id": "v1"}, "id": "whitespace-read"}
                ],
                usage_metadata=usage,
            ),
            check_messages,
        ]
    )

    async def save(state):
        pass

    assert (
        asyncio.run(
            run_strands(
                profile(), "Read", EvidenceTools(), save, model=model, thread_id="whitespace"
            )
        )
        == "Done."
    )


def test_repeated_visible_messages_keep_distinct_ids_and_provider_metadata(scripted_model):
    def check_messages(messages):
        previous = [message for message in messages if isinstance(message, AIMessage)]
        assert [message.id for message in previous] == ["first", "second"]
        assert [message.additional_kwargs["synthetic_signature"] for message in previous] == [
            "signature-one",
            "signature-two",
        ]
        return AIMessage(content="Done.")

    async def save(state):
        pass

    prompt = [
        HumanMessage(content="Repeat"),
        AIMessage(
            content="Same text",
            id="first",
            additional_kwargs={"synthetic_signature": "signature-one"},
        ),
        HumanMessage(content="Repeat"),
        AIMessage(
            content="Same text",
            id="second",
            additional_kwargs={"synthetic_signature": "signature-two"},
        ),
        HumanMessage(content="Finish"),
    ]
    asyncio.run(
        run_strands(
            profile(),
            prompt,
            EvidenceTools(),
            save,
            model=scripted_model([check_messages]),
            thread_id="duplicates",
        )
    )


def test_steering_lease_failure_retains_host_exception_type():
    from command_center.agents.worker import LeaseLost

    polls = 0

    async def instructions(after):
        nonlocal polls
        polls += 1
        if polls == 3:
            raise LeaseLost("lost")
        return after, []

    async def save(state):
        pass

    model = ScriptedModel()
    with pytest.raises(LeaseLost, match="lost"):
        asyncio.run(
            run_strands(
                profile(),
                "Read",
                EvidenceTools(),
                save,
                model=model,
                thread_id="lease-instruction",
                instructions=instructions,
            )
        )
    assert len(model.seen) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {"finish_reason": "MAX_TOKENS"},
        {"finish_reason": "length"},
        {"stop_reason": "max_tokens"},
        {"status": "incomplete"},
    ],
)
def test_truncated_provider_output_cannot_complete_a_task(scripted_model, metadata):
    async def save(state):
        pass

    model = scripted_model([AIMessage(content="Partial", response_metadata=metadata)])
    with pytest.raises(ExecutionStopped, match="output_limit"):
        asyncio.run(
            run_strands(
                profile(), "Read", EvidenceTools(), save, model=model, thread_id="truncated"
            )
        )


def test_exhausted_tools_are_removed_from_the_next_model_request():
    async def save(state):
        pass

    model = ScriptedModel()
    asyncio.run(
        run_strands(
            profile(tool_call_limits={"document_read": 1}),
            "Read",
            EvidenceTools(),
            save,
            model=model,
            thread_id="exhausted",
        )
    )
    assert len(model.seen) == 2
    assert len(model.bound_tools) == 1


def test_blank_assistant_history_retains_identity_when_sdk_inserts_placeholder(scripted_model):
    def check_messages(messages):
        previous = [message for message in messages if isinstance(message, AIMessage)]
        assert [(message.id, message.content) for message in previous] == [
            ("blank", ""),
            ("literal", "[blank text]"),
        ]
        assert previous[0].additional_kwargs == {"synthetic_signature": "blank-signature"}
        return AIMessage(content="Done.")

    async def save(state):
        pass

    asyncio.run(
        run_strands(
            profile(),
            [
                HumanMessage(content="First"),
                AIMessage(
                    content="",
                    id="blank",
                    additional_kwargs={"synthetic_signature": "blank-signature"},
                ),
                HumanMessage(content="Second"),
                AIMessage(content="[blank text]", id="literal"),
                HumanMessage(content="Continue"),
            ],
            EvidenceTools(),
            save,
            model=scripted_model([check_messages]),
            thread_id="blank",
        )
    )
