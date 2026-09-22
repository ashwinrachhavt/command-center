"""Real graph, MCP, HTTP and PostgreSQL boundaries with synthetic model replies."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.agents.mcp_client import MCPTools
from command_center.agents.runtime import build_agent, run_graph
from command_center.agents.runtime_control import RunControl
from command_center.core.capabilities import issue_run_token
from command_center.db.agents import AgentRun
from command_center.db.models import Actor, Task
from command_center.db.spending import SpendingPolicy, SpendingRateCard, SpendingReservation


def configure_synthetic_spending(db, owner_id, raw_profile):
    profile = AgentProfile.model_validate(raw_profile)
    configured = [profile, *profile.specialists.values()]
    model_rates = {
        (item.provider, item.model): {
            "provider": item.provider,
            "model": item.model,
            "input_per_million_micros": 0,
            "output_per_million_micros": 0,
            "fixed_micros": 1,
        }
        for item in configured
    }
    card = SpendingRateCard.create(
        db,
        owner_id=owner_id,
        name="Synthetic worker rates",
        source_label="Synthetic test fixture",
        rates={"models": list(model_rates.values()), "tools": []},
        request_id=uuid4(),
    )
    SpendingPolicy.configure(
        db,
        owner_id=owner_id,
        rate_card_id=card.id,
        monthly_limit_micros=1_000_000,
        default_work_limit_micros=1_000_000,
        active=True,
        request_id=uuid4(),
        expected_version=None,
    )
    db.flush()


def enqueue(engine, profile, *, claim=False):
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic deep agent owner")
        db.add(actor)
        db.flush()
        configure_synthetic_spending(db, actor.id, profile)
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            prompt="Plan synthetic research",
            profile="lead",
            configuration=profile,
            revision="synthetic-revision",
            request_id=uuid4(),
        )
        db.flush()
        if claim:
            run = AgentRun.claim(db, run.id)
        return run


def test_parallel_mcp_calls_keep_distinct_receipts(agent_server, engine):
    profile = AgentProfile(
        name="Synthetic",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Use synthetic data.",
        tools=["create_task"],
    )
    run = enqueue(engine, profile.model_dump(), claim=True)
    token = issue_run_token(agent_server, run.id, run.lease_id, audience="command-center-mcp")

    async def call_tools():
        tools = await MCPTools.connect(agent_server.internal_api_url, token)
        return await asyncio.gather(
            tools.aexecute("create_task", {"title": "First parallel task"}, "parallel-first"),
            tools.aexecute("create_task", {"title": "Second parallel task"}, "parallel-second"),
            tools.aexecute("create_task", {"title": "First parallel task"}, "parallel-first"),
        )

    results = asyncio.run(call_tools())
    assert all("Tool unavailable" not in result for result in results)
    with Session(engine) as db:
        tasks = db.scalars(select(Task).where(Task.owner_id == run.owner_id)).all()
        assert sorted(task.title for task in tasks) == [
            "First parallel task",
            "Second parallel task",
        ]


def test_specialist_capability_cannot_use_lead_tools(agent_server, engine):
    child = AgentProfile(
        name="Research",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Read memory.",
        tools=["memory_read"],
    ).model_dump()
    parent = {**child, "tools": ["memory_read", "create_task"], "specialists": {"research": child}}
    run = enqueue(engine, parent, claim=True)
    token = issue_run_token(agent_server, run.id, run.lease_id, role="research")
    with httpx.Client(base_url=agent_server.internal_api_url, trust_env=False) as http:
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}
        assert http.get("/api/v1/memories/retrieve", headers=headers).status_code == 200
        assert http.get("/api/v1/memories", headers=headers).status_code == 403
        denied = http.post("/api/v1/tasks", json={"title": "Must not exist"}, headers=headers)
        assert denied.status_code == 403
        unknown = issue_run_token(agent_server, run.id, run.lease_id, role="unknown")
        assert (
            http.get(
                "/api/v1/memories/retrieve",
                headers={"Authorization": f"Bearer {unknown}"},
            ).status_code
            == 403
        )
    with Session(engine) as db:
        assert db.scalar(select(Task).where(Task.owner_id == run.owner_id)) is None


def test_deep_agent_checkpoints_real_tool_work(agent_server, engine, scripted_model):
    profile = AgentProfile(
        name="Research",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Save the requested synthetic task.",
        tools=["create_task"],
        max_steps=3,
    )
    run = enqueue(engine, profile.model_dump(), claim=True)
    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_task",
                        "args": {"title": "Deep Agents task"},
                        "id": "task-call",
                    }
                ],
            ),
            AIMessage(content="The research task is saved."),
        ]
    )
    states = []
    saver = InMemorySaver()

    async def exercise():
        tools = await MCPTools.connect(
            agent_server.internal_api_url,
            issue_run_token(
                agent_server,
                run.id,
                run.lease_id,
                audience="command-center-mcp",
            ),
        )

        async def persist(state):
            states.append(state)

        output = await run_graph(
            profile,
            "Save a synthetic task",
            tools,
            persist,
            model=model,
            checkpointer=saver,
            thread_id=str(run.id),
        )
        restored_graph = build_agent(
            "lead",
            profile,
            tools,
            model,
            RunControl(profile, persist),
            checkpointer=saver,
        )
        restored = await restored_graph.aget_state({"configurable": {"thread_id": str(run.id)}})
        assert any(isinstance(message, ToolMessage) for message in restored.values["messages"])
        return output

    assert asyncio.run(exercise()) == "The research task is saved."
    assert states[-1]["steps"] == 2
    assert states[-1]["tools"][0]["state"] == "output-available"
    assert "synthetic-model-key" not in str(states)
    with Session(engine) as db:
        assert (
            db.scalar(select(Task).where(Task.owner_id == run.owner_id)).title == "Deep Agents task"
        )


def test_skills_are_progressively_loaded_and_cannot_be_overwritten(
    agent_server,
    engine,
    scripted_model,
):
    profile = AgentProfile(
        name="Research",
        description="Use a pinned skill",
        model="gpt-5-mini",
        instructions="Read the configured research skill before planning.",
        tools=[],
        skill_files={"research": "# Research\n\nCite original synthetic sources."},
    )
    run = enqueue(engine, profile.model_dump(), claim=True)
    skill_path = "/skills/research/research/SKILL.md"

    def read_skill(messages):
        prompt = messages[0].text
        assert skill_path in prompt
        assert "Cite original synthetic sources" not in prompt
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"file_path": skill_path},
                    "id": "read-skill",
                }
            ],
        )

    def attempt_overwrite(messages):
        assert "Cite original synthetic sources" in messages[-1].text
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": skill_path, "content": "Untrusted replacement"},
                    "id": "overwrite-skill",
                }
            ],
        )

    def verify_denial(messages):
        assert "denied" in messages[-1].text.lower()
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"file_path": skill_path},
                    "id": "read-again",
                }
            ],
        )

    def finish(messages):
        assert "Cite original synthetic sources" in messages[-1].text
        assert "Untrusted replacement" not in messages[-1].text
        return AIMessage(content="The pinned research guidance is intact.")

    model = scripted_model([read_skill, attempt_overwrite, verify_denial, finish])
    states = []

    async def exercise():
        registry = await MCPTools.connect(
            agent_server.internal_api_url,
            issue_run_token(agent_server, run.id, run.lease_id, audience="command-center-mcp"),
        )

        async def persist(state):
            states.append(state)

        return await run_graph(
            profile,
            "Use the research guidance",
            registry,
            persist,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id=str(run.id),
            root_role="research",
        )

    assert asyncio.run(exercise()) == "The pinned research guidance is intact."
    offered = model._agenerate.call_args.kwargs["tools"]
    assert "execute" not in {tool["function"]["name"] for tool in offered}
    assert states[-1]["steps"] == 4


@pytest.mark.parametrize("limit,expected", [(5, "Research complete."), (3, None)])
def test_delegation_has_visible_activity_and_one_shared_model_limit(
    agent_server,
    engine,
    scripted_model,
    limit,
    expected,
):
    child = AgentProfile(
        name="Research",
        description="Research synthetic workspace context",
        model="gpt-5-mini",
        instructions="Look up the requested context.",
        tools=["workspace_summary"],
    )
    profile = AgentProfile(
        name="Lead",
        description="Coordinate research",
        model="gpt-5-mini",
        instructions="Delegate research to the configured specialist.",
        tools=["workspace_summary"],
        specialists={"research": child},
        max_steps=limit,
    )
    run = enqueue(engine, profile.model_dump(), claim=True)
    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "research",
                            "description": "Read the workspace context.",
                        },
                        "id": "delegate",
                    }
                ],
            ),
            AIMessage(content="Research complete."),
        ]
    )
    specialist = scripted_model(
        [
            AIMessage(
                content="", tool_calls=[{"name": "workspace_summary", "args": {}, "id": "context"}]
            ),
            AIMessage(content="The current workspace context is available."),
        ]
    )
    states = []

    async def exercise():
        async def connect(role=None):
            return await MCPTools.connect(
                agent_server.internal_api_url,
                issue_run_token(
                    agent_server,
                    run.id,
                    run.lease_id,
                    audience="command-center-mcp",
                    role=role,
                ),
            )

        async def persist(state):
            states.append(state)

        return await run_graph(
            profile,
            "Research the workspace",
            await connect(),
            persist,
            model=model,
            specialist_tools={"research": await connect("research")},
            specialist_models={"research": specialist},
            checkpointer=InMemorySaver(),
            thread_id=str(run.id),
        )

    if expected:
        assert asyncio.run(exercise()) == expected
    else:
        with pytest.raises(ValueError, match="model_limit"):
            asyncio.run(exercise())
    assert states[-1]["steps"] == min(limit, 4)
    assert any(
        step["role"] == "research"
        and step["name"] == "workspace_summary"
        and step["state"] == "output-available"
        for step in states[-1]["tools"]
    )


def test_worker_saves_a_conversation_reply_and_durable_checkpoint(
    agent_server,
    engine,
    scripted_model,
    mocker,
):
    from command_center.agents.worker import perform_next
    from command_center.db.conversations import AgentMessage, AgentSession

    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Answer the task conversation.",
        tools=[],
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic conversation worker")
        db.add(actor)
        db.flush()
        task = Task(id=uuid4(), owner_id=actor.id, title="Research synthetic company")
        db.add(task)
        db.flush()
        configure_synthetic_spending(db, actor.id, profile.model_dump())
        conversation = AgentSession.open(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            task_id=task.id,
            opportunity_id=None,
            request_id=uuid4(),
        )
        message = conversation.receive(
            content="Help research this company",
            profile="lead",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
        )
        run_id, session_id, task_id = message.run_id, conversation.id, task.id
    model = scripted_model([AIMessage(content="I can start from the company sources.")])
    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        finished = db.get(AgentRun, run_id)
        assert finished.state == "completed", finished.error_code
        messages = db.scalars(
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.sequence)
        ).all()
        assert [message.author for message in messages] == ["user", "assistant"]
        assert messages[-1].content == "I can start from the company sources."
        assert db.get(Task, task_id).state == "open"
        from sqlalchemy import text

        assert (
            db.scalar(
                text("SELECT count(*) FROM agent_checkpoints.checkpoints WHERE thread_id = :id"),
                {"id": str(run_id)},
            )
            > 0
        )
    assert not perform_next(engine, agent_server, run_id)


def test_new_instruction_prevents_a_tool_planned_before_it(
    agent_server, engine, scripted_model, mocker
):
    from command_center.agents.worker import perform_next
    from command_center.db.conversations import AgentMessage, AgentSession

    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Follow the current request.",
        tools=["create_task"],
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic steering owner")
        db.add(actor)
        db.flush()
        scope = Task(id=uuid4(), owner_id=actor.id, title="Existing work")
        db.add(scope)
        db.flush()
        configure_synthetic_spending(db, actor.id, profile.model_dump())
        conversation = AgentSession.open(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            task_id=scope.id,
            opportunity_id=None,
            request_id=uuid4(),
        )
        first = conversation.receive(
            content="Create a research task",
            profile="lead",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
        )
        session_id, run_id, actor_id = conversation.id, first.run_id, actor.id

    def change_request_during_generation(messages):
        with Session(engine) as db, db.begin():
            db.get(AgentSession, session_id).receive(
                content="Do not create a task. Just explain the options.",
                profile="lead",
                configuration=profile.model_dump(),
                revision="synthetic",
                request_id=uuid4(),
            )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "create_task",
                    "args": {"title": "This must not be created"},
                    "id": "stale-plan",
                }
            ],
        )

    def answer_current_request(messages):
        assert any("Do not create a task" in message.text for message in messages)
        assert any(
            isinstance(message, ToolMessage) and message.status == "error" for message in messages
        )
        return AIMessage(content="Here are the options; no additional task was created.")

    model = scripted_model([change_request_during_generation, answer_current_request])
    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        run = db.get(AgentRun, run_id)
        assert run.state == "completed", run.error_code
        assert run.consumed_sequence == 2
        assert run.tool_steps()[0]["state"] == "output-error"
        assert list(db.scalars(select(Task.title).where(Task.owner_id == actor_id))) == [
            "Existing work"
        ]
        assert len(db.scalars(select(AgentRun).where(AgentRun.session_id == session_id)).all()) == 1
        assert (
            db.scalar(
                select(AgentMessage.content).where(
                    AgentMessage.session_id == session_id,
                    AgentMessage.author == "assistant",
                )
            )
            == "Here are the options; no additional task was created."
        )


def test_heartbeat_renews_and_cancels_an_inflight_provider_request(
    agent_server,
    engine,
    scripted_model,
    mocker,
):
    from datetime import timedelta
    from time import monotonic

    from command_center.agents.worker import perform_next
    from command_center.db.base import utc_now

    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Wait for provider output.",
        tools=[],
    )
    run = enqueue(engine, profile.model_dump())
    provider_cancelled = []

    async def slow_provider(messages):
        with Session(engine) as db, db.begin():
            db.get(AgentRun, run.id).lease_expires_at = utc_now() + timedelta(minutes=1)
        # Observe a committed renewal, rather than assuming a 100 ms scheduler deadline.
        deadline = monotonic() + 10
        while monotonic() < deadline:
            await asyncio.sleep(0.02)
            with Session(engine) as db, db.begin():
                current = db.get(AgentRun, run.id)
                if current.lease_expires_at > utc_now() + timedelta(minutes=4):
                    current.finish("cancelled")
                    break
        else:
            raise AssertionError("Heartbeat did not renew during the pending provider call")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            provider_cancelled.append(True)
            raise
        raise AssertionError("Cancelled work left its provider request running")

    model = scripted_model([slow_provider])
    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    mocker.patch("command_center.agents.worker.HEARTBEAT_SECONDS", 0.01)
    assert perform_next(engine, agent_server, run.id)
    assert provider_cancelled == [True]
    with Session(engine) as db:
        current = db.get(AgentRun, run.id)
        assert current.state == "cancelled"
        assert current.output is None
    assert not perform_next(engine, agent_server, run.id)


@pytest.mark.parametrize("delay_outreach", [False, True])
def test_parallel_specialists_do_not_hide_steering_from_the_lead(
    agent_server,
    engine,
    scripted_model,
    mocker,
    delay_outreach,
):
    from command_center.agents.runtime_control import WorkMiddleware
    from command_center.agents.worker import perform_next
    from command_center.db.conversations import AgentSession

    specialist = AgentProfile(
        name="Specialist",
        description="Prepare a synthetic task",
        model="gpt-5-mini",
        instructions="Follow the current request.",
        tools=["create_task"],
    )
    profile = AgentProfile(
        name="Lead",
        description="Coordinate",
        model="gpt-5-mini",
        instructions="Coordinate both specialists.",
        tools=["create_task"],
        specialists={
            "research": specialist.model_copy(update={"name": "Research"}),
            "outreach": specialist.model_copy(update={"name": "Outreach"}),
        },
        max_steps=8,
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic parallel steering")
        db.add(actor)
        db.flush()
        scope = Task(id=uuid4(), owner_id=actor.id, title="Coordinate work")
        db.add(scope)
        db.flush()
        configure_synthetic_spending(db, actor.id, profile.model_dump())
        conversation = AgentSession.open(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            task_id=scope.id,
            opportunity_id=None,
            request_id=uuid4(),
        )
        message = conversation.receive(
            content="Prepare research and outreach tasks",
            profile="lead",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
        )
        session_id, run_id, actor_id = conversation.id, message.run_id, actor.id

    started = []
    ready = asyncio.Event()
    outreach_started = asyncio.Event()
    research_consumed = asyncio.Event()
    updated_instruction = "Do not create any tasks. Explain both options."

    before_model = WorkMiddleware.abefore_model

    async def staggered_start(middleware, state, runtime):
        if delay_outreach and middleware.role == "outreach":
            outreach_started.set()
            await asyncio.wait_for(research_consumed.wait(), 2)
        return await before_model(middleware, state, runtime)

    mocker.patch.object(WorkMiddleware, "abefore_model", new=staggered_start)

    async def prepare_child(messages):
        started.append(True)
        if delay_outreach:
            await asyncio.wait_for(outreach_started.wait(), 2)
        if delay_outreach or len(started) == 2:
            with Session(engine) as db, db.begin():
                db.get(AgentSession, session_id).receive(
                    content=updated_instruction,
                    profile="lead",
                    configuration=profile.model_dump(),
                    revision="synthetic",
                    request_id=uuid4(),
                )
            ready.set()
        await asyncio.wait_for(ready.wait(), 2)
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "create_task",
                    "args": {"title": "Unwanted child task"},
                    "id": "same-child-call",
                }
            ],
        )

    def child_answer(messages):
        assert any(message.text == updated_instruction for message in messages)
        research_consumed.set()
        return AIMessage(content="The options are ready; nothing was created.")

    def lead_answer(messages):
        assert any(message.text == updated_instruction for message in messages)
        return AIMessage(content="Here are both options.")

    lead = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {"subagent_type": role, "description": "Prepare a task"},
                        "id": role,
                    }
                    for role in ("research", "outreach")
                ],
            ),
            lead_answer,
        ]
    )
    models = {
        "Lead": lead,
        "Research": scripted_model([prepare_child, child_answer]),
        "Outreach": scripted_model(
            [child_answer] if delay_outreach else [prepare_child, child_answer]
        ),
    }
    mocker.patch(
        "command_center.agents.worker.create_chat_model",
        side_effect=lambda settings, configured: models[configured.name],
    )
    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        finished = db.get(AgentRun, run_id)
        assert finished.state == "completed", finished.error_code
        assert finished.output == "Here are both options."
        assert finished.consumed_sequence == 2
        assert len(db.scalars(select(Task).where(Task.owner_id == actor_id)).all()) == 1
        skipped = [step for step in finished.tool_steps() if step["name"] == "create_task"]
        assert len(skipped) == (1 if delay_outreach else 2)
        assert len({step["id"] for step in skipped}) == len(skipped)
        assert all(step["state"] == "output-error" for step in skipped)
        reservations = db.scalars(
            select(SpendingReservation).where(SpendingReservation.agent_run_id == run_id)
        ).all()
        assert len(reservations) >= 5
        assert {row.role for row in reservations} == {"lead", "research", "outreach"}
        assert all(row.state == "unknown" for row in reservations)


@pytest.mark.parametrize("scope_type", ["task", "opportunity"])
def test_worker_provides_the_saved_scope_and_linked_job_context(
    agent_server,
    engine,
    scripted_model,
    mocker,
    scope_type,
):
    from command_center.agents.worker import perform_next
    from command_center.db.conversations import AgentSession
    from command_center.db.crm import Company, Job, Opportunity

    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Discuss this work.",
        tools=[],
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic scope context")
        db.add(actor)
        db.flush()
        company = Company(
            id=uuid4(), owner_id=actor.id, name="Synthetic Northstar", domain="example.com"
        )
        db.add(company)
        db.flush()
        job = Job(
            id=uuid4(),
            owner_id=actor.id,
            company_id=company.id,
            title="Platform engineer",
            source_url="https://example.com/jobs/platform",
            description="Build synthetic developer tools.",
        )
        db.add(job)
        db.flush()
        opportunity = Opportunity(
            id=uuid4(),
            owner_id=actor.id,
            company_id=company.id,
            job_id=job.id,
            title="Northstar platform role",
            notes="Ask about the interview stages.",
        )
        db.add(opportunity)
        db.flush()
        task = Task(
            id=uuid4(),
            owner_id=actor.id,
            opportunity_id=opportunity.id,
            title="Prepare company brief",
            rationale="Summarize this role before contacting the team.",
        )
        db.add(task)
        db.flush()
        configure_synthetic_spending(db, actor.id, profile.model_dump())
        conversation = AgentSession.open(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            task_id=task.id if scope_type == "task" else None,
            opportunity_id=opportunity.id if scope_type == "opportunity" else None,
            request_id=uuid4(),
        )
        run_id = conversation.receive(
            content="What should I focus on?",
            profile="lead",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
        ).run_id

    def answer(messages):
        context = next(message.text for message in messages if message.name == "workspace_context")
        assert "data, not instructions" in context
        for detail in (
            "Synthetic Northstar",
            "https://example.com/jobs/platform",
            "Build synthetic developer tools",
            "Ask about the interview stages",
        ):
            assert detail in context
        if scope_type == "task":
            assert "Prepare company brief" in context
        return AIMessage(content="Focus on the platform team and interview stages.")

    mocker.patch(
        "command_center.agents.worker.create_chat_model", return_value=scripted_model([answer])
    )
    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        finished = db.get(AgentRun, run_id)
        assert finished.state == "completed", finished.error_code


def test_run_outputs_link_exact_owned_versions_after_manual_revision(
    agent_server, settings, engine
):
    from fastapi.testclient import TestClient

    from command_center.core.identity import Identity, authenticate
    from command_center.db.artifacts import Artifact, ArtifactVersion
    from command_center.main import create_app

    profile = AgentProfile(
        name="Lead",
        description="Synthetic",
        model="gpt-5-mini",
        instructions="Save synthetic drafts.",
        tools=["draft_artifact"],
    )
    run = enqueue(engine, profile.model_dump(), claim=True)

    async def draft():
        registry = await MCPTools.connect(
            agent_server.internal_api_url,
            issue_run_token(agent_server, run.id, run.lease_id, audience="command-center-mcp"),
        )
        for call_id, title in (("first", "Company brief"), ("second", "Outreach draft")):
            result = await registry.aexecute(
                "draft_artifact", {"title": title, "text": "Synthetic output"}, call_id
            )
            assert "Tool unavailable" not in result

    asyncio.run(draft())
    with Session(engine) as db, db.begin():
        first = db.scalar(
            select(Artifact).where(
                Artifact.owner_id == run.owner_id, Artifact.title == "Company brief"
            )
        )
        original = db.scalar(select(ArtifactVersion).where(ArtifactVersion.artifact_id == first.id))
        original_id = str(original.id)
        first.append_text("A later manual revision", version_id=uuid4(), request_id=uuid4())
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(run.owner_id, "synthetic")
    with TestClient(app) as http:
        response = http.get(f"/api/v1/agent-runs/{run.id}/artifacts")
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["total"] == 2
        assert {item["title"] for item in saved["items"]} == {"Company brief", "Outreach draft"}
        assert all(item["version"] == 1 for item in saved["items"])
        assert (
            next(item["version_id"] for item in saved["items"] if item["title"] == "Company brief")
            == original_id
        )
        page = http.get(f"/api/v1/agent-runs/{run.id}/artifacts?limit=1&offset=1").json()
        assert page["total"] == 2 and len(page["items"]) == 1
        app.dependency_overrides[authenticate] = lambda: Identity(uuid4(), "synthetic-other")
        assert http.get(f"/api/v1/agent-runs/{run.id}/artifacts").status_code == 404


def test_job_discovery_saves_evidence_and_an_unsent_outreach_draft(
    agent_server, engine, scripted_model, mocker
):
    from command_center.db.artifacts import Artifact, ArtifactReview, ArtifactVersion
    from command_center.db.crm import Job, Opportunity
    from command_center.db.evidence import SourceRecord
    from command_center.integrations.public_research import PublicPage

    url = "https://example.com/jobs/platform-engineer"
    mocker.patch(
        "command_center.integrations.clients.SearxngClient.search",
        return_value=[
            {"title": "Platform Engineer", "url": url, "content": "Synthetic hiring page"}
        ],
    )
    fetch = mocker.patch(
        "command_center.api.leads.scrape_public",
        return_value=PublicPage(
            url=url, title="Platform Engineer", markdown="Build reliable platform tools."
        ),
    )
    profile = AgentProfile(
        name="Lead",
        description="Synthetic job discovery",
        model="gpt-5-mini",
        instructions="Find the requested job lead, save source evidence and draft outreach.",
        tools=["research_search", "capture_lead", "enrich_lead", "lead_evidence", "draft_artifact"],
        max_steps=8,
    )
    run = enqueue(engine, profile.model_dump(), claim=True)
    saved = {}

    def latest_result(messages):
        message = next(item for item in reversed(messages) if isinstance(item, ToolMessage))
        result = json.loads(message.content)
        if isinstance(result, list) and result and result[0].get("type") == "text":
            result = json.loads("".join(item["text"] for item in result))
        return result

    def call(name, args):
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])

    def capture(messages):
        found = latest_result(messages)[0]
        assert found["url"] == url
        return call(
            "capture_lead",
            {
                "url": found["url"],
                "title": found["title"],
                "company_name": "Synthetic Company",
                "snippet": found["content"],
            },
        )

    def enrich(messages):
        saved.update(latest_result(messages))
        return call("enrich_lead", {"opportunity_id": saved["opportunity_id"]})

    def read_evidence(messages):
        assert latest_result(messages)["provider"] == "public_http"
        return call("lead_evidence", {"opportunity_id": saved["opportunity_id"]})

    def draft(messages):
        sources = latest_result(messages)["items"]
        assert len(sources) == 2
        assert "Build reliable platform tools." in sources[0]["excerpt"]
        return call(
            "draft_artifact",
            {
                "title": "Synthetic Company outreach draft",
                "kind": "message",
                "text": f"Recipient: not provided\nSubject: Platform Engineer role\n\n"
                f"Hello, I am interested in the platform tools role.\n\nSource: {url}",
            },
        )

    model = scripted_model(
        [
            call("research_search", {"query": "Synthetic Company platform engineer"}),
            capture,
            enrich,
            read_evidence,
            draft,
            AIMessage(content="Saved the lead, source evidence and unsent outreach draft."),
        ]
    )

    async def exercise():
        tools = await MCPTools.connect(
            agent_server.internal_api_url,
            issue_run_token(agent_server, run.id, run.lease_id, audience="command-center-mcp"),
        )

        async def persist(state):
            pass

        return await run_graph(
            profile,
            "Find a Synthetic Company engineering lead and prepare an outreach draft.",
            tools,
            persist,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id=str(run.id),
        )

    assert "unsent outreach draft" in asyncio.run(exercise())
    fetch.assert_awaited_once()
    with Session(engine) as db:
        opportunity = db.scalar(select(Opportunity).where(Opportunity.owner_id == run.owner_id))
        assert str(opportunity.id) == saved["opportunity_id"]
        assert opportunity.stage == "researching"
        assert db.get(Job, opportunity.job_id).status == "unknown"
        sources = db.scalars(
            select(SourceRecord).where(SourceRecord.opportunity_id == opportunity.id)
        ).all()
        assert len(sources) == 2 and any(source.provider == "public_http" for source in sources)
        artifact = db.scalar(
            select(Artifact).where(Artifact.owner_id == run.owner_id, Artifact.kind == "message")
        )
        assert artifact.sensitivity == "private"
        version = db.scalar(
            select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
        )
        assert url in version.payload["text"]
        assert (
            db.scalar(
                select(ArtifactReview).where(ArtifactReview.artifact_version_id == version.id)
            )
            is None
        )


def test_document_evidence_becomes_a_proposal_until_human_review(
    agent_server, engine, scripted_model
):
    from command_center.db.artifacts import Artifact, ArtifactVersion
    from command_center.db.profile_facts import ProfileFact

    profile = AgentProfile(
        name="Application",
        description="Synthetic profile extraction",
        model="gpt-5-mini",
        instructions="Read the supplied document and propose supported facts for human review.",
        tools=["document_read", "propose_profile_fact", "approved_profile"],
        max_steps=5,
    )
    run = enqueue(engine, profile.model_dump(), claim=True)
    with Session(engine) as db, db.begin():
        artifact = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=run.owner_id,
            title="Synthetic extracted resume",
            kind="research",
            sensitivity="private",
            text="Synthetic Candidate\nSkills: Python",
            document_type_id=None,
            request_id=uuid4(),
        )
        db.flush()
        version_id = db.scalar(
            select(ArtifactVersion.id).where(ArtifactVersion.artifact_id == artifact.id)
        )

    def result(messages):
        raw = json.loads(next(m for m in reversed(messages) if isinstance(m, ToolMessage)).content)
        return json.loads("".join(item["text"] for item in raw)) if isinstance(raw, list) else raw

    def call(name, args):
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])

    saved = {}

    def propose(messages):
        source = result(messages)
        assert source["version_id"] == str(version_id)
        assert source["text"] == "Synthetic Candidate\nSkills: Python"
        return call(
            "propose_profile_fact",
            {
                "field": "skill",
                "value": "Python",
                "source_version_id": str(version_id),
                "source_excerpt": "Skills: Python",
            },
        )

    def read_approved(messages):
        saved.update(result(messages))
        assert saved["current"]["review_state"] == "proposed" and saved["active"] is None
        return call("approved_profile", {})

    def finish(messages):
        assert result(messages)["items"] == []
        return AIMessage(content="Proposed Python with evidence; human review is required.")

    model = scripted_model(
        [
            call("document_read", {"version_id": str(version_id)}),
            propose,
            read_approved,
            finish,
        ]
    )

    async def exercise():
        tools = await MCPTools.connect(
            agent_server.internal_api_url,
            issue_run_token(agent_server, run.id, run.lease_id, audience="command-center-mcp"),
        )

        async def persist(state):
            pass

        return await run_graph(
            profile,
            "Suggest profile facts from the synthetic extraction.",
            tools,
            persist,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id=str(run.id),
        )

    assert "human review is required" in asyncio.run(exercise())
    token = issue_run_token(agent_server, run.id, run.lease_id)
    with httpx.Client(base_url=agent_server.internal_api_url, trust_env=False) as http:
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}
        denied = http.post(
            f"/api/v1/profile/facts/{saved['id']}/reviews",
            headers=headers,
            json={
                "expected_version": saved["row_version"],
                "revision_id": saved["current"]["id"],
                "decision": "approved",
            },
        )
        assert denied.status_code == 403
        assert http.get("/api/v1/profile/facts", headers=headers).status_code == 403
        assert (
            http.post("/api/v1/profile/default-resume", headers=headers, json={}).status_code == 403
        )
        assert (
            http.get(f"/api/v1/documents/versions/{uuid4()}/text", headers=headers).status_code
            == 404
        )

        with Session(engine) as db, db.begin():
            fact = db.get(ProfileFact, saved["id"])
            assert fact.active_revision_id is None
            fact.review(
                revision_id=fact.current_revision_id,
                reviewer_id=run.owner_id,
                reviewer_is_human=True,
                decision="approved",
                reason=None,
                request_id=uuid4(),
            )
        approved = http.get("/api/v1/profile/facts/approved", headers=headers).json()["items"]
        assert len(approved) == 1
        assert approved[0]["value"] == "Python" and approved[0]["source_version_id"] == str(
            version_id
        )
