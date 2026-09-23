"""Bounded chat context using synthetic model replies; no paid provider or database."""

import asyncio
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from command_center.agents.config import AgentProfile
from command_center.agents.runtime import run_graph
from command_center.api.conversations import MessageCreate, SessionCreate


class NoTools:
    schemas = []

    async def aexecute(self, name, arguments, call_id):
        raise AssertionError("No external tools are expected")


def test_standalone_session_and_fresh_answer_contract():
    assert SessionCreate().title == "New conversation"
    message = MessageCreate(content="Synthetic prompt", fresh_answer=True, model="gpt-5-mini")
    assert message.fresh_answer is True
    assert message.model == "gpt-5-mini"


def test_large_history_compacts_before_accounting_limit(scripted_model):
    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Preserve the synthetic objective and exact references.",
        max_steps=10,
    )
    observed = []
    snapshots = []
    saved = []
    reference = str(uuid4())
    messages = [
        HumanMessage(content=f"Synthetic constraint {reference}. " + "x" * 550, id=str(uuid4()))
        for _ in range(270)
    ]
    messages.append(HumanMessage(content="What is the next step?", id=str(uuid4())))

    def reply(batch):
        observed.append(sum(len(str(item.content)) for item in batch))
        if len(batch) == 1 and "<messages>" in str(batch[0].content):
            return AIMessage(
                content=f"Objective: keep synthetic constraints. Reference {reference}."
            )
        return AIMessage(content="Continue the synthetic task.")

    async def persist(state):
        snapshots.append(state)

    async def summary(text, covered_ids):
        saved.append((text, covered_ids))

    result = asyncio.run(
        run_graph(
            profile,
            messages,
            NoTools(),
            persist,
            model=scripted_model([reply] * 10),
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
            summary_sink=summary,
        )
    )
    assert result == "Continue the synthetic task."
    assert len(observed) >= 2
    assert max(observed) < profile.max_context_chars
    assert snapshots[-1]["steps"] == len(observed)
    assert saved and reference in saved[-1][0]
    assert messages[-1].id not in saved[-1][1]
    assert len(saved[-1][1]) > 200
    assert observed[-1] < sum(len(str(message.content)) for message in messages) // 2


def test_cache_policy_is_explicit_text_only_and_fails_closed():
    from command_center.agents import answer_cache

    safe = "Summarize this text:\nA synthetic, immutable paragraph."
    assert answer_cache.cacheable_request(safe)
    assert not answer_cache.cacheable_request("Send this text:\nA synthetic paragraph.")
    assert not answer_cache.cacheable_request("Summarize the latest records")
    assert not answer_cache.cacheable_request(
        "Summarize this text:\nRefresh the latest live records."
    )
    assert not answer_cache.cacheable_request("Summarize this text:   ")
    assert answer_cache.read_only_trace({"steps": 1, "tool_count": 0, "tools": []})
    assert not answer_cache.read_only_trace({})
    assert not answer_cache.read_only_trace({"steps": 1, "tool_count": 1, "tools": []})
    assert not answer_cache.read_only_trace(
        {
            "steps": 2,
            "tool_count": 1,
            "tools": [{"name": "create_task", "state": "output-available"}],
        }
    )


def test_summary_failure_does_not_publish_or_retry(scripted_model):
    import pytest

    from command_center.agents.runtime_control import ExecutionStopped

    profile = AgentProfile(
        name="Synthetic", description="Synthetic", model="gpt-5-mini", instructions="Synthetic"
    )
    calls = []
    published = []

    def deny(batch):
        calls.append(batch)
        raise ExecutionStopped("spending_limit")

    async def persist(state):
        pass

    async def summary(text, ids):
        published.append(text)

    with pytest.raises(ExecutionStopped, match="spending_limit"):
        asyncio.run(
            run_graph(
                profile,
                [HumanMessage(content="x" * 1000) for _ in range(100)],
                NoTools(),
                persist,
                model=scripted_model([deny]),
                checkpointer=InMemorySaver(),
                thread_id=str(uuid4()),
                summary_sink=summary,
            )
        )
    assert len(calls) == 1
    assert not published


