"""Owned chat summaries, exact answer reuse and recent-history HTTP contracts."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_conversations import client, post  # noqa: F401
from test_deep_agents import configure_synthetic_spending

from command_center.agents.config import AgentProfile
from command_center.agents.worker import conversation_messages, perform_next
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.conversations import AgentMessage, AgentSession
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor

PROMPT = "Summarize this text:\nSynthetic immutable text describes a small research project."
OUTPUT = "A small synthetic research project."


@pytest.fixture
def conversation(session):
    actor = Actor(id=uuid4(), kind="human", display_name="Synthetic cache owner")
    session.add(actor)
    session.flush()
    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Transform supplied text.",
    )
    configure_synthetic_spending(session, actor.id, profile.model_dump())
    chat = AgentSession.open_chat(
        session, record_id=uuid4(), owner_id=actor.id, title="Synthetic history", request_id=uuid4()
    )
    first = chat.receive(
        content=PROMPT,
        profile="lead",
        configuration=profile.model_dump(),
        revision="synthetic-v1",
        request_id=uuid4(),
    )
    run = AgentRun.claim(session, first.run_id)
    run.consumed_sequence = first.sequence
    run.checkpoint = {
        "steps": 1,
        "tool_count": 0,
        "tools": [],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    run.finish("completed", output=OUTPUT)
    session.flush()
    return chat, run, profile


def repeat(session, chat, profile, **kwargs):
    message = chat.receive(
        content=PROMPT,
        profile="lead",
        configuration=profile.model_dump(),
        revision="synthetic-v1",
        request_id=uuid4(),
        **kwargs,
    )
    return AgentRun.claim(session, message.run_id)


def test_summary_preserves_full_history_and_rehydrates_a_bounded_tail(session, conversation):
    chat, previous, profile = conversation
    run = repeat(session, chat, profile)
    for index in range(270):
        chat.last_sequence += 1
        session.add(
            AgentMessage(
                owner_id=chat.owner_id,
                session_id=chat.id,
                run_id=run.id,
                sequence=chat.last_sequence,
                author="user",
                profile="lead",
                content=f"Synthetic constraint {index}",
            )
        )
    session.flush()
    messages, _ = conversation_messages(session, run)
    assert len(messages) > 250
    ids = [message.id for message in messages if message.id][:260]
    revision = chat.save_summary(
        run=run,
        lease_id=run.lease_id,
        expected_revision=0,
        summary="Synthetic objective and accepted constraints.",
        covered_ids=ids,
    )
    assert revision == 1
    reduced, sequence = conversation_messages(session, run)
    assert len(reduced) < 20
    assert any("accepted constraints" in str(message.content) for message in reduced)
    assert sequence == chat.last_sequence
    assert (
        session.scalar(
            select(func.count()).select_from(AgentMessage).where(AgentMessage.session_id == chat.id)
        )
        == 273
    )
    assert chat.context_summary["covered_sequence"] == 260
    assert chat.context_summary["source_digest"]
    with pytest.raises(RecordConflict):
        chat.save_summary(
            run=run,
            lease_id=run.lease_id,
            expected_revision=0,
            summary="Stale summary",
            covered_ids=ids,
        )


def test_cancelled_worker_cannot_publish_summary(session, conversation):
    chat, _, profile = conversation
    run = repeat(session, chat, profile)
    lease = run.lease_id
    run.finish("cancelled")
    with pytest.raises(RecordConflict):
        chat.save_summary(
            run=run, lease_id=lease, expected_revision=0, summary="Forbidden", covered_ids=[]
        )
    assert chat.context_summary is None


def test_cache_hit_keeps_durable_provenance_and_consumes_new_message(session, conversation):
    chat, source, profile = conversation
    run = repeat(session, chat, profile)
    assert chat.reuse_answer(run) is True
    assert run.output == OUTPUT and run.state == "completed"
    assert run.checkpoint["steps"] == 0
    assert run.checkpoint["usage"] == {"input_tokens": 0, "output_tokens": 0}
    rows = session.scalars(
        select(AgentMessage)
        .where(AgentMessage.session_id == chat.id)
        .order_by(AgentMessage.sequence)
    ).all()
    assert [row.author for row in rows] == ["user", "assistant", "user", "assistant"]
    assert rows[-1].answer_cache["source_run_id"] == str(source.id)
    assert run.consumed_sequence == rows[-2].sequence
    assert (
        session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.session_id == chat.id)
        )
        == 2
    )


@pytest.mark.parametrize(
    "invalidation",
    [
        "fresh",
        "expired",
        "configuration",
        "source",
        "tools",
        "unknown",
        "summary",
        "intervening",
        "scope",
        "owner",
        "session",
    ],
)
def test_cache_misses_on_changed_authority_or_dependencies(session, conversation, invalidation):
    chat, source, profile = conversation
    if invalidation == "expired":
        source.completed_at = utc_now() - timedelta(minutes=6)
    elif invalidation == "source":
        original = session.scalar(
            select(AgentMessage).where(
                AgentMessage.session_id == chat.id, AgentMessage.sequence == 1
            )
        )
        original.content += " Changed."
    elif invalidation == "tools":
        source.checkpoint = {
            **source.checkpoint,
            "tool_count": 1,
            "tools": [{"name": "unknown_tool"}],
        }
    elif invalidation == "unknown":
        source.checkpoint = {}
    elif invalidation == "summary":
        chat.context_summary = {"revision": 1}
    elif invalidation == "intervening":
        chat.append_assistant(
            run_id=source.id, profile="lead", content="Intervening correction", request_id=uuid4()
        )
    elif invalidation == "scope":
        # A task ID is enough to exercise the fail-closed domain guard without a new row.
        session.flush()
        with session.no_autoflush:
            chat.task_id = uuid4()
            assert chat.cache_candidate(source) is None
        session.expire(chat)
        return
    if invalidation == "configuration":
        profile = profile.model_copy(update={"instructions": "Different authority"})
    session.flush()
    run = repeat(session, chat, profile, fresh_answer=invalidation == "fresh")
    if invalidation in {"owner", "session"}:
        session.flush()
        with session.no_autoflush:
            setattr(run, "owner_id" if invalidation == "owner" else "session_id", uuid4())
            assert chat.reuse_answer(run) is False
        session.expire(run)
        return
    assert chat.reuse_answer(run) is False
    assert run.state == "running"


def test_standalone_history_orders_by_activity_and_searches(client, engine):  # noqa: F811
    first = post(client, "agent-sessions", {"title": "Synthetic first"}).json()
    second = post(client, "agent-sessions", {"title": "Synthetic second"}).json()
    response = post(
        client,
        f"agent-sessions/{first['id']}/messages",
        {"content": PROMPT, "fresh_answer": True, "model": "gpt-5-mini"},
    )
    assert response.status_code == 201, response.text
    page = client.get("/api/v1/agent-sessions?standalone=true&limit=1").json()
    assert page["items"][0]["id"] == first["id"] and page["total"] == 2
    page = client.get("/api/v1/agent-sessions?q=second&standalone=true").json()
    assert [item["id"] for item in page["items"]] == [second["id"]]


def test_worker_cache_hit_never_constructs_provider_or_mcp(engine, settings, mocker):
    with Session(engine) as session, session.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic worker cache owner")
        session.add(actor)
        session.flush()
        profile = AgentProfile(
            name="Synthetic",
            description="Synthetic",
            model="gpt-5-mini",
            instructions="Transform text",
        )
        configure_synthetic_spending(session, actor.id, profile.model_dump())
        chat = AgentSession.open_chat(
            session, record_id=uuid4(), owner_id=actor.id, title="Synthetic", request_id=uuid4()
        )
        message = chat.receive(
            content=PROMPT,
            profile="lead",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
        )
        source = AgentRun.claim(session, message.run_id)
        source.consumed_sequence = 1
        source.checkpoint = {"steps": 1, "tool_count": 0, "tools": []}
        source.finish("completed", output=OUTPUT)
        message = chat.receive(
            content=PROMPT,
            profile="lead",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
        )
        run_id = message.run_id
    mocker.patch(
        "command_center.agents.worker.MCPTools.connect",
        side_effect=AssertionError("Cache must not connect MCP"),
    )
    mocker.patch(
        "command_center.agents.worker.create_chat_model",
        side_effect=AssertionError("Cache must not construct provider"),
    )
    assert perform_next(engine, settings, run_id)
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        assert run.state == "completed", run.error_code
        assert run.output == OUTPUT
        assert run.checkpoint["steps"] == 0


def test_second_turn_reuses_persisted_summary_without_resummarizing(
    session, conversation, scripted_model
):
    import asyncio

    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from test_chat_context import NoTools

    from command_center.agents.runtime import run_graph

    chat, _, profile = conversation
    profile = profile.model_copy(update={"max_steps": 10})
    run = repeat(session, chat, profile)
    input_id = session.scalar(select(AgentMessage.id).where(AgentMessage.run_id == run.id))
    for index in range(270):
        chat.last_sequence += 1
        session.add(
            AgentMessage(
                owner_id=chat.owner_id,
                session_id=chat.id,
                run_id=run.id,
                sequence=chat.last_sequence,
                author="user",
                profile="lead",
                content=f"Synthetic constraint {index}. " + "x" * 600,
            )
        )
    session.flush()
    messages, latest = conversation_messages(session, run)
    revision = 0
    first_calls = []

    async def summary(text, ids):
        nonlocal revision
        revision = chat.save_summary(
            run=run,
            lease_id=run.lease_id,
            expected_revision=revision,
            summary=text,
            covered_ids=ids,
        )

    async def progress(state):
        run.checkpoint = state
        run.consumed_sequence = state["instruction_sequence"]

    def first_reply(batch):
        first_calls.append(sum(len(str(item.content)) for item in batch))
        if len(batch) == 1 and "<messages>" in str(batch[0].content):
            return AIMessage(
                content="Synthetic objective: preserve constraints and unresolved questions."
            )
        assert any(
            str(input_id) in str(message.content) and message.name == "workspace_context"
            for message in batch
        )
        return AIMessage(content="First synthetic answer.")

    output = asyncio.run(
        run_graph(
            profile,
            messages,
            NoTools(),
            progress,
            model=scripted_model([first_reply] * 10),
            checkpointer=InMemorySaver(),
            thread_id=str(run.id),
            initial_sequence=latest,
            summary_sink=summary,
        )
    )
    assert revision > 0
    run.finish("completed", output=output)
    followup = chat.receive(
        content="Continue with those constraints",
        profile="lead",
        configuration=profile.model_dump(),
        revision="synthetic-v1",
        request_id=uuid4(),
    )
    run = AgentRun.claim(session, followup.run_id)
    messages, latest = conversation_messages(session, run)
    second_calls = []

    def second_reply(batch):
        second_calls.append(batch)
        return AIMessage(content="Second synthetic answer.")

    output = asyncio.run(
        run_graph(
            profile,
            messages,
            NoTools(),
            progress,
            model=scripted_model([second_reply]),
            checkpointer=InMemorySaver(),
            thread_id=str(run.id),
            initial_sequence=latest,
            summary_sink=summary,
        )
    )
    assert output == "Second synthetic answer."
    assert len(second_calls) == 1
    assert any("unresolved questions" in str(message.content) for message in second_calls[0])
    assert sum(len(str(message.content)) for message in second_calls[0]) < 60000
    assert chat.last_sequence == 275
    assert len(first_calls) >= 2


def test_summary_invalidates_on_config_or_original_transcript_change(session, conversation):
    chat, _, profile = conversation
    run = repeat(session, chat, profile)
    messages, _ = conversation_messages(session, run)
    chat.save_summary(
        run=run,
        lease_id=run.lease_id,
        expected_revision=0,
        summary="Synthetic summary",
        covered_ids=[message.id for message in messages if message.id][:2],
    )
    session.flush()
    compacted, _ = conversation_messages(session, run)
    assert any(message.name == "conversation_summary" for message in compacted)
    run.config_snapshot = {**run.config_snapshot, "revision": "changed-revision"}
    uncompacted, _ = conversation_messages(session, run)
    assert all(message.name != "conversation_summary" for message in uncompacted)
    run.config_snapshot = {**run.config_snapshot, "revision": "synthetic-v1"}
    original = session.scalar(
        select(AgentMessage).where(AgentMessage.session_id == chat.id, AgentMessage.sequence == 1)
    )
    original.content += " Corrected source."
    session.flush()
    uncompacted, _ = conversation_messages(session, run)
    assert all(message.name != "conversation_summary" for message in uncompacted)
