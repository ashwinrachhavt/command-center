"""One typed catalog for FastMCP HTTP and the authenticated local stdio proxy."""

import copy
import json
import re
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastmcp.server.providers import Provider
from fastmcp.tools import Tool, ToolResult
from mcp.types import ToolAnnotations
from pydantic import PrivateAttr
from starlette.concurrency import run_in_threadpool

from command_center.agents.mcp_policy import POLICIES
from command_center.agents.tools import ToolRegistry


def resolve_schema(value: Any, openapi: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [resolve_schema(item, openapi) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        ref: Any = openapi
        for part in value["$ref"].removeprefix("#/").split("/"):
            ref = ref[part]
        return resolve_schema({**ref, **{k: v for k, v in value.items() if k != "$ref"}}, openapi)
    return {key: resolve_schema(item, openapi) for key, item in value.items()}


def add_api_tools(registry: ToolRegistry, openapi: dict[str, Any], *, local: bool) -> None:
    """Compile only reviewed operations; reuse existing handwritten tool handlers."""
    for operation, policy in POLICIES.items():
        name = policy["name"]
        if name in registry.executors or (not local and name not in registry.profile.tools):
            continue
        method, path = operation.split(" ", 1)
        api = openapi["paths"].get(path, {}).get(method.lower())
        if api is None:
            continue
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        params = [p for p in api.get("parameters", []) if p["in"] in {"path", "query"}]
        for param in params:
            schema["properties"][param["name"]] = resolve_schema(param["schema"], openapi)
            if param.get("required"):
                schema["required"].append(param["name"])
        body = api.get("requestBody", {})
        if body.get("content", {}).get("application/json"):
            schema["properties"]["body"] = resolve_schema(
                body["content"]["application/json"]["schema"], openapi
            )
            if body.get("required"):
                schema["required"].append("body")
        # Guidance requires only a target, never purported human approval input.
        if policy["policy"] in {"human", "transport"} or (local and policy["policy"] == "runtime"):
            schema["required"] = []

        def execute(
            args: dict[str, Any],
            *,
            verb: str = method,
            route: str = path,
            parameters: list[dict[str, Any]] = params,
            rule: dict[str, str] = policy,
        ) -> Any:
            if rule["policy"] in {"human", "transport"} or (local and rule["policy"] == "runtime"):
                return requirement_result(rule)
            for param in parameters:
                if param["in"] == "path":
                    route = route.replace(
                        "{" + param["name"] + "}", quote(str(args[param["name"]]), safe="")
                    )
            query = {
                p["name"]: args[p["name"]]
                for p in parameters
                if p["in"] == "query" and p["name"] in args
            }
            return registry.request(verb, route.removeprefix("/api/v1/"), args.get("body"), query)

        registry.add(name, f"{api.get('summary', name)}. {policy['reason']}", schema, execute)


def requirement_result(policy: dict[str, str]) -> dict[str, Any]:
    runtime = policy["policy"] == "runtime"
    return {
        "status": "context_required" if runtime else "human_required",
        "reason": policy["reason"],
        "next_step": (
            "Create or select an owned conversation with cc_conversations_create_session, "
            "then use cc_conversations_receive_message to request this task workflow."
        )
        if runtime
        else (
            "Open the corresponding Command Center section and complete this action "
            "in your signed-in session."
        ),
        "executed": False,
    }


def tool_policy(name: str) -> dict[str, str] | None:
    return next((p for p in POLICIES.values() if p["name"] == name), None)


def readonly(name: str) -> bool:
    from command_center.core.capabilities import CAPABILITIES

    if name in {"research_search", "connected_context", "gmail_search", "catalog_search"}:
        return True
    rules = CAPABILITIES.get(name, [])
    return bool(rules) and all(method == "GET" for method, _ in rules)


class CatalogTool(Tool):
    _registry: ToolRegistry = PrivateAttr()
    _local: bool = PrivateAttr()
    _call_id: str = PrivateAttr()

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        arguments = dict(arguments)
        operation_id = arguments.pop("operation_id", None) if self._local else None
        call_id = operation_id if self._local else self._call_id
        policy = tool_policy(self.name)
        if self._local and policy and policy["policy"] in {"runtime", "human", "transport"}:
            return ToolResult(content=json.dumps(requirement_result(policy)))
        if (not call_id and (not self._local or not readonly(self.name))) or (
            call_id is not None and (not isinstance(call_id, str) or len(call_id) > 200)
        ):
            return ToolResult(content="Denied: a stable tool-call ID is required.")
        result = await run_in_threadpool(
            self._registry.execute, self.name, arguments, call_id or str(uuid4())
        )
        return ToolResult(content=result)


class CatalogProvider(Provider):
    def __init__(self, factory: Callable[[], tuple[ToolRegistry, bool, str]]):
        super().__init__()
        self.factory = factory

    async def _list_tools(self) -> Sequence[Tool]:
        registry, local, call_id = await run_in_threadpool(self.factory)
        result: list[Tool] = []
        for entry in registry.schemas:
            fn = entry["function"]
            schema = copy.deepcopy(fn["parameters"])
            if local and not readonly(fn["name"]):
                schema["properties"]["operation_id"] = {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": (
                        "Unique operation identifier. Reuse it with identical arguments when "
                        "retrying this action; use a new identifier for a new action."
                    ),
                }
                policy = tool_policy(fn["name"])
                if not policy or policy["policy"] == "tool":
                    schema.setdefault("required", []).append("operation_id")
            tool = CatalogTool(
                name=fn["name"],
                description=fn["description"],
                parameters=schema,
                annotations=ToolAnnotations(
                    readOnlyHint=readonly(fn["name"]), destructiveHint=False, openWorldHint=True
                ),
            )
            tool._registry, tool._local, tool._call_id = registry, local, call_id
            result.append(tool)
        return result

    async def _get_tool(self, name: str, version: Any = None) -> Tool | None:
        # No name-only cache: each request gets its own credentials, grant and schema.
        result = next((tool for tool in await self._list_tools() if tool.name == name), None)
        return result or DeniedTool(name=name, parameters={"type": "object"})


class DeniedTool(Tool):
    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="Denied: this tool is not granted to this run.")


