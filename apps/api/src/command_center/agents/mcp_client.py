import asyncio
import json
from typing import Any, cast

from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, MCPToolCallResult


class MCPTools:
    """LangGraph-facing tools discovered from our authenticated MCP endpoint."""

    def __init__(self, url: str, token: str):
        self.call_id = ""

        async def call_identity(request: MCPToolCallRequest, handler: Any) -> MCPToolCallResult:
            headers = {**(request.headers or {}), "X-Tool-Call-ID": self.call_id}
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
        self.tools = {tool.name: tool for tool in asyncio.run(client.get_tools())}
        self.schemas = [convert_to_openai_tool(tool) for tool in self.tools.values()]

    def execute(self, name: str, arguments: dict[str, Any], call_id: str) -> str:
        self.call_id = call_id
        if name not in self.tools:
            return "Denied: this tool is not in the discovered capability list."
        result = asyncio.run(self.tools[name].ainvoke(arguments))
        return result if isinstance(result, str) else json.dumps(result, default=str)
