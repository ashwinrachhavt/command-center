"""Shared limits, steering and public activity for one root and its specialists."""

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Annotated, Any, NotRequired
from uuid import NAMESPACE_URL, UUID, uuid5

from deepagents.graph import DeepAgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from command_center.agents.config import AgentProfile

type ProgressSink = Callable[[dict[str, Any]], Awaitable[None]]
type InstructionSource = Callable[[int], Awaitable[tuple[int, list[BaseMessage]]]]
type ActivitySink = Callable[[str, str, dict[str, Any]], Awaitable[None]]

tool_identity: ContextVar[str] = ContextVar("agent_tool_identity", default="")


class WorkState(DeepAgentState):
    # Each graph must consume its own instructions. Child completion must not
    # overwrite the lead's cursor or collide with another child's state update.
    instruction_sequence: NotRequired[Annotated[int, PrivateStateAttr]]


class ExecutionStopped(ValueError):
    """A host-enforced limit or lost authority; never converted to a model tool error."""


class RunControl:
    def __init__(
        self,
        profile: AgentProfile,
        sink: ProgressSink,
        sequence: int = 0,
        activity: ActivitySink | None = None,
    ):
        self.profile, self.sink = profile, sink
        self.activity = activity
        self.lock = asyncio.Lock()
        self.parallel = asyncio.Semaphore(profile.max_parallel_tools)
        self.steps = 0
        self.tool_count = 0
        self.sequence = sequence
        self.initial_sequence = sequence
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.tools: dict[str, dict[str, Any]] = {}

    async def emit_activity(self, event_type: str, role: str, data: dict[str, Any]) -> None:
        if self.activity is not None:
            await self.activity(event_type, role, data)

    async def emit(self) -> None:
        """Caller holds lock, so snapshots cannot overtake each other on the way to SQL."""
        await self.sink(
            copy.deepcopy(
                {
                    "steps": self.steps,
                    "tool_count": self.tool_count,
                    "instruction_sequence": self.sequence,
                    "usage": self.usage,
                    "tools": list(self.tools.values()),
                }
            )
        )


class ModelAccounting(AsyncCallbackHandler):
    """Counts all actual model calls, including library compaction and specialists."""

    raise_error = True

    def __init__(self, control: RunControl, role: str):
        self.control, self.role = control, role

    async def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[BaseMessage]], **kwargs: Any
    ) -> None:
        control = self.control
        size = sum(len(str(message.content)) for batch in messages for message in batch)
        size += len(json.dumps(kwargs.get("invocation_params", {}).get("tools", []), default=str))
        async with control.lock:
            if size > control.profile.max_context_chars:
                raise ExecutionStopped("context_limit")
            if control.steps >= control.profile.max_steps:
                raise ExecutionStopped("model_limit")
            control.steps += 1
            await control.emit()

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        async with self.control.lock:
            for generation in response.generations:
                for output in generation:
                    usage = getattr(getattr(output, "message", None), "usage_metadata", None) or {}
                    for name in self.control.usage:
                        self.control.usage[name] += int(usage.get(name, 0))
            await self.control.emit()
            if any(self.control.usage.values()):
                await self.control.emit_activity(
                    "usage",
                    self.role,
                    {
                        **self.control.usage,
                        "total_tokens": sum(self.control.usage.values()),
                    },
                )


class WorkMiddleware(AgentMiddleware[WorkState, Any, Any]):
    state_schema = WorkState

    def __init__(
        self,
        control: RunControl,
        role: str,
        *,
        delegates: frozenset[str] = frozenset(),
        instructions: InstructionSource | None = None,
        nested: bool = False,
    ):
        self.control, self.role = control, role
        self.delegates, self.instructions = delegates, instructions
        self.nested = nested

    async def abefore_model(self, state: WorkState, runtime: Runtime[Any]) -> dict[str, Any] | None:
        if self.instructions is None:
            return None
        # A child may start after a sibling already consumed new instructions.
        # Its cursor begins at the run's input snapshot, not the sibling's cursor.
        previous = state.get("instruction_sequence", self.control.initial_sequence)
        sequence, messages = await self.instructions(previous)
        if sequence <= previous:
            return {"instruction_sequence": previous}
        self.control.sequence = max(self.control.sequence, sequence)
        return {"messages": messages, "instruction_sequence": sequence}

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        namespace = request.runtime.config.get("configurable", {}).get("checkpoint_ns", "")
        original_id = call["id"]
        if not original_id:
            raise ExecutionStopped("missing_tool_identity")
        call_id = (
            str(uuid5(NAMESPACE_URL, f"{namespace}:{original_id}")) if self.nested else original_id
        )
        control = self.control
        async with control.lock:
            if control.tool_count >= control.profile.max_tool_calls:
                raise ExecutionStopped("tool_limit")
            control.tool_count += 1
            control.tools[call_id] = {
                "id": call_id,
                "name": call["name"],
                "role": self.role,
                "state": "input-available",
                "output": None,
            }
            if call["name"] == "task":
                control.tools[call_id].update(
                    specialist=str(call["args"].get("subagent_type", ""))[:100],
                    summary=str(call["args"].get("description", ""))[:2000],
                )
            await control.emit()
            await control.emit_activity(
                "tool-input-available",
                self.role,
                {
                    "tool_call_id": call_id,
                    "tool_name": call["name"],
                    "input": call["args"],
                },
            )
        context = tool_identity.set(call_id)

        async def dispatch() -> ToolMessage | Command[Any]:
            if self.instructions is not None:
                planned_sequence = request.state.get(
                    "instruction_sequence", control.initial_sequence
                )
                sequence, _ = await self.instructions(planned_sequence)
                if sequence > planned_sequence:
                    return ToolMessage(
                        "The user added instructions after this operation was planned. "
                        "It was not started. Read the new instructions before planning again.",
                        tool_call_id=original_id,
                        status="error",
                    )
            return await handler(request)

        try:
            if call["name"] == "task" and call["args"].get("subagent_type") not in self.delegates:
                result: ToolMessage | Command[Any] = ToolMessage(
                    "Denied: this specialist is not configured for the current role.",
                    tool_call_id=original_id,
                    status="error",
                )
            elif call["name"] == "task":
                # A delegation must not occupy capacity needed by its own child tools.
                result = await dispatch()
            else:
                async with control.parallel:
                    result = await dispatch()
            content = result.content if isinstance(result, ToolMessage) else "Specialist finished."
            if isinstance(result, Command) and isinstance(result.update, dict):
                messages = result.update.get("messages", [])
                if messages:
                    content = messages[-1].content
            output = content if isinstance(content, str) else json.dumps(content, default=str)
            failed = isinstance(result, ToolMessage) and result.status == "error"
            failed = failed or output.startswith(("Denied:", "Tool unavailable"))
            async with control.lock:
                control.tools[call_id].update(
                    state="output-error" if failed else "output-available", output=output[:20000]
                )
                await control.emit()
                await control.emit_activity(
                    "tool-output-error" if failed else "tool-output-available",
                    self.role,
                    (
                        {"tool_call_id": call_id, "error_text": output[:20_000]}
                        if failed
                        else {"tool_call_id": call_id, "output": output[:20_000]}
                    ),
                )
            return result
        except Exception:
            async with control.lock:
                control.tools[call_id].update(state="output-error", output="Operation interrupted.")
                await control.emit()
                await control.emit_activity(
                    "tool-output-error",
                    self.role,
                    {"tool_call_id": call_id, "error_text": "Operation interrupted."},
                )
            raise
        finally:
            tool_identity.reset(context)
