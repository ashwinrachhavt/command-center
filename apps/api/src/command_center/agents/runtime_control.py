"""Shared limits, steering and public activity for one root and its specialists."""

import asyncio
import copy
import json
import random
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Annotated, Any, NotRequired
from uuid import NAMESPACE_URL, UUID, uuid5

from deepagents.graph import DeepAgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, PrivateStateAttr
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage, ToolCall, ToolMessage
from langchain_core.outputs import LLMResult
from langgraph.errors import GraphInterrupt
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from command_center.agents.config import AgentProfile
from command_center.agents.progress import progress_text, saved_findings
from command_center.agents.read_cache import failed_tool_result, immutable_read_key
from command_center.agents.spending import ModelSpendingGate, conservative_input_bound
from command_center.agents.telemetry import current_trace
from command_center.agents.tool_recovery import (
    MAX_READ_ATTEMPTS,
    MAX_RETRY_DELAY,
    safe_read,
    transient_exception,
    transient_result,
)
from command_center.db.spending import SpendingDenied

type ProgressSink = Callable[[dict[str, Any]], Awaitable[None]]
type InstructionSource = Callable[[int], Awaitable[tuple[int, list[BaseMessage]]]]
type ActivitySink = Callable[[str, str, dict[str, Any]], Awaitable[None]]

tool_identity: ContextVar[str] = ContextVar("agent_tool_identity", default="")

# Leave one turn for local saves and one for the supervisor's final answer.
SUPERVISOR_FINISH_CALLS = 2
COMPLETION_TOOLS = frozenset(
    {
        "capture_lead_content",
        "create_task",
        "draft_artifact",
        "save_record_work",
        "save_application_material",
        "suggest_application_answers",
        "propose_profile_fact",
        "ask_user",
        "catalog_execute",
    }
)


class WorkState(DeepAgentState):
    # Each graph must consume its own instructions. Child completion must not
    # overwrite the lead's cursor or collide with another child's state update.
    instruction_sequence: NotRequired[Annotated[int, PrivateStateAttr]]


class ExecutionStopped(ValueError):
    """A host-enforced limit or lost authority; never converted to a model tool error."""


class SpecialistBudgetExhausted(ValueError):
    """Return partial specialist work while preserving the supervisor's finish calls."""


class RunControl:
    def __init__(
        self,
        profile: AgentProfile,
        sink: ProgressSink,
        sequence: int = 0,
        activity: ActivitySink | None = None,
        prior_state: dict[str, Any] | None = None,
    ):
        self.profile, self.sink = profile, sink
        self.activity = activity
        self.lock = asyncio.Lock()
        self.parallel = asyncio.Semaphore(profile.max_parallel_tools)
        prior = prior_state or {}
        self.steps = int(prior.get("steps", 0))
        self.role_steps: dict[str, int] = dict(prior.get("role_steps", {}))
        self.tool_count = int(prior.get("tool_count", 0))
        self.sequence = max(sequence, int(prior.get("instruction_sequence", 0)))
        self.initial_sequence = sequence
        self.progress_index = int(prior.get("progress_index", 0))
        self.progress_completed = int(prior.get("progress_completed", 0))
        self.last_progress_at = time.monotonic()
        self.read_cache: dict[str, asyncio.Task[ToolMessage | Command[Any]]] = {}
        usage = prior.get("usage", {})
        self.usage = {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
        }
        self.tools = {
            str(item["id"]): copy.deepcopy(item)
            for item in prior.get("tools", [])
            if isinstance(item, dict) and item.get("id")
        }

    async def report_progress(self) -> None:
        """A deterministic, durable update; never an extra paid model call."""
        completed = sum(item["state"] != "input-available" for item in self.tools.values())
        if completed - self.progress_completed < (3 if not self.progress_index else 5) and (
            time.monotonic() - self.last_progress_at < 20
        ):
            return
        async with self.lock:
            # All callers share this lock, including concurrently completing specialists.
            completed = sum(item["state"] != "input-available" for item in self.tools.values())
            if completed - self.progress_completed < (3 if not self.progress_index else 5) and (
                time.monotonic() - self.last_progress_at < 20
            ):
                return
            self.progress_index += 1
            self.progress_completed = completed
            self.last_progress_at = time.monotonic()
            await self.emit()
            await self.emit_activity(
                "text-delta",
                "lead",
                {
                    "message_id": f"progress-{self.progress_index}",
                    "delta": progress_text(list(self.tools.values())),
                },
            )

    async def emit_activity(self, event_type: str, role: str, data: dict[str, Any]) -> None:
        if self.activity is not None:
            await self.activity(event_type, role, data)

    async def emit(self) -> None:
        """Caller holds lock, so snapshots cannot overtake each other on the way to SQL."""
        await self.sink(
            copy.deepcopy(
                {
                    "steps": self.steps,
                    "role_steps": self.role_steps,
                    "tool_count": self.tool_count,
                    "instruction_sequence": self.sequence,
                    "usage": self.usage,
                    "tools": list(self.tools.values()),
                    "progress_index": self.progress_index,
                    "progress_completed": self.progress_completed,
                }
            )
        )


