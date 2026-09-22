"""Deep Agents over scoped MCP tools and a durable, isolated virtual workspace."""

from collections.abc import Mapping
from typing import Any, Protocol

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
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from command_center.agents.config import AgentProfile
from command_center.agents.runtime_control import (
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
        ModelAccounting(control),
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
) -> str:
    control = RunControl(profile, checkpoint, initial_sequence)
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
    final = await graph.ainvoke(
        {"messages": messages, "files": files, "instruction_sequence": initial_sequence},
        {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": profile.max_steps * 5 + 10,
            "max_concurrency": profile.max_parallel_tools,
        },
    )
    async with control.lock:
        control.sequence = max(
            control.sequence, final.get("instruction_sequence", initial_sequence)
        )
        await control.emit()
    # Provider reasoning blocks never become the visible response.
    return str(final["messages"][-1].text)
