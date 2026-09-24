"""Durable branch-specific agent question and saver recovery regressions."""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.agents.checkpoints import checkpoint_store
from command_center.agents.config import AgentProfile
from command_center.agents.runtime import GraphPaused, run_graph
from command_center.agents.worker import _saved_interrupts, perform_next, recover_stale_questions
from command_center.core.identity import Identity, authenticate
from command_center.db.agent_questions import AgentQuestion, AgentResumeIntent
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.conversations import AgentMessage, AgentSession
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor, AuditEvent, Task
from command_center.db.spending import SpendingPolicy, SpendingRateCard
from command_center.main import create_app


class QuestionTools:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": "Pause for one required human answer.",
                "parameters": {
                    "type": "object",
                    "properties": {"prompt": {"type": "string"}},
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    async def aexecute(self, name: str, arguments: dict[str, Any], call_id: str) -> str:
        raise AssertionError("ask_user must interrupt locally before MCP execution")


def question_profile() -> AgentProfile:
    return AgentProfile(
        name="Lead",
        description="Synthetic durable question agent",
        model="gpt-5-mini",
        instructions="Ask once when a required input is missing.",
        tools=["ask_user"],
        max_steps=4,
    )


def configure_spending(db: Session, owner_id, profile: AgentProfile) -> None:
    card = SpendingRateCard.create(
        db,
        owner_id=owner_id,
        name="Synthetic question rates",
        source_label="Synthetic question fixture",
        rates={
            "models": [
                {
                    "provider": profile.provider,
                    "model": profile.model,
                    "input_per_million_micros": 0,
                    "output_per_million_micros": 0,
                    "fixed_micros": 1,
                }
            ],
            "tools": [],
        },
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


def queued_run(engine, profile: AgentProfile) -> tuple[Any, Any, Any]:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Synthetic question owner")
        db.add(owner)
        db.flush()
        configure_spending(db, owner.id, profile)
        task = Task(id=uuid4(), owner_id=owner.id, title="Answer a required question")
        db.add(task)
        db.flush()
        conversation = AgentSession.open(
            db,
            record_id=uuid4(),
            owner_id=owner.id,
            task_id=task.id,
            opportunity_id=None,
            request_id=uuid4(),
        )
        message = conversation.receive(
            content="Prepare the answer, asking if required context is missing.",
            profile="lead",
            configuration=profile.model_dump(mode="json"),
            revision="synthetic-question",
            request_id=uuid4(),
        )
        return owner.id, conversation.id, message.run_id


def human_client(settings, engine, owner_id):
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner_id, "synthetic-question-owner")
    return TestClient(app)


def test_question_waits_answers_once_and_resumes_exact_run(
    settings, agent_server, engine, scripted_model, mocker
):
    profile = question_profile()
    owner_id, session_id, run_id = queued_run(engine, profile)
    resumed_messages: list[str] = []

    def finish(messages):
        resumed_messages.extend(str(message.text) for message in messages)
        return AIMessage(content="The location preference is Seattle.")

    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_user",
                        "args": {"prompt": "Which city should this target?"},
                        "id": "location-question",
                    }
                ],
            ),
            finish,
        ]
    )
    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, run_id)

    with human_client(settings, engine, owner_id) as client:
        response = client.get(f"/api/v1/agent-runs/{run_id}/questions")
        assert response.status_code == 200, response.text
        [question] = response.json()
        assert question["state"] == "open"
        assert question["role"] == "lead"
        assert question["tool_call_id"] == "location-question"
        assert question["interrupt_id"] and question["branch_id"]
        with Session(engine) as db:
            waiting = db.get(AgentRun, run_id)
            assert waiting.tool_steps()[0]["state"] == "input-available"

        key = uuid4()
        body = {"answer": "Seattle", "expected_version": question["row_version"]}
        stale = client.post(
            f"/api/v1/agent-runs/{run_id}/questions/{question['id']}/answer",
            headers={"Idempotency-Key": str(uuid4())},
            json={"answer": "Seattle", "expected_version": question["row_version"] + 1},
        )
        assert stale.status_code == 409
        answered = client.post(
            f"/api/v1/agent-runs/{run_id}/questions/{question['id']}/answer",
            headers={"Idempotency-Key": str(key)},
            json=body,
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["state"] == "answered"
        replay = client.post(
            f"/api/v1/agent-runs/{run_id}/questions/{question['id']}/answer",
            headers={"Idempotency-Key": str(key)},
            json=body,
        )
        assert replay.status_code == 200 and replay.json() == answered.json()
        conflict = client.post(
            f"/api/v1/agent-runs/{run_id}/questions/{question['id']}/answer",
            headers={"Idempotency-Key": str(uuid4())},
            json={"answer": "Portland", "expected_version": question["row_version"]},
        )
        assert conflict.status_code == 409

        app = client.app
        app.dependency_overrides[authenticate] = lambda: Identity(uuid4(), "foreign-owner")
        assert client.get(f"/api/v1/agent-runs/{run_id}/questions").status_code == 404
        assert (
            client.post(
                f"/api/v1/agent-runs/{run_id}/questions/{question['id']}/answer",
                headers={"Idempotency-Key": str(uuid4())},
                json=body,
            ).status_code
            == 404
        )

    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        run = db.get(AgentRun, run_id)
        question = db.scalar(select(AgentQuestion).where(AgentQuestion.run_id == run_id))
        intent = db.scalar(select(AgentResumeIntent).where(AgentResumeIntent.run_id == run_id))
        assert run.state == "completed" and run.output == "The location preference is Seattle."
        assert question.state == "resumed" and intent.state == "applied"
        assert any("Seattle" in text for text in resumed_messages), resumed_messages
        messages = db.scalars(
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.sequence)
        ).all()
        assert [message.author for message in messages] == ["user", "assistant"]


