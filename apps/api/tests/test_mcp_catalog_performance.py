import asyncio
from uuid import uuid4

from command_center.agents.config import AgentProfile
from command_center.agents.mcp_catalog import CatalogProvider, DeniedTool
from command_center.agents.tools import ToolRegistry


def test_lookup_builds_only_one_tool_and_reloads_scope_each_time(settings, mocker):
    profile = AgentProfile(
        name="Catalog", description="Synthetic", model="synthetic", instructions="Read."
    )
    registry = ToolRegistry(settings, profile, uuid4(), uuid4(), "synthetic-token")
    registry.schemas = []
    schema = {"type": "object", "properties": {}}
    for index in range(100):
        registry.add(f"synthetic_{index}", "Synthetic", schema, lambda _: {})
    factory = mocker.Mock(return_value=(registry, True, "first-identity"))
    provider = CatalogProvider(factory)
    build = mocker.spy(provider, "_build_tool")

    async def exercise():
        first = await provider._get_tool("synthetic_50")
        assert first.name == "synthetic_50"
        assert "operation_id" in first.parameters["required"]
        assert first._call_id == "first-identity"
        assert build.call_count == 1
        assert "operation_id" not in schema["properties"]
        factory.return_value = registry, False, "second-identity"
        second = await provider._get_tool("synthetic_50")
        assert second._call_id == "second-identity"
        assert "operation_id" not in second.parameters["properties"]
        assert build.call_count == 2
        registry.schemas = []  # Scope was revoked between requests.
        denied = await provider._get_tool("synthetic_50")
        assert isinstance(denied, DeniedTool)
        assert build.call_count == 2
        assert factory.call_count == 3

    asyncio.run(exercise())
