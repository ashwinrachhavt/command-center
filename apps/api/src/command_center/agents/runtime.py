"""Deep Agents over scoped MCP tools and a durable, isolated virtual workspace."""

import asyncio
import time
from collections.abc import AsyncGenerator, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, uuid5

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemPermission
from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from command_center.agents.chat_context import ChatSummarizationMiddleware, SummarySink
from command_center.agents.config import AgentProfile
from command_center.agents.runtime_control import (
    ActivitySink,
    ExecutionStopped,
    InstructionSource,
    ModelAccounting,
    ProgressSink,
    RunControl,
    WorkMiddleware,
    WorkState,
    tool_identity,
)
from command_center.agents.spending import ModelSpendingGate

# Model prompts cannot expand this policy. Scripts require a separate sandbox backend.
register_harness_profile(
    "openai",
    HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        excluded_tools=frozenset({"execute"}),
    ),
)


class AgentTools(Protocol):
    schemas: list[dict[str, Any]]

    async def aexecute(self, name: str, arguments: dict[str, Any], call_id: str) -> str: ...


@dataclass(frozen=True)
class GraphQuestion:
    interrupt_id: str
    branch_id: str
    role: str
    tool_call_id: str
    prompt: str


@dataclass(frozen=True)
class GraphPaused:
    questions: list[GraphQuestion]


def domain_tools(registry: AgentTools, role: str) -> list[BaseTool]:
    def make_tool(schema: dict[str, Any]) -> BaseTool:
        description = schema["function"]
        name = str(description["name"])

        async def execute(**arguments: Any) -> str:
            if name == "ask_user":
                answer = interrupt(
                    {
                        "kind": "user_question",
                        "prompt": str(arguments["prompt"]),
                        "role": role,
                        "tool_call_id": tool_identity.get(),
                    }
                )
                if not isinstance(answer, str) or not answer.strip() or len(answer) > 20_000:
                    raise ExecutionStopped("invalid_question_answer")
                return "The user answered this question:\n" + answer
            return await registry.aexecute(name, arguments, tool_identity.get())

        return StructuredTool(
            name=name,
            description=description["description"],
            args_schema=description["parameters"],
            coroutine=execute,
        )

    return [make_tool(schema) for schema in registry.schemas]


