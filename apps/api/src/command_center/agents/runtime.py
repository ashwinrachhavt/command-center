"""Deep Agents over scoped MCP tools and a durable, isolated virtual workspace."""

import asyncio
import time
from collections.abc import Mapping
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

from command_center.agents.config import AgentProfile
from command_center.agents.runtime_control import (
    ActivitySink,
    InstructionSource,
    ModelAccounting,
    ProgressSink,
    RunControl,
    WorkMiddleware,
    WorkState,
    tool_identity,
)

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


def domain_tools(registry: AgentTools) -> list[BaseTool]:
    def make_tool(schema: dict[str, Any]) -> BaseTool:
        description = schema["function"]
        name = str(description["name"])

        async def execute(**arguments: Any) -> str:
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
) -> CompiledStateGraph[Any, Any, Any, Any]:
    # Model callbacks also cover framework-owned context compaction calls.
    callbacks = [
        *(model.callbacks if isinstance(model.callbacks, list) else []),
        ModelAccounting(control, role),
    ]
    model = model.model_copy(update={"callbacks": callbacks})
    return create_deep_agent(
        model=model,
        system_prompt=profile.instructions,
        tools=domain_tools(registry),
        backend=StateBackend(),
        skills=[f"/skills/{role}/"] if profile.skill_files else None,
        permissions=[FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny")],
        subagents=subagents or [],
        middleware=[
            WorkMiddleware(
                control,
                role,
                delegates=frozenset(profile.specialists),
                instructions=instructions,
                nested=nested,
            )
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
) -> str:
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
    )
    messages = [HumanMessage(content=prompt)] if isinstance(prompt, str) else prompt
    graph_input: dict[str, Any] = {
        "messages": messages,
        "files": files,
        "instruction_sequence": initial_sequence,
    }
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": profile.max_steps * 5 + 10,
        "max_concurrency": profile.max_parallel_tools,
    }
    final: dict[str, Any]
    if activity is None:
        final = await graph.ainvoke(graph_input, config)
    else:
        final = {}

        async for streamed in graph.astream(
            graph_input,
            config,
            stream_mode=["messages", "values"],
            subgraphs=True,
        ):
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
                if len(pending[key][0]) >= 512 or now - started >= 0.1:
                    buffered, _ = pending.pop(key)
                    await activity(
                        "text-delta",
                        role,
                        {"message_id": message_id, "delta": buffered},
                    )
        await flush_pending()
    async with control.lock:
        control.sequence = max(
            control.sequence, final.get("instruction_sequence", initial_sequence)
        )
        await control.emit()
    # Provider reasoning blocks never become the visible response.
    return str(final["messages"][-1].text)
