"""Conservative recovery policy for host-reviewed reads, never external writes."""

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

TRANSIENT_STATUSES = {408, 429, 502, 503, 504}
MAX_READ_ATTEMPTS = 3
MAX_RETRY_DELAY = 8.0


def retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def safe_read(call: Mapping[str, Any]) -> bool:
    # Host policy, not a remote MCP annotation or model-provided retry instruction.
    from command_center.core.capabilities import CAPABILITIES

    name = call.get("name")
    if name == "catalog_execute":
        args = call.get("args")
        if not isinstance(args, dict):
            return False
        name = args.get("tool_name")
    if not isinstance(name, str):
        return False
    if name == "catalog_search":
        return True
    routes = CAPABILITIES.get(name, [])
    return bool(routes) and all(method == "GET" for method, _ in routes)


def transient_exception(error: Exception) -> tuple[bool, float | None]:
    if isinstance(error, httpx.HTTPStatusError):
        return (
            error.response.status_code in TRANSIENT_STATUSES,
            retry_after(error.response.headers.get("Retry-After")),
        )
    return isinstance(
        error, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
    ), None


def transient_result(value: Any, depth: int = 0) -> tuple[bool, float | None]:
    """Inspect transport envelopes only; document text is never a retry directive."""
    if depth > 12:
        return False, None
    if isinstance(value, str):
        try:
            return transient_result(json.loads(value), depth + 1)
        except (ValueError, RecursionError):
            return False, None
    if isinstance(value, list) and len(value) == 1:
        return transient_result(value[0], depth + 1)
    if not isinstance(value, dict):
        return False, None
    if value.get("type") == "text" and set(value) <= {"type", "text", "annotations", "_meta"}:
        return transient_result(value.get("text"), depth + 1)
    if "content" in value and set(value) <= {"content", "isError", "structuredContent", "_meta"}:
        return transient_result(value["content"], depth + 1)
    if set(value) == {"result"}:
        return transient_result(value["result"], depth + 1)
    if not value.get("error") or not set(value) <= {
        "error",
        "status_code",
        "error_code",
        "retry_after_seconds",
    }:
        return False, None
    status = value.get("status_code")
    transient = (type(status) is int and status in TRANSIENT_STATUSES) or (
        value.get("error_code") == "tool_transport_unavailable"
    )
    delay = value.get("retry_after_seconds")
    return transient, retry_after(str(delay)) if delay is not None else None
