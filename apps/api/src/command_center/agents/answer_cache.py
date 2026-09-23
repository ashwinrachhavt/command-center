"""Fail-closed reuse policy for standalone transformations of immutable user text.

No workspace read, tool, specialist, connected account or mutable collection is eligible.
The first exchange and its immediate exact repeats are the only supported histories.
"""

import hashlib
import json
import re
from typing import Any

CACHE_REVISION = "text-transform-v1"
CONTEXT_REVISION = "bounded-summary-v1"
CACHE_TTL_SECONDS = 300
TRANSFORM = re.compile(r"^(?:Summarize|Explain) this text:\s*\S", re.IGNORECASE)
LIVE = re.compile(
    r"\b(?:now|latest|refresh|current|today|live|update|send|submit|create|delete|approve|execute)\b",
    re.IGNORECASE,
)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def configuration_digest(configuration: dict[str, Any]) -> str:
    return digest(
        {
            "profile": configuration.get("profile"),
            "revision": configuration.get("revision"),
            "harness": CONTEXT_REVISION,
            "cache": CACHE_REVISION,
        }
    )


def cacheable_request(prompt: str) -> bool:
    # Only outer whitespace normalization. Interior whitespace can change source meaning.
    return bool(TRANSFORM.match(prompt.strip())) and not LIVE.search(prompt)


def read_only_trace(checkpoint: dict[str, Any]) -> bool:
    # Absence of evidence is not evidence of zero effects. New/unknown tools miss.
    return (
        isinstance(checkpoint.get("steps"), int)
        and checkpoint["steps"] > 0
        and checkpoint.get("tool_count") == 0
        and checkpoint.get("tools") == []
    )