class ModelAccounting(AsyncCallbackHandler):
    """Counts all actual model calls, including library compaction and specialists."""

    raise_error = True

    def __init__(
        self,
        control: RunControl,
        role: str,
        profile: AgentProfile,
        spending: ModelSpendingGate | None,
        *,
        nested: bool = False,
    ):
        self.control, self.role, self.profile = control, role, profile
        self.spending = spending
        self.nested = nested

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        control = self.control
        size = sum(len(str(message.content)) for batch in messages for message in batch)
        size += len(json.dumps(kwargs.get("invocation_params", {}).get("tools", []), default=str))
        async with control.lock:
            if size > control.profile.max_context_chars:
                raise ExecutionStopped("context_limit")
            if self.nested and (
                control.steps >= control.profile.max_steps - SUPERVISOR_FINISH_CALLS
                or control.role_steps.get(self.role, 0) >= self.profile.max_steps
            ):
                raise SpecialistBudgetExhausted()
            if control.steps >= control.profile.max_steps:
                raise ExecutionStopped("model_limit")
            control.steps += 1
            control.role_steps[self.role] = control.role_steps.get(self.role, 0) + 1
            await control.emit()
        if self.spending is not None:
            try:
                await self.spending.reserve(
                    run_id,
                    role=self.role,
                    provider=self.profile.provider,
                    model=self.profile.model,
                    input_tokens=conservative_input_bound(
                        messages, kwargs.get("invocation_params", {})
                    ),
                    output_tokens=self.profile.max_output_tokens,
                )
            except SpendingDenied as exc:
                raise ExecutionStopped(exc.code) from exc

        if trace := current_trace.get():
            schemas = kwargs.get("invocation_params", {}).get("tools", [])
            trace.model_start(
                run_id,
                self.role,
                self.profile.provider,
                self.profile.model,
                sum(len(str(m.content)) for batch in messages for m in batch),
                len(json.dumps(schemas, default=str)),
                len(schemas),
                messages=[message for batch in messages for message in batch],
            )

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        call_usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
        async with self.control.lock:
            for generation in response.generations:
                for output in generation:
                    usage = getattr(getattr(output, "message", None), "usage_metadata", None) or {}
                    usage = {
                        **usage,
                        "cached_input_tokens": min(
                            int(usage.get("input_tokens", 0)),
                            max(0, int(usage.get("input_token_details", {}).get("cache_read", 0))),
                        ),
                    }
                    for name in self.control.usage:
                        count = int(usage.get(name, 0))
                        call_usage[name] += count
                        self.control.usage[name] += count
            await self.control.emit()
            if any(self.control.usage.values()):
                await self.control.emit_activity(
                    "usage",
                    self.role,
                    {
                        **self.control.usage,
                        "total_tokens": self.control.usage["input_tokens"]
                        + self.control.usage["output_tokens"],
                    },
                )
        if trace := current_trace.get():
            trace.model_end(
                run_id,
                call_usage,
                output=[
                    getattr(output, "message", None)
                    for batch in response.generations
                    for output in batch
                ],
            )
        if self.spending is not None:
            await self.spending.settle(
                run_id,
                call_usage["input_tokens"],
                call_usage["output_tokens"],
            )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if trace := current_trace.get():
            trace.model_end(run_id, {}, error=True)
        if self.spending is not None:
            await self.spending.unknown(run_id, "spending_usage_unknown")


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

    def lookup_remaining(self, name: str) -> int | None:
        role_profile = self.control.profile.specialists.get(self.role)
        limits = [
            value
            for value in (
                self.control.profile.tool_call_limits.get(name),
                role_profile.tool_call_limits.get(name) if role_profile else None,
            )
            if value is not None
        ]
        if not limits:
            return None
        used = sum(
            int(item.get("attempts", 1))
            for item in self.control.tools.values()
            if (item.get("summary") if item["name"] == "catalog_execute" else item["name"]) == name
        )
        return max(0, min(limits) - used)

    def model_remaining(self) -> int:
        remaining = self.control.profile.max_steps - self.control.steps
        if self.nested:
            remaining -= SUPERVISOR_FINISH_CALLS
            profile = self.control.profile.specialists.get(self.role)
            if profile is not None:
                remaining = min(
                    remaining, profile.max_steps - self.control.role_steps.get(self.role, 0)
                )
        return max(0, remaining)

    def completion_call(self, call: ToolCall) -> bool:
        name = call["name"]
        if name == "catalog_execute":
            name = str(call["args"].get("tool_name", ""))
            # Already-discovered API writes remain possible; catalog reads and
            # network-backed research cannot bypass the save phase.
            if name.startswith("cc_"):
                return not safe_read(call)
        return name in COMPLETION_TOOLS - {"catalog_execute"}

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        control = self.control
        remaining = max(0, control.profile.max_tool_calls - control.tool_count)
        model_remaining = self.model_remaining()
        final_answer = model_remaining <= 1 or remaining == 0
        finishing = model_remaining <= 2 or remaining <= 2
        role_profile = control.profile.specialists.get(self.role)
        limited_names = set(control.profile.tool_call_limits)
        if role_profile is not None:
            limited_names.update(role_profile.tool_call_limits)
        hint = (
            f"Shared remaining budget: {remaining} tool calls and "
            f"{max(0, control.profile.max_steps - control.steps)} model calls. "
            f"This agent has at most {model_remaining} model calls including this one. "
            "Reuse saved results. Prioritize requested saves over optional research."
        )
        if limited_names:
            hint += (
                " Remaining lookup quotas: "
                + ", ".join(
                    f"{name}={self.lookup_remaining(name)}" for name in sorted(limited_names)
                )
                + ". Never exceed a quota in a parallel batch or retry an exhausted tool."
            )
        if final_answer:
            hint += (
                " Finish now with a final response using existing results and save receipts. "
                "Do not call tools. Clearly identify any requested output that remains unsaved "
                "or unsupported; do not claim the entire request is complete unless it is."
            )
        elif finishing:
            hint += (
                " Save-and-finish phase: stop lookups and delegation. Save all remaining "
                "requested outputs from available evidence now, batching independent saves "
                "within the remaining tool budget. For catalog_execute, use only already-known "
                "save operations. Mark missing evidence explicitly. The next turn is for the "
                "final response."
            )
        elif model_remaining <= 4 or remaining <= max(4, control.profile.max_tool_calls // 4):
            hint += " Finish research now and prepare the requested saves; omit optional lookups."

        def available(tool: Any) -> bool:
            name = (
                str(tool.get("function", tool).get("name", ""))
                if isinstance(tool, dict)
                else tool.name
            )
            return (
                not final_answer
                and self.lookup_remaining(name) != 0
                and (not finishing or name in COMPLETION_TOOLS)
                and (name != "task" or model_remaining > SUPERVISOR_FINISH_CALLS + 2)
            )

        return await handler(
            request.override(
                tools=[tool for tool in request.tools if available(tool)],
                # Keep the long system prefix stable for provider prompt caching.
                # This small, transient hint is not saved in canonical graph history.
                messages=[*request.messages, HumanMessage(content=hint, name="execution_budget")],
            )
        )

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
        limited = False
        finishing_denied = False
        budget_name = (
            str(call["args"].get("tool_name", ""))
            if call["name"] == "catalog_execute"
            else call["name"]
        )
        async with control.lock:
            existing = control.tools.get(call_id)
            if existing is None:
                if control.tool_count >= control.profile.max_tool_calls:
                    raise ExecutionStopped("tool_limit")
                limited = self.lookup_remaining(budget_name) == 0
                # The planning call has already been charged by ModelAccounting.
                finishing_denied = self.model_remaining() <= 1 and not self.completion_call(call)
                control.tool_count += 1
                control.tools[call_id] = {
                    "id": call_id,
                    "name": call["name"],
                    "role": self.role,
                    "state": "input-available",
                    "output": None,
                    "budget_denied": limited,
                    "finishing_denied": finishing_denied,
                    "attempts": 1,
                }
                if call["name"] == "task":
                    control.tools[call_id].update(
                        specialist=str(call["args"].get("subagent_type", ""))[:100],
                        summary=str(call["args"].get("description", ""))[:2000],
                    )
                elif call["name"] == "catalog_execute":
                    control.tools[call_id]["summary"] = str(call["args"].get("tool_name", ""))[:100]
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
            elif existing.get("name") != call["name"] or existing.get("role") != self.role:
                raise ExecutionStopped("tool_identity_conflict")
            else:
                limited = bool(existing.get("budget_denied"))
                finishing_denied = bool(existing.get("finishing_denied"))
        context = tool_identity.set(call_id)
        recoverable = safe_read(call)

        async def steering() -> ToolMessage | None:
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
            return None

        async def invoke() -> ToolMessage | Command[Any]:
            while True:
                try:
                    result = await handler(request)
                    transient, delay = (
                        transient_result(result.content)
                        if recoverable and isinstance(result, ToolMessage)
                        else (False, None)
                    )
                except Exception as exc:
                    transient, delay = transient_exception(exc)
                    if not transient or not recoverable:
                        raise
                    result = ToolMessage(
                        "The read service is temporarily unavailable. Continue with available "
                        "evidence or explain the missing information; do not infer success.",
                        tool_call_id=original_id,
                        status="error",
                    )
                if not transient:
                    return result
                attempt = int(control.tools[call_id].get("attempts", 1))
                if attempt >= MAX_READ_ATTEMPTS or (delay is not None and delay > MAX_RETRY_DELAY):
                    return result
                # Reserve before sleeping; a cancelled attempt remains charged, never replayed
                # for free. The run deadline and heartbeat cancel this await normally.
                async with control.lock:
                    if (
                        control.tool_count >= control.profile.max_tool_calls
                        or self.lookup_remaining(budget_name) == 0
                    ):
                        return result
                    control.tool_count += 1
                    control.tools[call_id]["attempts"] = attempt + 1
                    await control.emit()
                await asyncio.sleep(max(delay or 0, random.uniform(0.25, 0.5) * 2 ** (attempt - 1)))
                if updated := await steering():
                    return updated

        async def dispatch() -> ToolMessage | Command[Any]:
            if updated := await steering():
                return updated
            key = immutable_read_key(call)
            if key is None:
                return await invoke()
            key = f"{self.role}:{control.sequence}:{key}"
            task = control.read_cache.get(key)
            if task is None:
                if len(control.read_cache) >= 32:
                    expired = next(
                        (key for key, task in control.read_cache.items() if task.done()), None
                    )
                    if expired is None:
                        return await invoke()
                    control.read_cache.pop(expired)

                task = asyncio.create_task(invoke())
                control.read_cache[key] = task
            try:
                result = await task
            except BaseException:
                if control.read_cache.get(key) is task:
                    control.read_cache.pop(key, None)
                raise
            if not isinstance(result, ToolMessage):
                if control.read_cache.get(key) is task:
                    control.read_cache.pop(key, None)
                return result
            if (
                len(str(result.content)) > 32_000 or failed_tool_result(result)
            ) and control.read_cache.get(key) is task:
                control.read_cache.pop(key, None)
            return result.model_copy(update={"tool_call_id": original_id})

        try:
            if finishing_denied:
                result: ToolMessage | Command[Any] = ToolMessage(
                    "Research and discovery are closed for this run. Do not retry this call. "
                    "Save the requested outputs with the evidence already available, then "
                    "report saved references and any missing work.",
                    tool_call_id=original_id,
                    status="error",
                )
            elif limited:
                result = ToolMessage(
                    "This tool's lookup budget is used. Continue with saved context and existing "
                    "results; omit unsupported claims and save a useful concise draft.",
                    tool_call_id=original_id,
                    status="error",
                )
            elif call["name"] == "task" and call["args"].get("subagent_type") not in self.delegates:
                result = ToolMessage(
                    "Denied: this specialist is not configured for the current role.",
                    tool_call_id=original_id,
                    status="error",
                )
            elif call["name"] == "task":
                # A delegation must not occupy capacity needed by its own child tools.
                try:
                    result = await dispatch()
                except SpecialistBudgetExhausted:
                    specialist = str(call["args"].get("subagent_type", ""))
                    result = ToolMessage(
                        "The specialist returned partial work to preserve your completion budget. "
                        "Use the saved evidence below to finish the requested outputs; do not "
                        "delegate again or imply missing outputs were saved.\n\n"
                        + saved_findings(
                            [
                                item
                                for item in control.tools.values()
                                if item["role"] == specialist
                                and item["state"] == "output-available"
                            ]
                        ),
                        tool_call_id=original_id,
                    )
            else:
                async with control.parallel:
                    result = await dispatch()
            content = result.content if isinstance(result, ToolMessage) else "Specialist finished."
            if isinstance(result, Command) and isinstance(result.update, dict):
                messages = result.update.get("messages", [])
                if messages:
                    content = messages[-1].content
            output = content if isinstance(content, str) else json.dumps(content, default=str)
            failed = isinstance(result, ToolMessage) and failed_tool_result(result)
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
            await control.report_progress()
            return result
        except GraphInterrupt:
            # A durable human question is pending, not a failed tool execution.
            raise
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