def test_authoritative_input_reference_survives_compaction(scripted_model):
    reference = str(uuid4())
    observed = []
    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Synthetic",
        max_steps=10,
    )
    messages = [
        HumanMessage(
            content='{"input_user_message_id": "' + reference + '"}', name="workspace_context"
        )
    ]
    messages.extend(HumanMessage(content="Synthetic history " + "x" * 700) for _ in range(120))
    messages.append(HumanMessage(content="Continue"))

    def reply(batch):
        if len(batch) == 1 and "<messages>" in str(batch[0].content):
            return AIMessage(content="Synthetic objective and constraints.")
        observed.extend(batch)
        return AIMessage(content="Done")

    async def persist(state):
        pass

    asyncio.run(
        run_graph(
            profile,
            messages,
            NoTools(),
            persist,
            model=scripted_model([reply] * 10),
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
        )
    )
    pinned = [message for message in observed if message.name == "workspace_context"]
    assert len(pinned) == 1
    assert reference in pinned[0].content


def test_compacted_checkpoint_resumes_the_exact_unanswered_question(scripted_model):
    from test_agent_questions import QuestionTools, question_profile

    from command_center.agents.runtime import GraphPaused

    profile = question_profile().model_copy(update={"max_steps": 10})
    saver = InMemorySaver()
    thread_id = str(uuid4())
    snapshots = []

    async def persist(state):
        snapshots.append(state)

    def reply(batch):
        if len(batch) == 1 and "<messages>" in str(batch[0].content):
            return AIMessage(content="Synthetic prior objective and constraints.")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ask_user",
                    "args": {"prompt": "Which synthetic location?"},
                    "id": "synthetic-location",
                }
            ],
        )

    paused = asyncio.run(
        run_graph(
            profile,
            [HumanMessage(content="x" * 700) for _ in range(125)],
            QuestionTools(),
            persist,
            model=scripted_model([reply] * 10),
            checkpointer=saver,
            thread_id=thread_id,
        )
    )
    assert isinstance(paused, GraphPaused)
    [question] = paused.questions
    assert question.tool_call_id == "synthetic-location"
    received = []

    def resumed(batch):
        received.extend(str(message.content) for message in batch)
        return AIMessage(content="Continue in the synthetic location.")

    result = asyncio.run(
        run_graph(
            profile,
            "ignored on checkpoint resume",
            QuestionTools(),
            persist,
            model=scripted_model([resumed]),
            checkpointer=saver,
            thread_id=thread_id,
            resume=(question.interrupt_id, "Synthetic Seattle"),
            prior_state=snapshots[-1],
        )
    )
    assert result == "Continue in the synthetic location."
    assert any("Synthetic Seattle" in text for text in received)
    assert any("prior objective" in text for text in received)


def test_large_instruction_overhead_keeps_small_chat_within_hard_budget(scripted_model):
    class LargeSchema(NoTools):
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": "synthetic_read",
                    "description": "d" * 7000,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="s" * 20000,
        max_context_chars=40000,
    )

    async def persist(state):
        pass

    output = asyncio.run(
        run_graph(
            profile,
            "Short synthetic request",
            LargeSchema(),
            persist,
            model=scripted_model([AIMessage(content="Done")]),
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
        )
    )
    assert output == "Done"


def test_large_tool_result_is_offloaded_and_model_input_stays_bounded(scripted_model):
    class LargeResult:
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": "synthetic_read",
                    "description": "Read synthetic text",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        async def aexecute(self, name, arguments, call_id):
            return "Synthetic long tool result.\n" * 5000

    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Read synthetic context.",
    )
    observed = []

    async def persist(state):
        pass

    def finish(batch):
        observed.extend(batch)
        return AIMessage(content="Read the bounded synthetic result.")

    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "synthetic_read", "args": {}, "id": "large-result"}],
            ),
            finish,
        ]
    )
    result = asyncio.run(
        run_graph(
            profile,
            "Read synthetic text",
            LargeResult(),
            persist,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
        )
    )
    assert result == "Read the bounded synthetic result."
    assert sum(len(str(message.content)) for message in observed) < profile.max_context_chars
    assert any("/large_tool_results/" in str(message.content) for message in observed)


def test_compaction_accepts_full_length_messages_in_smaller_profile(scripted_model):
    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Preserve the supplied synthetic constraints.",
        max_context_chars=40000,
    )
    calls = []

    async def persist(state):
        pass

    def reply(batch):
        calls.append(sum(len(str(message.content)) for message in batch))
        if len(batch) == 1 and "<messages>" in str(batch[0].content):
            return AIMessage(content="The first synthetic message's constraints.")
        return AIMessage(content="Both synthetic messages were considered.")

    output = asyncio.run(
        run_graph(
            profile,
            [HumanMessage(content="a" * 20000), HumanMessage(content="b" * 20000)],
            NoTools(),
            persist,
            model=scripted_model([reply, reply]),
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
        )
    )
    assert output == "Both synthetic messages were considered."
    assert len(calls) == 2
    assert max(calls) < profile.max_context_chars