def test_multiple_branch_questions_resume_only_the_answered_interrupt(engine):
    profile = question_profile()
    _, _, run_id = queued_run(engine, profile)
    with Session(engine) as db, db.begin():
        run = AgentRun.claim(db, run_id)
        assert run and run.lease_id
        AgentQuestion.capture_checkpoint(
            db,
            run=run,
            lease_id=run.lease_id,
            interruptions=[
                {
                    "interrupt_id": "interrupt-research",
                    "branch_id": "branch-research",
                    "role": "research",
                    "tool_call_id": "research-call",
                    "prompt": "Which market?",
                },
                {
                    "interrupt_id": "interrupt-outreach",
                    "branch_id": "branch-outreach",
                    "role": "outreach",
                    "tool_call_id": "outreach-call",
                    "prompt": "Which recipient?",
                },
            ],
            request_id=run.id,
        )
    with Session(engine) as db, db.begin():
        conversation = db.get(AgentSession, db.get(AgentRun, run_id).session_id)
        steering = conversation.receive(
            content="Keep both branches concise.",
            profile="lead",
            configuration=profile.model_dump(mode="json"),
            revision="synthetic-question",
            request_id=uuid4(),
        )
        assert steering.run_id == run_id
        assert db.get(AgentRun, run_id).state == "waiting_for_user"
    with Session(engine) as db, db.begin():
        research = db.scalar(
            select(AgentQuestion)
            .where(AgentQuestion.run_id == run_id, AgentQuestion.role == "research")
            .with_for_update()
        )
        research.answer_once(
            db,
            answer="Developer tools",
            expected_version=research.row_version,
            request_id=uuid4(),
        )
    with Session(engine) as db, db.begin():
        run = AgentRun.claim(db, run_id)
        assert run and run.lease_id
        AgentQuestion.capture_checkpoint(
            db,
            run=run,
            lease_id=run.lease_id,
            interruptions=[
                {
                    "interrupt_id": "interrupt-outreach",
                    "branch_id": "branch-outreach",
                    "role": "outreach",
                    "tool_call_id": "outreach-call",
                    "prompt": "Which recipient?",
                }
            ],
            request_id=run.id,
        )
    with Session(engine) as db:
        questions = db.scalars(
            select(AgentQuestion).where(AgentQuestion.run_id == run_id).order_by(AgentQuestion.role)
        ).all()
        assert [(item.role, item.state) for item in questions] == [
            ("outreach", "open"),
            ("research", "resumed"),
        ]
        run = db.get(AgentRun, run_id)
        assert run.state == "waiting_for_user" and run.lease_id is None
    with Session(engine) as db, db.begin():
        run = db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        run.finish("cancelled")
    with Session(engine) as db, db.begin():
        questions = db.scalars(
            select(AgentQuestion).where(AgentQuestion.run_id == run_id).order_by(AgentQuestion.role)
        ).all()
        assert [(item.role, item.state) for item in questions] == [
            ("outreach", "cancelled"),
            ("research", "resumed"),
        ]
        assert db.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_id == questions[0].id,
                AuditEvent.action == "agent_question.cancelled",
            )
        )
        with pytest.raises(RecordConflict, match="no longer open"):
            questions[0].answer_once(
                db,
                answer="Someone else",
                expected_version=questions[0].row_version,
                request_id=uuid4(),
            )


