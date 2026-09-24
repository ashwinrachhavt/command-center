"""Run-local immutable reads and lossless deduplication of effective model context."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage


def failed_tool_result(message: ToolMessage) -> bool:
    """Recognize API error envelopes even when MCP transports them as successful text."""

    def failed(value: Any, depth: int = 0) -> bool:
        if depth > 12:
            return True  # An opaque nested envelope is not safe to reuse as evidence.
        if isinstance(value, str):
            if value.startswith(("Denied:", "Tool unavailable")):
                return True
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                return False
            return failed(decoded, depth + 1)
        if isinstance(value, list):
            return any(failed(item, depth + 1) for item in value)
        if isinstance(value, dict):
            status = value.get("status_code")
            if (
                value.get("error")
                or value.get("isError") is True
                or value.get("success") is False
                or isinstance(status, int)
                and status >= 400
            ):
                return True
            # Decode transport envelopes only. A document's text/content/message
            # fields are source data, even when they contain JSON error examples.
            if value.get("type") == "text" and set(value) <= {
                "type",
                "text",
                "annotations",
                "_meta",
            }:
                return failed(value.get("text"), depth + 1)
            if "content" in value and set(value) <= {
                "content",
                "isError",
                "structuredContent",
                "_meta",
            }:
                return failed(value["content"], depth + 1)
            if set(value) == {"result"}:
                return failed(value["result"], depth + 1)
            if set(value) == {"message"} and isinstance(value["message"], str):
                return value["message"].startswith(("Denied:", "Tool unavailable"))
        return False

    return message.status == "error" or failed(message.content)


def immutable_read_key(call: Mapping[str, Any]) -> str | None:
    name, arguments = call["name"], call.get("args", {})
    if not isinstance(arguments, dict):
        return None
    if name == "catalog_execute":
        name, arguments = arguments.get("tool_name"), arguments.get("arguments", {})
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return None
    if name == "document_read" and not arguments.get("version_id"):
        return None
    if name not in {"catalog_search", "document_read"}:
        return None
    return json.dumps([call["name"], name, arguments], sort_keys=True, default=str)


def compact_read_results(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Retain the first full result and all tool-call protocol messages.

    This projection is never persisted. If compaction removed the first result,
    the next occurrence stays complete, so no dangling reference is introduced.
    """
    calls: dict[str, str | None] = {}
    seen: dict[tuple[str, str], str] = {}
    projected: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, AIMessage):
            calls.update(
                {
                    call["id"]: immutable_read_key(call)
                    for call in message.tool_calls
                    if call["id"] is not None
                }
            )
        if (
            isinstance(message, ToolMessage)
            and isinstance(message.content, str)
            and len(message.content) > 400
            and (key := calls.get(message.tool_call_id)) is not None
            and not failed_tool_result(message)
        ):
            identity = (key, message.content)
            if identity in seen:
                message = message.model_copy(
                    update={
                        "content": "Identical immutable read result is in tool call "
                        + seen[identity]
                        + ". Reuse that result and its exact references.",
                    }
                )
            else:
                seen[identity] = message.tool_call_id
        projected.append(message)
    return projected
