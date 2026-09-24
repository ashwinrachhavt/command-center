"""Bounded diagnostic copies; original messages remain in the application database."""

import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import SecretStr

from command_center.core.config import Settings

_PRIVATE_KEY = re.compile(
    r"password|secret|authorization|cookie|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"reasoning|thinking|signature|image_url|image_data|base64",
    re.I,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_DATA_URI = re.compile(r"data:[^,\s]+,[^\s\"']+", re.I)
_CREDENTIAL = re.compile(
    r"(?i)\b(?:bearer\s+|sk-[\w-]*|(?:password|api[_-]?key|access[_-]?token|secret)"
    r"\s*[=:]\s*[\"']?)[\w./+~=-]+"
)


def message_content(message: BaseMessage) -> dict[str, Any]:
    """Project public text/tool calls only, never provider reasoning or media blocks."""
    content = message.content
    if isinstance(content, list):
        content = [
            block if isinstance(block, str) else block.get("text", "")
            for block in content
            if isinstance(block, str) or block.get("type") in {"text", "output_text"}
        ]
    result: dict[str, Any] = {"role": message.type, "content": content}
    if isinstance(message, AIMessage) and message.tool_calls:
        result["tool_calls"] = message.tool_calls
    return result


class TraceContent:
    def __init__(self, enabled: bool = False, secrets: tuple[str, ...] = ()):
        self.enabled = enabled
        self.secrets = tuple(value for value in secrets if len(value) >= 8)

    @classmethod
    def from_settings(cls, settings: Settings, *, enabled: bool | None = None) -> "TraceContent":
        return cls(
            settings.langfuse_capture_content if enabled is None else enabled,
            tuple(
                value.get_secret_value()
                for name in type(settings).model_fields
                if isinstance(value := getattr(settings, name), SecretStr)
            ),
        )

    def capture(self, value: Any) -> dict[str, Any]:
        if not self.enabled:
            return {"capture": "disabled"}
        remaining = 12_000
        truncated = False

        def clean(item: Any, depth: int = 0) -> Any:
            nonlocal remaining, truncated
            if depth > 8 or remaining <= 0:
                truncated = True
                return "[truncated]"
            remaining -= 8  # Account for structural overhead and primitive values, too.
            if isinstance(item, BaseMessage):
                return clean(message_content(item), depth + 1)
            if isinstance(item, dict):
                # Structured reasoning can also occur inside tool responses.
                if item.get("type") in {"reasoning", "thinking", "redacted_thinking"}:
                    return "[omitted]"
                truncated |= len(item) > 40
                result = {}
                for key, child in list(item.items())[:40]:
                    if remaining <= 0:
                        truncated = True
                        break
                    remaining -= len(str(key)[:100])
                    result[str(key)[:100]] = (
                        "[redacted]" if _PRIVATE_KEY.search(str(key)) else clean(child, depth + 1)
                    )
                return result
            if isinstance(item, (list, tuple)):
                truncated |= len(item) > 40
                children = []
                for child in item[:40]:
                    if remaining <= 0:
                        truncated = True
                        break
                    children.append(clean(child, depth + 1))
                return children
            if isinstance(item, str):
                # Tool output often contains JSON encoded as a string.
                if item.startswith(("{", "[")):
                    import json

                    try:
                        return clean(json.loads(item), depth + 1)
                    except (ValueError, RecursionError):
                        pass
                for secret in self.secrets:
                    item = item.replace(secret, "[redacted]")
                item = _DATA_URI.sub("[media omitted]", item)
                item = _EMAIL.sub("[email]", _CREDENTIAL.sub("[redacted]", item))
                truncated |= len(item) > remaining
                text = item[: max(0, remaining)]
                remaining -= len(text)
                return text
            if item is None or isinstance(item, (bool, int, float)):
                return item
            return "[omitted]"

        content = clean(value)
        return {"capture": "redacted", "content": content, "truncated": truncated}
