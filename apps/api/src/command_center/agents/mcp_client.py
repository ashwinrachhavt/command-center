import asyncio
import json
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any, cast

from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, MCPToolCallResult


class MCPTools:
    """Scoped async tools; discovery and calls share the worker's event loop."""

    def __init__(self, tools: list[BaseTool], identity: ContextVar[str]):
        self.tools = {tool.name: tool for tool in tools}
        self.schemas = [convert_to_openai_tool(tool) for tool in tools]
        self.identity = identity

    @classmethod
    async def connect(cls, url: str, token: str) -> "MCPTools":
        identity: ContextVar[str] = ContextVar("mcp_call_identity", default="")

        async def call_identity(request: MCPToolCallRequest, handler: Any) -> MCPToolCallResult:
            headers = {**(request.headers or {}), "X-Tool-Call-ID": identity.get()}
            return cast(MCPToolCallResult, await handler(request.override(headers=headers)))

        client = MultiServerMCPClient(
            {
                "command_center": {
                    "transport": "streamable_http",
                    "url": url.rstrip("/") + "/mcp/",
                    "headers": {"Authorization": f"Bearer {token}"},
                    "timeout": 45.0,
                }
            },
            tool_interceptors=[call_identity],
        )
        return cls(await client.get_tools(), identity)

    @classmethod
    async def connect_many(
        cls, url: str, tokens: Mapping[str | None, str], *, concurrency: int
    ) -> dict[str | None, "MCPTools"]:
        capacity = asyncio.Semaphore(concurrency)

        async def connect(token: str) -> "MCPTools":
            async with capacity:
                return await cls.connect(url, token)

        async with asyncio.TaskGroup() as group:
            tasks = {role: group.create_task(connect(token)) for role, token in tokens.items()}
        return {role: task.result() for role, task in tasks.items()}

    async def aexecute(self, name: str, arguments: dict[str, Any], call_id: str) -> str:
        if name not in self.tools:
            return "Denied: this tool is not in the discovered capability list."
        if not call_id or len(call_id) > 200:
            raise ValueError("A bounded stable tool-call identity is required")
        context = self.identity.set(call_id)
        try:
            result = await self.tools[name].ainvoke(arguments)
            return result if isinstance(result, str) else json.dumps(result, default=str)
        finally:
            self.identity.reset(context)
