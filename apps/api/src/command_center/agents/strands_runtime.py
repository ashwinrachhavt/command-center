"""Opt-in, single-agent Strands harness using the application's scoped controls."""

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from types import SimpleNamespace
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from jsonschema import ValidationError, validate
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from strands.types.content import Messages
from strands.types.tools import AgentTool, ToolSpec, ToolUse
from strands_harness import create_harness

from command_center.agents.chat_context import SummarySink
from command_center.agents.config import AgentProfile
from command_center.agents.read_cache import failed_tool_result
from command_center.agents.runtime import AgentTools
from command_center.agents.runtime_control import (
    ActivitySink,
    ExecutionStopped,
    InstructionSource,
    ProgressSink,
    RunControl,
)
from command_center.agents.spending import ModelSpendingGate
from command_center.agents.strands_model import HostModel


class ScopedTool(AgentTool):
    def __init__(self, schema: dict[str, Any], registry: AgentTools, bridge: HostModel) -> None:
        super().__init__()
        self.schema, self.registry, self.bridge = schema["function"], registry, bridge

    @property
    def tool_name(self) -> str:
        return str(self.schema["name"])

    @property
    def tool_spec(self) -> ToolSpec:
        return {
            "name": self.tool_name,
            "description": self.schema["description"],
            "inputSchema": {"json": self.schema["parameters"]},
        }

    @property
    def tool_type(self) -> str:
        return "command_center"

    async def stream(
        self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any
    ) -> AsyncGenerator[Any, None]:
        bridge = self.bridge
        call = {"name": self.tool_name, "args": tool_use["input"], "id": tool_use["toolUseId"]}

        async def invoke(request: ToolCallRequest) -> ToolMessage:
            bridge.check()
            try:
                validate(call["args"], self.schema["parameters"])
            except ValidationError:
                return ToolMessage(
                    "Invalid tool arguments; correct them before trying again.",
                    tool_call_id=tool_use["toolUseId"],
                    status="error",
                )
            return ToolMessage(
                await self.registry.aexecute(self.tool_name, call["args"], call["id"]),
                tool_call_id=call["id"],
            )

        try:
            bridge.check()
            result = await bridge.work.awrap_tool_call(
                ToolCallRequest(
                    tool_call=cast(Any, call),
                    tool=None,
                    state=bridge.state,
                    runtime=cast(Any, SimpleNamespace(config={"configurable": {}})),
                ),
                invoke,
            )
            if not isinstance(result, ToolMessage):
                raise ExecutionStopped("strands_tool_command_unsupported")
            yield {
                "toolUseId": call["id"],
                "status": "error" if failed_tool_result(result) else "success",
                "content": [{"text": str(result.content)}],
            }
        except Exception as exc:
            # SDK tool exceptions ordinarily become model-readable errors. Host failures
            # (limits, spending, lease loss) must terminate instead, before any next call.
            bridge.fatal = exc
            yield {
                "toolUseId": call["id"],
                "status": "error",
                "content": [{"text": "Execution stopped by the host."}],
            }


async def run_strands(
    profile: AgentProfile,
    prompt: str | list[BaseMessage],
    registry: AgentTools,
    checkpoint: ProgressSink,
    *,
    model: BaseChatModel,
    thread_id: str,
    instructions: InstructionSource | None = None,
    initial_sequence: int = 0,
    root_role: str = "lead",
    activity: ActivitySink | None = None,
    spending: ModelSpendingGate | None = None,
    resume: tuple[str, str] | None = None,
    prior_state: dict[str, Any] | None = None,
    summary_sink: SummarySink | None = None,
) -> str:
    """Execute once; durable run recovery and human-question resumes are not yet supported."""
    profile = AgentProfile.model_validate({**profile.model_dump(), "runtime": "strands"})
    if resume is not None or prior_state:
        raise ExecutionStopped("strands_resume_unsupported")
    control = RunControl(profile, checkpoint, initial_sequence, activity)
    bridge = HostModel(model, profile, control, root_role, spending, instructions, summary_sink)
    granted = set(profile.tools)
    exposed = granted if profile.prompt_tools is None else set(profile.prompt_tools)
    tools = [
        ScopedTool(schema, registry, bridge)
        for schema in registry.schemas
        if schema["function"]["name"] in granted & exposed
    ]
    initial = [HumanMessage(content=prompt)] if isinstance(prompt, str) else prompt
    # Disable host-incompatible defaults explicitly: no local offload/session files,
    # memory, shell, background work, hidden model retries or implicit tool grants.
    agent = create_harness(
        model=bridge,
        system_prompt=profile.instructions,
        tools=tools,
        builtin_tools=[],
        builtin_plugins=[],
        background_tasks=False,
        memory=False,
        skills=False,
        session=False,
        context_manager=False,
        caching=False,
        retry_strategy=None,
        callback_handler=None,
        messages=cast(Messages, [bridge.encode(message) for message in initial]),
    )
    pending = ""
    started = time.monotonic()
    message_index = 0
    output = ""

    async def flush() -> None:
        nonlocal pending, started
        if pending and activity is not None:
            await activity(
                "text-delta",
                root_role,
                {
                    "message_id": str(uuid5(NAMESPACE_URL, f"{thread_id}:strands:{message_index}")),
                    "delta": pending,
                },
            )
        pending, started = "", time.monotonic()

    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=32)

    async def pump() -> None:
        # SDK tracing attaches context variables around yields. Keep all generator
        # advancement and closure in one task, including cancellation.
        try:
            async with aclosing(cast(AsyncGenerator[Any, None], agent.stream_async())) as events:
                async for event in events:
                    await queue.put(event)
        except Exception as exc:
            await queue.put(exc)
        finally:
            task = asyncio.current_task()
            if task is not None and not task.cancelling():
                await queue.put(None)

    async with asyncio.timeout(profile.max_duration_seconds):
        pumping = asyncio.create_task(pump())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.08)
                except TimeoutError:
                    bridge.check()
                    await flush()
                    await control.report_progress()
                    continue
                bridge.check()
                if isinstance(event, Exception):
                    raise event
                if event is None:
                    break
                if event.get("data"):
                    pending += str(event["data"])
                    if len(pending) >= 512 or time.monotonic() - started >= 0.08:
                        await flush()
                if "message" in event and event["message"].get("role") == "assistant":
                    await flush()
                    message_index += 1
                if "result" in event:
                    output = "".join(
                        block.get("text", "") for block in event["result"].message["content"]
                    )
        finally:
            pumping.cancel()
            await asyncio.gather(pumping, return_exceptions=True)
    await flush()
    bridge.check()
    async with control.lock:
        await control.emit()
    return output
