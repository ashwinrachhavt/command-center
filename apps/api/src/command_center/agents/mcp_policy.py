"""Reviewed route inventory. Unknown routes are never granted implicitly."""

import json
import re
from pathlib import Path
from typing import Any

POLICIES: dict[str, dict[str, str]] = json.loads(
    Path(__file__).with_name("mcp_policies.json").read_text()
)


def route_pattern(path: str) -> str:
    return re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(path))


def policy_capabilities() -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for operation, policy in POLICIES.items():
        if policy["policy"] in {"tool", "runtime"}:
            method, path = operation.split(" ", 1)
            result.setdefault(policy["name"], []).append((method, route_pattern(path)))
    result["catalog_execute"] = [route for routes in result.values() for route in routes]
    result["catalog_search"] = []
    return result


def catalog_tool_names() -> set[str]:
    return {policy["name"] for policy in POLICIES.values()} | {"catalog_search", "catalog_execute"}


def local_api_allowed(method: str, path: str) -> bool:
    return any(
        policy["policy"] == "tool"
        and method == operation.split(" ", 1)[0]
        and re.fullmatch(route_pattern(operation.split(" ", 1)[1]), path)
        for operation, policy in POLICIES.items()
    )


def register_operation(method: str, path: str, *, name: str, policy: str, reason: str) -> None:
    """Register a reviewed typed API extension before create_app (including lead intake).

    Normally add an entry to mcp_policies.json instead. The API's OpenAPI schema supplies
    arguments; executors can only invoke this exact method/path. No model URL is accepted.
    """
    if policy not in {"tool", "runtime", "human", "transport"} or not path.startswith("/api/v1/"):
        raise ValueError("Invalid MCP operation policy")
    POLICIES[f"{method.upper()} {path}"] = {"name": name, "policy": policy, "reason": reason}
    from command_center.core.capabilities import CAPABILITIES

    CAPABILITIES.update(policy_capabilities())


def coverage(openapi: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "operation": f"{method.upper()} {path}",
            **POLICIES.get(
                f"{method.upper()} {path}", {"policy": "unclassified", "reason": "Denied"}
            ),
        }
        for path, methods in openapi["paths"].items()
        if path.startswith("/api/v1/")
        for method in methods
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    ]
