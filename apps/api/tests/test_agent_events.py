"""Durable, replayable public activity for agent runs."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt.tool_node import ToolCallRequest
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.agents.runtime import run_graph
from command_center.agents.runtime_control import RunControl, WorkMiddleware
from command_center.core.identity import Identity, authenticate
from command_center.db.agent_events import AgentEvent, public_input, validate_event
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Streaming API owner"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


class EmptyTools:
    schemas: list[dict[str, Any]] = []

    async def aexecute(self, name: str, arguments: dict[str, Any], call_id: str) -> str:
        raise AssertionError("No tool should run")


class StreamingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "synthetic-stream"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "StreamingModel":
        return self

    def _generate(self, messages: list[BaseMessage], **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Hello world"))])

    async def _astream(self, messages: list[BaseMessage], **kwargs: Any):
        for text in ("Hello ", "world"):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=text,
                    id="provider-message-1",
                    usage_metadata=(
                        {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4}
                        if text == "world"
                        else None
                    ),
                )
            )


def make_run(db: Session, owner_id, profile: dict[str, Any] | None = None) -> AgentRun:
    run = AgentRun.enqueue(
        db,
        record_id=uuid4(),
        owner_id=owner_id,
        prompt="Synthetic streamed run",
        profile="lead",
        configuration=profile
        or AgentProfile(
            name="Lead",
            description="Synthetic",
            model="gpt-5-mini",
            instructions="Reply briefly.",
        ).model_dump(mode="json"),
        revision="synthetic",
        request_id=uuid4(),
    )
    db.flush()
    return run


def test_actual_model_chunks_are_streamed_without_exposing_non_text_content() -> None:
    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Reply briefly.",
    )
    events: list[tuple[str, str, dict[str, Any]]] = []

    async def persist(state: dict[str, Any]) -> None:
        pass

    async def activity(event_type: str, role: str, data: dict[str, Any]) -> None:
        events.append((event_type, role, data))

    output = asyncio.run(
        run_graph(
            profile,
            "Hello",
            EmptyTools(),
            persist,
            model=StreamingModel(),
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
            activity=activity,
        )
    )

    assert output == "Hello world"
    deltas = [event for event in events if event[0] == "text-delta"]
    assert "".join(event[2]["delta"] for event in deltas) == "Hello world"
    assert len({event[2]["message_id"] for event in deltas}) == 1
    assert all(event[1] == "lead" for event in deltas)
    assert any(event[0] == "usage" for event in events)


def test_a_small_chunk_is_visible_while_the_provider_waits_for_its_next_token() -> None:
    async def exercise() -> None:
        visible = asyncio.Event()
        release_provider = asyncio.Event()
        deltas: list[str] = []

        class PausingModel(StreamingModel):
            async def _astream(self, messages: list[BaseMessage], **kwargs: Any):
                yield ChatGenerationChunk(message=AIMessageChunk(content="First ", id="paused"))
                await release_provider.wait()
                yield ChatGenerationChunk(message=AIMessageChunk(content="reply", id="paused"))

        async def persist(state: dict[str, Any]) -> None:
            pass

        async def activity(event_type: str, role: str, data: dict[str, Any]) -> None:
            if event_type == "text-delta":
                deltas.append(data["delta"])
                visible.set()

        task = asyncio.create_task(
            run_graph(
                AgentProfile(
                    name="Lead",
                    description="Synthetic",
                    model="synthetic",
                    instructions="Reply briefly",
                ),
                "Reply",
                EmptyTools(),
                persist,
                model=PausingModel(),
                checkpointer=InMemorySaver(),
                thread_id=str(uuid4()),
                activity=activity,
            )
        )
        try:
            await asyncio.wait_for(visible.wait(), timeout=2)
            assert deltas == ["First "]
            assert not task.done()
        finally:
            release_provider.set()
            result = await task
        assert result == "First reply"
        assert "".join(deltas) == result

    asyncio.run(exercise())


def test_sse_drains_a_completed_backlog_without_pauses_between_pages(client, engine, mocker):
    with Session(engine, expire_on_commit=False) as db, db.begin():
        run = AgentRun.claim(db, make_run(db, client.actor_id).id)
        assert run is not None and run.lease_id is not None
        AgentEvent.append(
            db,
            run_id=run.id,
            lease_id=run.lease_id,
            events=[
                ("text-delta", "lead", {"message_id": "backlog", "delta": str(index)})
                for index in range(205)
            ],
        )
        run.finish("completed", output="Saved backlog")
        run_id = run.id
    sleep = mocker.patch(
        "command_center.api.agent_events.asyncio.sleep", new_callable=mocker.AsyncMock
    )
    response = client.get(f"/api/v1/agent-runs/{run_id}/events")
    assert response.status_code == 200
    sequences = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert sequences == list(range(1, 208))
    sleep.assert_not_awaited()


def test_actual_tool_middleware_emits_input_and_output() -> None:
    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Use the tool.",
    )
    events: list[tuple[str, str, dict[str, Any]]] = []

    async def persist(state: dict[str, Any]) -> None:
        pass

    async def activity(event_type: str, role: str, data: dict[str, Any]) -> None:
        events.append((event_type, role, data))

    control = RunControl(profile, persist, activity=activity)
    middleware = WorkMiddleware(control, "lead")
    request = ToolCallRequest(
        tool_call={"name": "synthetic", "args": {"query": "public"}, "id": "tool-1"},
        tool=None,
        state={},
        runtime=SimpleNamespace(config={"configurable": {}}),
    )

    async def invoke() -> ToolMessage:
        async def handler(call: ToolCallRequest) -> ToolMessage:
            return ToolMessage("Synthetic output", tool_call_id=call.tool_call["id"])

        result = await middleware.awrap_tool_call(request, handler)
        assert isinstance(result, ToolMessage)
        return result

    assert asyncio.run(invoke()).content == "Synthetic output"
    assert events == [
        (
            "tool-input-available",
            "lead",
            {"tool_call_id": "tool-1", "tool_name": "synthetic", "input": {"query": "public"}},
        ),
        (
            "tool-output-available",
            "lead",
            {"tool_call_id": "tool-1", "output": "Synthetic output"},
        ),
    ]


def test_lookup_quota_survives_resume_and_denied_call_replay():
    profile = AgentProfile(
        name="Quick",
        description="Synthetic",
        model="synthetic",
        instructions="Use saved context",
        tools=["research_search", "save_record_work"],
        tool_call_limits={"research_search": 1},
    )
    snapshots = []
    dispatched = []

    async def persist(state):
        snapshots.append(state)

    async def invoke():
        control = RunControl(profile, persist)
        middleware = WorkMiddleware(control, "lead")

        async def handler(request):
            dispatched.append(request.tool_call["name"])
            return ToolMessage("Saved", tool_call_id=request.tool_call["id"])

        def request(name, identifier):
            return ToolCallRequest(
                tool_call={"name": name, "args": {}, "id": identifier},
                tool=None,
                state={},
                runtime=SimpleNamespace(config={"configurable": {}}),
            )

        await middleware.awrap_tool_call(request("research_search", "first"), handler)
        denied = await middleware.awrap_tool_call(request("research_search", "second"), handler)
        assert denied.status == "error"
        restored = WorkMiddleware(RunControl(profile, persist, prior_state=snapshots[-1]), "lead")
        replay = await restored.awrap_tool_call(request("research_search", "second"), handler)
        assert replay.status == "error"
        await restored.awrap_tool_call(request("save_record_work", "save"), handler)

    asyncio.run(invoke())
    assert dispatched == ["research_search", "save_record_work"]


def test_events_are_monotonic_fenced_and_terminal(engine) -> None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Streaming owner")
        db.add(owner)
        db.flush()
        run = make_run(db, owner.id)
        claimed = AgentRun.claim(db, run.id)
        assert claimed is not None and claimed.lease_id is not None
        run_id, lease_id = claimed.id, claimed.lease_id

    def append(delta: str) -> None:
        with Session(engine) as db, db.begin():
            AgentEvent.append(
                db,
                run_id=run_id,
                lease_id=lease_id,
                events=[("text-delta", "lead", {"message_id": "message", "delta": delta})],
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(append, ["first", "second"]))

    with Session(engine) as db, db.begin():
        run = db.get(AgentRun, run_id)
        assert run is not None
        run.finish("cancelled")

    with Session(engine) as db:
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.sequence)
        ).all()
        assert [event.sequence for event in events] == [1, 2, 3, 4]
        assert events[0].data == {"state": "running"}
        assert events[-1].data == {"state": "cancelled"}
        with pytest.raises(RecordConflict):
            AgentEvent.append(
                db,
                run_id=run_id,
                lease_id=lease_id,
                events=[("text-delta", "lead", {"message_id": "message", "delta": "late"})],
            )


def test_expired_lease_records_recovery_status_and_rejects_late_events(engine) -> None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Expired lease owner")
        db.add(owner)
        db.flush()
        run = AgentRun.claim(db, make_run(db, owner.id).id)
        assert run is not None and run.lease_id is not None
        run.lease_expires_at = utc_now() - timedelta(seconds=1)
        run_id, lease_id = run.id, run.lease_id

    with Session(engine) as db, db.begin(), pytest.raises(RecordConflict):
        AgentEvent.append(
            db,
            run_id=run_id,
            lease_id=lease_id,
            events=[("text-delta", "lead", {"message_id": "message", "delta": "late"})],
        )

    with Session(engine) as db, db.begin():
        AgentRun.expire_stale(db)

    with Session(engine) as db:
        run = db.get(AgentRun, run_id)
        events = db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.sequence)
        ).all()
        assert run is not None and run.state == "failed"
        assert [(event.type, event.data) for event in events] == [
            ("run-status", {"state": "running"}),
            ("run-status", {"state": "failed", "error_code": "worker_interrupted"}),
        ]


def test_claiming_one_chat_does_not_wait_for_an_unrelated_owners_recovery(engine) -> None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        blocked_owner = Actor(id=uuid4(), kind="human", display_name="Busy owner")
        ready_owner = Actor(id=uuid4(), kind="human", display_name="Ready owner")
        db.add_all([blocked_owner, ready_owner])
        db.flush()
        stale = AgentRun.claim(db, make_run(db, blocked_owner.id).id)
        assert stale is not None
        stale.lease_expires_at = utc_now() - timedelta(seconds=1)
        ready = make_run(db, ready_owner.id)
        ready_id, stale_id = ready.id, stale.id

    # A profile/budget edit in another workspace must not delay a ready chat.
    with Session(engine) as busy, busy.begin():
        busy.scalar(select(Actor).where(Actor.id == blocked_owner.id).with_for_update())
        with Session(engine) as db, db.begin():
            db.execute(sql_text("SET LOCAL statement_timeout = '500ms'"))
            claimed = AgentRun.claim(db, ready_id)
            assert claimed is not None and claimed.state == "running"
            claimed.finish("cancelled")

    with Session(engine) as db, db.begin():
        # Global recovery remains the dispatcher's responsibility.
        AgentRun.expire_stale(db)
        expired = db.get(AgentRun, stale_id)
        assert expired is not None and expired.state == "failed"


def test_sse_replays_after_cursor_and_hides_other_owners(client, engine) -> None:
    local_owner = client.actor_id
    with Session(engine, expire_on_commit=False) as db, db.begin():
        other = Actor(id=uuid4(), kind="human", display_name="Other owner")
        db.add(other)
        db.flush()
        run = make_run(db, local_owner)
        run = AgentRun.claim(db, run.id)
        assert run is not None and run.lease_id is not None
        AgentEvent.append(
            db,
            run_id=run.id,
            lease_id=run.lease_id,
            events=[
                ("text-delta", "lead", {"message_id": "message", "delta": "Visible"}),
                (
                    "tool-input-available",
                    "lead",
                    {
                        "tool_call_id": "tool",
                        "tool_name": "synthetic",
                        "input": {"api_token": "must-not-leak", "query": "public"},
                    },
                ),
                ("usage", "lead", {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}),
            ],
        )
        run.finish("completed", output="Visible")
        run_id = run.id
        hidden = make_run(db, other.id)
        hidden_id = hidden.id

    response = client.get(f"/api/v1/agent-runs/{run_id}/events?after_sequence=1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = [block for block in response.text.strip().split("\n\n") if block]
    payloads = [json.loads(block.split("data: ", 1)[1]) for block in blocks]
    assert [payload["sequence"] for payload in payloads] == [2, 3, 4, 5]
    assert payloads[1]["data"]["input"] == {
        "api_token": "[redacted]",
        "query": "public",
    }
    assert payloads[2]["data"] == {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}
    assert client.get(f"/api/v1/agent-runs/{hidden_id}/events").status_code == 404


def test_event_payloads_are_bounded_and_redact_nested_credentials() -> None:
    assert public_input({"nested": {"Authorization": "secret", "value": "ok"}}) == {
        "nested": {"Authorization": "[redacted]", "value": "ok"}
    }


@pytest.mark.parametrize("value", ["private-token-value", True, -1, 1.5])
def test_usage_rejects_non_count_values(value) -> None:
    with pytest.raises(ValueError, match="Invalid usage event"):
        validate_event(
            "usage", "lead", {"input_tokens": value, "output_tokens": 0, "total_tokens": value}
        )
    assert public_input({"input_tokens": value}) == {"input_tokens": "[redacted]"}