def test_native_parallel_specialist_interrupts_resume_only_the_addressed_branch(
    scripted_model,
):
    specialist = AgentProfile(
        name="Specialist",
        description="Ask for one required input",
        model="gpt-5-mini",
        instructions="Ask once, then finish from the answer.",
        tools=["ask_user"],
        max_steps=6,
    )
    profile = AgentProfile(
        name="Lead",
        description="Coordinate two question branches",
        model="gpt-5-mini",
        instructions="Delegate both branches and summarize their results.",
        tools=["ask_user"],
        specialists={
            "research": specialist.model_copy(update={"name": "Research"}),
            "outreach": specialist.model_copy(update={"name": "Outreach"}),
        },
        max_steps=12,
    )
    calls = {"lead": 0, "research": 0, "outreach": 0}

    def lead_delegate(messages):
        calls["lead"] += 1
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "task",
                    "args": {"subagent_type": role, "description": f"Prepare {role}"},
                    "id": f"delegate-{role}",
                }
                for role in ("research", "outreach")
            ],
        )

    def lead_finish(messages):
        calls["lead"] += 1
        assert any("Research resumed" in str(message.text) for message in messages)
        assert any("Outreach resumed" in str(message.text) for message in messages)
        return AIMessage(content="Both specialist answers were applied once.")

    def ask(role, prompt, call_id):
        def reply(messages):
            calls[role] += 1
            return AIMessage(
                content="",
                tool_calls=[{"name": "ask_user", "args": {"prompt": prompt}, "id": call_id}],
            )

        return reply

    def finish(role, answer, output):
        def reply(messages):
            calls[role] += 1
            assert any(answer in str(message.text) for message in messages)
            return AIMessage(content=output)

        return reply

    models = {
        "lead": scripted_model([lead_delegate, lead_finish]),
        "research": scripted_model(
            [
                ask("research", "Which market should research cover?", "research-question"),
                finish("research", "Developer tools", "Research resumed once."),
            ]
        ),
        "outreach": scripted_model(
            [
                ask("outreach", "Who should outreach target?", "outreach-question"),
                finish("outreach", "Hiring manager", "Outreach resumed once."),
            ]
        ),
    }
    saver = InMemorySaver()
    states: list[dict[str, Any]] = []

    async def persist(state):
        states.append(state)

    async def exercise():
        first = await run_graph(
            profile,
            "Prepare research and outreach in parallel.",
            QuestionTools(),
            persist,
            model=models["lead"],
            specialist_tools={"research": QuestionTools(), "outreach": QuestionTools()},
            specialist_models={"research": models["research"], "outreach": models["outreach"]},
            checkpointer=saver,
            thread_id="native-parallel-questions",
        )
        assert isinstance(first, GraphPaused)
        by_role = {question.role: question for question in first.questions}
        assert set(by_role) == {"research", "outreach"}
        assert len({question.interrupt_id for question in first.questions}) == 2
        assert len({question.branch_id for question in first.questions}) == 2

        second = await run_graph(
            profile,
            "ignored after checkpoint",
            QuestionTools(),
            persist,
            model=models["lead"],
            specialist_tools={"research": QuestionTools(), "outreach": QuestionTools()},
            specialist_models={"research": models["research"], "outreach": models["outreach"]},
            checkpointer=saver,
            thread_id="native-parallel-questions",
            resume=(by_role["research"].interrupt_id, "Developer tools"),
            prior_state=states[-1],
        )
        assert isinstance(second, GraphPaused)
        assert [(item.role, item.interrupt_id, item.branch_id) for item in second.questions] == [
            (
                "outreach",
                by_role["outreach"].interrupt_id,
                by_role["outreach"].branch_id,
            )
        ]
        assert calls == {"lead": 1, "research": 2, "outreach": 1}
        checkpoint = await saver.aget_tuple(
            {"configurable": {"thread_id": "native-parallel-questions"}}
        )
        assert [item["role"] for item in _saved_interrupts(checkpoint)] == ["outreach"], [
            (task_id, channel) for task_id, channel, _ in checkpoint.pending_writes
        ]

        final = await run_graph(
            profile,
            "ignored after checkpoint",
            QuestionTools(),
            persist,
            model=models["lead"],
            specialist_tools={"research": QuestionTools(), "outreach": QuestionTools()},
            specialist_models={"research": models["research"], "outreach": models["outreach"]},
            checkpointer=saver,
            thread_id="native-parallel-questions",
            resume=(by_role["outreach"].interrupt_id, "Hiring manager"),
            prior_state=states[-1],
        )
        assert final == "Both specialist answers were applied once."

    asyncio.run(exercise())
    assert calls == {"lead": 2, "research": 2, "outreach": 2}


