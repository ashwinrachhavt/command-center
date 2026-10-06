import asyncio
import copy
import json
from uuid import uuid4

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from command_center.agents.application_workflow import run_application_workflow
from command_center.agents.config import AgentProfile
from command_center.agents.runtime_control import ExecutionStopped

PREPARATION, VERSION, SAVED, FACT = (str(uuid4()) for _ in range(4))
ANSWER = {
    "field_id": "f1",
    "value": "I built an accessible search product.",
    "fact_revision_ids": [FACT],
}


class DraftModel(BaseChatModel):
    seen: list = Field(default_factory=list)
    answers: list = Field(default_factory=lambda: [copy.deepcopy(ANSWER)])
    fail: bool = False

    @property
    def _llm_type(self):
        return "synthetic-application"

    def bind_tools(self, tools, **kwargs):
        assert kwargs == {"tool_choice": "DraftAnswers"}
        return self

    def _generate(self, messages, **kwargs):
        self.seen.append(messages)
        if self.fail:
            raise RuntimeError("synthetic provider failure")
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "draft",
                                "name": "DraftAnswers",
                                "args": {"answers": self.answers},
                            }
                        ],
                        usage_metadata={
                            "input_tokens": 120,
                            "output_tokens": 40,
                            "total_tokens": 160,
                        },
                    )
                )
            ]
        )


def item(field_id="f1", label="Describe a product you built", **changes):
    return {
        "field": {"id": field_id, "label": label, "type": "textarea", "value_state": "empty"},
        "answer": {
            "field_id": field_id,
            "value": None,
            "status": "needs_input",
            "origin": "missing",
        }
        | changes,
        "fact_revision_ids": [],
    }


class Tools:
    schemas = []

    def __init__(self):
        self.calls = []
        self.items = [item(), item("f2", "Work authorization"), item("f3", origin="human")]
        self.saved = False
        self.fail_save = False
        self.verify_failure = False

    async def aexecute(self, name, args, call_id):
        self.calls.append((name, args, call_id))
        if name == "application_context":
            items = copy.deepcopy(self.items)
            if self.saved:
                items[0]["answer"].update(
                    value="Wrong" if self.verify_failure else ANSWER["value"],
                    status="suggested",
                    origin="agent",
                )
                items[0]["fact_revision_ids"] = [FACT]
            result = {
                "preparation_id": PREPARATION,
                "version_id": SAVED if self.saved else VERSION,
                "items": items,
                "next_offset": None,
                "job_context": None,
            }
        elif name == "approved_profile":
            result = {
                "items": [
                    {
                        "id": FACT,
                        "field": "experience",
                        "value": "Built an accessible search product",
                        "context": None,
                    }
                ],
                "next_offset": None,
            }
        elif name == "suggest_application_answers":
            assert args == {
                "preparation_id": PREPARATION,
                "expected_version_id": VERSION,
                "answers": [ANSWER],
            }
            if self.fail_save:
                return json.dumps({"error": "Changed after drafting", "status_code": 409})
            self.saved = True
            result = {"preparation_id": PREPARATION, "version_id": SAVED, "suggestions_saved": 1}
        else:
            raise AssertionError(name)
        return json.dumps([{"type": "text", "text": json.dumps(result)}])


def profile(**kwargs):
    return AgentProfile(
        name="Application",
        description="Synthetic",
        model="synthetic",
        runtime="langgraph_application",
        application_preparation_id=PREPARATION,
        instructions="Grounded drafts",
        tools=[
            "application_context",
            "approved_profile",
            "document_read",
            "suggest_application_answers",
        ],
        max_steps=3,
        **kwargs,
    )


def test_one_model_call_saves_verifies_and_completed_checkpoint_never_repeats():
    async def run():
        model, tools, checkpoints, saver = DraftModel(), Tools(), [], InMemorySaver()

        async def checkpoint(state):
            checkpoints.append(state)

        kwargs = dict(model=model, checkpointer=saver, thread_id="one")
        result = await run_application_workflow(profile(), tools, checkpoint, **kwargs)
        assert "Saved and verified 1" in result
        count = len(tools.calls)
        assert (
            await run_application_workflow(
                profile(), tools, checkpoint, prior_state=checkpoints[-1], **kwargs
            )
            == result
        )
        assert len(model.seen) == 1 and len(tools.calls) == count == 4
        prompt = json.loads(model.seen[0][1].content)
        assert prompt["questions"] == [{"id": "f1", "question": "Describe a product you built"}]
        assert checkpoints[-1]["steps"] == 1
        assert checkpoints[-1]["usage"]["input_tokens"] == 120

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["citation", "field", "duplicate", "save", "verify"])
def test_invalid_or_unsaved_output_never_reports_success(failure):
    async def run():
        model, tools = DraftModel(), Tools()
        if failure == "citation":
            model.answers[0]["fact_revision_ids"] = [str(uuid4())]
        elif failure == "field":
            model.answers[0]["field_id"] = "f2"
        elif failure == "duplicate":
            model.answers *= 2
        elif failure == "save":
            tools.fail_save = True
        else:
            tools.verify_failure = True

        async def checkpoint(state):
            pass

        with pytest.raises(ExecutionStopped):
            await run_application_workflow(
                profile(),
                tools,
                checkpoint,
                model=model,
                checkpointer=InMemorySaver(),
                thread_id="bad",
            )
        assert len(model.seen) == 1
        assert sum(name == "suggest_application_answers" for name, _, _ in tools.calls) == (
            failure in {"save", "verify"}
        )

    asyncio.run(run())


def test_no_unknown_questions_needs_no_model_or_profile_read():
    async def run():
        model, tools = DraftModel(), Tools()
        tools.items[0]["answer"].update(value="Already saved", status="suggested")

        async def checkpoint(state):
            pass

        result = await run_application_workflow(
            profile(),
            tools,
            checkpoint,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id="known",
        )
        assert "No new supported" in result
        assert not model.seen and len(tools.calls) == 1

    asyncio.run(run())


def test_unknown_paid_call_is_not_retried_after_worker_recovery():
    async def run():
        model, tools, checkpoints, saver = DraftModel(fail=True), Tools(), [], InMemorySaver()

        async def checkpoint(state):
            checkpoints.append(state)

        kwargs = dict(model=model, checkpointer=saver, thread_id="recover")
        with pytest.raises(RuntimeError, match="synthetic"):
            await run_application_workflow(profile(), tools, checkpoint, **kwargs)
        with pytest.raises(ExecutionStopped, match="application_model_outcome_unknown"):
            await run_application_workflow(
                profile(), tools, checkpoint, prior_state=checkpoints[-1], **kwargs
            )
        assert len(model.seen) == 1

    asyncio.run(run())


def test_save_failure_recovery_does_not_redraft_or_repeat_write():
    async def run():
        model, tools, checkpoints, saver = DraftModel(), Tools(), [], InMemorySaver()
        tools.fail_save = True

        async def checkpoint(state):
            checkpoints.append(state)

        kwargs = dict(model=model, checkpointer=saver, thread_id="recover-save")
        for attempt in range(2):
            with pytest.raises(ExecutionStopped):
                await run_application_workflow(
                    profile(),
                    tools,
                    checkpoint,
                    prior_state=checkpoints[-1] if attempt else None,
                    **kwargs,
                )
        assert len(model.seen) == 1
        assert sum(name == "suggest_application_answers" for name, _, _ in tools.calls) == 1

    asyncio.run(run())