def build_agent(
    role: str,
    profile: AgentProfile,
    registry: AgentTools,
    model: BaseChatModel,
    control: RunControl,
    *,
    subagents: list[CompiledSubAgent] | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    instructions: InstructionSource | None = None,
    nested: bool = False,
    spending: ModelSpendingGate | None = None,
    summary_sink: SummarySink | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    # Model callbacks also cover framework-owned context compaction calls.
    callbacks = [
        *(model.callbacks if isinstance(model.callbacks, list) else []),
        ModelAccounting(control, role, profile, spending),
    ]
    model = model.model_copy(update={"callbacks": callbacks})

    def no_retry(*args: Any, **kwargs: Any) -> BaseChatModel:
        # Deep Agents' compaction middleware otherwise wraps this model in three
        # implicit paid retries. Each provider attempt must be an explicit run call.
        return model

    object.__setattr__(model, "with_retry", no_retry)
    return create_deep_agent(
        model=model,
        system_prompt=profile.instructions,
        tools=domain_tools(registry, role),
        backend=StateBackend(),
        skills=[f"/skills/{role}/"] if profile.skill_files else None,
        permissions=[FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny")],
        subagents=subagents or [],
        middleware=[
            cast(
                Any,
                ChatSummarizationMiddleware(model, control.profile.max_context_chars, summary_sink),
            ),
            WorkMiddleware(
                control,
                role,
                delegates=frozenset(profile.specialists),
                instructions=instructions,
                nested=nested,
            ),
        ],
        state_schema=WorkState,
        checkpointer=checkpointer,
        name=role,
    )


async def run_graph(
    profile: AgentProfile,
    prompt: str | list[BaseMessage],
    registry: AgentTools,
    checkpoint: ProgressSink,
    *,
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver[Any],
    thread_id: str,
    specialist_tools: Mapping[str, AgentTools] | None = None,
    specialist_models: Mapping[str, BaseChatModel] | None = None,
    instructions: InstructionSource | None = None,
    initial_sequence: int = 0,
    root_role: str = "lead",
    activity: ActivitySink | None = None,
    spending: ModelSpendingGate | None = None,
    resume: tuple[str, str] | None = None,
    prior_state: dict[str, Any] | None = None,
    summary_sink: SummarySink | None = None,
) -> str | GraphPaused:
    pending: dict[tuple[str, str], tuple[str, float]] = {}
    delta_lock = asyncio.Lock()

    async def flush_pending() -> None:
        if activity is None:
            return
        async with delta_lock:
            for (role, message_id), (delta, _) in list(pending.items()):
                await activity("text-delta", role, {"message_id": message_id, "delta": delta})
                pending.pop((role, message_id))

    async def ordered_activity(event_type: str, role: str, data: dict[str, Any]) -> None:
        assert activity is not None
        await flush_pending()
        await activity(event_type, role, data)

    control = RunControl(
        profile,
        checkpoint,
        initial_sequence,
        ordered_activity if activity is not None else None,
        prior_state,
    )
    children: list[CompiledSubAgent] = []
    files = {}
    for role, configured in {root_role: profile, **profile.specialists}.items():
        for slug, content in configured.skill_files.items():
            if not content.startswith("---\n"):
                content = (
                    f"---\nname: {slug}\ndescription: {slug} workflow guidance\n---\n\n{content}"
                )
            files[f"/skills/{role}/{slug}/SKILL.md"] = create_file_data(content)
    for role, configured in profile.specialists.items():
        if not specialist_tools or not specialist_models:
            raise ValueError("Configured specialists need scoped tools and models")
        children.append(
            {
                "name": role,
                "description": configured.description,
                "runnable": build_agent(
                    role,
                    configured,
                    specialist_tools[role],
                    specialist_models[role],
                    control,
                    instructions=instructions,
                    nested=True,
                    spending=spending,
                ),
            }
        )
    graph = build_agent(
        root_role,
        profile,
        registry,
        model,
        control,
        subagents=children,
        checkpointer=checkpointer,
        instructions=instructions,
        spending=spending,
        summary_sink=summary_sink,
    )
    messages = [HumanMessage(content=prompt)] if isinstance(prompt, str) else prompt
    initial_input: dict[str, Any] = {
        "messages": messages,
        "files": files,
        "instruction_sequence": initial_sequence,
    }
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": profile.max_steps * 5 + 10,
        "max_concurrency": profile.max_parallel_tools,
    }
    snapshot = await graph.aget_state(config)

    def pending_interrupt_ids() -> set[str]:
        return {
            item.id for task in snapshot.tasks if task.result is None for item in task.interrupts
        }

    def paused() -> GraphPaused:
        pending_ids = pending_interrupt_ids()
        questions: list[GraphQuestion] = []
        for task in snapshot.tasks:
            for pending_interrupt in task.interrupts:
                if pending_interrupt.id not in pending_ids:
                    continue
                value = pending_interrupt.value
                if not isinstance(value, dict) or value.get("kind") != "user_question":
                    raise ExecutionStopped("unsupported_interrupt")
                questions.append(
                    GraphQuestion(
                        interrupt_id=pending_interrupt.id,
                        branch_id=str(task.id),
                        role=str(value.get("role", "")),
                        tool_call_id=str(value.get("tool_call_id", "")),
                        prompt=str(value.get("prompt", "")),
                    )
                )
        if not questions:
            raise ExecutionStopped("question_checkpoint_missing")
        return GraphPaused(questions)

    if pending_interrupt_ids():
        if resume is None or resume[0] not in pending_interrupt_ids():
            return paused()
        graph_input: Any = Command(resume={resume[0]: resume[1]})
    elif snapshot.values:
        if not snapshot.next:
            saved_messages = snapshot.values.get("messages", [])
            if not saved_messages:
                raise ExecutionStopped("checkpoint_output_missing")
            return str(saved_messages[-1].text)
        graph_input = None
    else:
        graph_input = initial_input
    final: dict[str, Any]
    if activity is None:
        final = await graph.ainvoke(graph_input, config)
    else:
        final = {}

        async def streamed_messages() -> AsyncGenerator[Any, None]:
            # A small chunk must become visible even when the provider pauses before
            # its next token. Never cancel an in-flight graph read on a flush timeout.
            async with aclosing(
                cast(
                    AsyncGenerator[Any, None],
                    graph.astream(
                        graph_input, config, stream_mode=["messages", "values"], subgraphs=True
                    ),
                )
            ) as events:
                reading: asyncio.Future[Any] | None = None
                try:
                    while True:
                        reading = asyncio.ensure_future(anext(events))
                        while not reading.done():
                            ready, _ = await asyncio.wait({reading}, timeout=0.08)
                            if not ready:
                                await flush_pending()
                        try:
                            yield reading.result()
                        except StopAsyncIteration:
                            return
                finally:
                    if reading is not None:
                        reading.cancel()
                        await asyncio.gather(reading, return_exceptions=True)

        async with aclosing(streamed_messages()) as streamed_events:
            async for streamed in streamed_events:
                namespace, mode, value = cast(tuple[tuple[str, ...], str, Any], streamed)
                if mode == "values":
                    if not namespace:
                        final = value
                    continue
                chunk, metadata = value
                if not isinstance(chunk, AIMessageChunk):
                    continue
                # Only public agent replies are streamed. Framework summaries and other
                # internal model calls may share the graph stream but are not UI messages.
                if metadata.get("langgraph_node") != "model":
                    continue
                delta = str(chunk.text)
                if not delta:
                    continue
                role = str(metadata.get("lc_agent_name") or root_role)[:100]
                identity = ":".join(
                    [
                        *(str(part) for part in namespace),
                        str(metadata.get("langgraph_node", "model")),
                        str(metadata.get("langgraph_step", "")),
                        str(chunk.id or ""),
                    ]
                )
                message_id = str(uuid5(NAMESPACE_URL, f"{thread_id}:{identity}"))
                key = (role, message_id)
                now = time.monotonic()
                async with delta_lock:
                    buffered, started = pending.get(key, ("", now))
                    pending[key] = (buffered + delta, started)
                    if len(pending[key][0]) >= 512 or now - started >= 0.08:
                        buffered, _ = pending.pop(key)
                        await activity(
                            "text-delta",
                            role,
                            {"message_id": message_id, "delta": buffered},
                        )
        await flush_pending()
    snapshot = await graph.aget_state(config)
    if pending_interrupt_ids():
        return paused()
    async with control.lock:
        control.sequence = max(
            control.sequence, final.get("instruction_sequence", initial_sequence)
        )
        await control.emit()
    # Provider reasoning blocks never become the visible response.
    return str(final["messages"][-1].text)