def test_saver_and_resume_ledger_reconcile_crashes(agent_server, engine, scripted_model, mocker):
    profile = question_profile()
    _, _, run_id = queued_run(engine, profile)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        run = AgentRun.claim(db, run_id)
        assert run and run.lease_id
        stale_lease = run.lease_id

    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_user",
                        "args": {"prompt": "Which format is required?"},
                        "id": "format-question",
                    }
                ],
            ),
            AIMessage(content="Use the requested PDF format."),
        ]
    )

    async def interrupt_then_crash():
        async with checkpoint_store(agent_server) as saver:
            return await run_graph(
                profile,
                "Prepare the output",
                QuestionTools(),
                lambda state: asyncio.sleep(0),
                model=model,
                checkpointer=saver,
                thread_id=str(run_id),
            )

    paused = asyncio.run(interrupt_then_crash())
    assert isinstance(paused, GraphPaused)
    with Session(engine) as db, db.begin():
        running = db.get(AgentRun, run_id)
        assert running.lease_id == stale_lease
        running.lease_expires_at = utc_now() - timedelta(seconds=1)
    assert recover_stale_questions(engine, agent_server, run_id) == 1

    with Session(engine) as db, db.begin():
        question = db.scalar(
            select(AgentQuestion).where(AgentQuestion.run_id == run_id).with_for_update()
        )
        question.answer_once(
            db,
            answer="PDF",
            expected_version=question.row_version,
            request_id=uuid4(),
        )
        running = AgentRun.claim(db, run_id)
        assert running and running.lease_id
        resume_lease = running.lease_id

    async def resume_then_crash():
        async with checkpoint_store(agent_server) as saver:
            return await run_graph(
                profile,
                "ignored after checkpoint",
                QuestionTools(),
                lambda state: asyncio.sleep(0),
                model=model,
                checkpointer=saver,
                thread_id=str(run_id),
                resume=(paused.questions[0].interrupt_id, "PDF"),
            )

    assert asyncio.run(resume_then_crash()) == "Use the requested PDF format."
    with Session(engine) as db, db.begin():
        running = db.get(AgentRun, run_id)
        assert running.lease_id == resume_lease
        running.lease_expires_at = utc_now() - timedelta(seconds=1)
    assert recover_stale_questions(engine, agent_server, run_id) == 1

    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, run_id)
    with Session(engine) as db:
        run = db.get(AgentRun, run_id)
        intent = db.scalar(select(AgentResumeIntent).where(AgentResumeIntent.run_id == run_id))
        assert run.state == "completed" and run.output == "Use the requested PDF format."
        assert intent.state == "applied"


def test_question_migration_refuses_to_drop_durable_interrupts(engine, migration_config):
    profile = question_profile()
    _, _, run_id = queued_run(engine, profile)
    with Session(engine) as db, db.begin():
        run = AgentRun.claim(db, run_id)
        assert run and run.lease_id
        AgentQuestion.capture_checkpoint(
            db,
            run=run,
            lease_id=run.lease_id,
            interruptions=[
                {
                    "interrupt_id": "migration-interrupt",
                    "branch_id": "migration-branch",
                    "role": "lead",
                    "tool_call_id": "migration-call",
                    "prompt": "Keep this question across rollback attempts?",
                }
            ],
            request_id=run.id,
        )

    try:
        # Exercise this guard directly: later migrations have their own refusal
        # conditions and may contain durable synthetic fixtures from earlier runs.
        revision = ScriptDirectory.from_config(migration_config).get_revision(
            "0016_agent_questions"
        )
        assert revision is not None
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="durable agent questions"),
        ):
            revision.module.downgrade()
        with Session(engine) as db:
            question = db.scalar(select(AgentQuestion).where(AgentQuestion.run_id == run_id))
            assert question is not None and question.prompt.startswith("Keep this question")
            assert db.get(AgentRun, run_id).state == "waiting_for_user"
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DELETE FROM agent_resume_intents WHERE run_id = %s", (run_id,)
            )
            connection.exec_driver_sql("DELETE FROM agent_questions WHERE run_id = %s", (run_id,))
            connection.exec_driver_sql(
                "UPDATE agent_runs SET state='cancelled', lease_id=NULL, lease_expires_at=NULL, "
                "completed_at=now() WHERE id = %s",
                (run_id,),
            )