def add_catalog_tools(registry: ToolRegistry, openapi: dict[str, Any], *, local: bool) -> None:
    """Two small schemas give the lead progressive access to the reviewed catalog.

    catalog_execute is an explicit broad grant, never inferred for specialists. Each
    discovered operation still validates its own schema and passes the API boundary.
    """
    if not {"catalog_search", "catalog_execute"}.intersection(registry.profile.tools):
        return
    from command_center.agents.mcp_policy import catalog_tool_names
    from command_center.core.capabilities import CAPABILITIES

    grants = sorted(
        (set(CAPABILITIES) | catalog_tool_names()) - {"catalog_search", "catalog_execute"}
    )
    profile = registry.profile.model_copy(update={"tools": grants})
    catalog = ToolRegistry(
        registry.settings, profile, registry.actor_id, registry.run_id, registry.token, local=local
    )
    add_api_tools(catalog, openapi, local=local)

    def search(args: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            "creation": "create",
            "creating": "create",
            "contacts": "contact",
            "companies": "company",
            "tasks": "task",
            "documents": "document",
            "docs": "document",
            "files": "document",
            "uploads": "uploaded",
            "contents": "content",
            "emails": "email",
            "mail": "email",
        }
        ignored = {
            "crm",
            "capability",
            "capabilities",
            "operation",
            "operations",
            "a",
            "the",
            "my",
            "most",
            "from",
            "in",
            "access",
            "get",
        }
        words = [
            aliases.get(word, word)
            for word in re.findall(r"[a-z0-9]+", args.get("query", "").lower())
            if word not in ignored
        ]
        matches = [
            entry["function"]
            for entry in catalog.schemas
            if all(
                word in (entry["function"]["name"] + " " + entry["function"]["description"]).lower()
                for word in words
            )
        ]
        offset = args.get("offset", 0)
        limit = args.get("limit", 3)
        result = {
            "items": matches[offset : offset + limit],
            "offset": offset,
            "total": len(matches),
            "next_offset": offset + limit if offset + limit < len(matches) else None,
        }
        if not matches:
            result["hint"] = (
                "Try a short action/entity query: document vault, read document, Gmail search, "
                "or create contact. No matches does not establish that access is unavailable."
            )
        return result

    def execute(args: dict[str, Any]) -> Any:
        name = args["tool_name"]
        policy = tool_policy(name)
        if policy and (
            policy["policy"] in {"human", "transport"} or (local and policy["policy"] == "runtime")
        ):
            return requirement_result(policy)
        result = catalog.execute(name, args["arguments"], registry.call_id)
        try:
            return json.loads(result)
        except ValueError:
            return {"message": result}

    if "catalog_search" in registry.profile.tools:
        registry.add(
            "catalog_search",
            "Find Command Center operations and their exact argument schemas. Search before "
            "catalog_execute. Human review remains required for approval, sending, browser "
            "control and credential actions.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                    "offset": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            search,
        )
    if "catalog_execute" in registry.profile.tools:
        registry.add(
            "catalog_execute",
            "Execute one reviewed Command Center operation found through catalog_search, using "
            "its exact typed arguments. Requires the explicit broad workspace catalog grant; "
            "each API still enforces ownership, workflow scope and human review.",
            {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "arguments": {"type": "object"},
                },
                "required": ["tool_name", "arguments"],
                "additionalProperties": False,
            },
            execute,
        )
