"""Compact saved evidence for agent tool responses without changing stored sources."""

from typing import Any
from uuid import UUID

LEAD_EVIDENCE_PREVIEW_CHARS = 400


def project_lead_evidence(result: Any, *, can_read_versions: bool) -> Any:
    """Shorten saved source excerpts only when exact full-text reads are available."""
    if not can_read_versions or not isinstance(result, dict) or "error" in result:
        return result
    items = result.get("items")
    if not isinstance(items, list) or not items:
        return result
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("excerpt"), str):
            return result
        if not isinstance(item.get("version_id"), str):
            return result
        try:
            if str(UUID(item["version_id"])) != item["version_id"].lower():
                return result
        except ValueError:
            return result
    if not any(len(item["excerpt"]) > LEAD_EVIDENCE_PREVIEW_CHARS for item in items):
        return result

    projected = dict(result)
    projected["items"] = []
    for item in items:
        preview = dict(item)
        excerpt = item["excerpt"]
        if len(excerpt) > LEAD_EVIDENCE_PREVIEW_CHARS:
            preview["excerpt"] = excerpt[:LEAD_EVIDENCE_PREVIEW_CHARS]
            preview["excerpt_truncated"] = True
        projected["items"].append(preview)
    projected["source_text_access"] = (
        "Each excerpt is a saved-source preview. Call document_read with the item's "
        "version_id and offset 0 for exact text; use next_offset for later pages."
    )
    if isinstance(result.get("offset"), int) and isinstance(result.get("total"), int):
        end = result["offset"] + len(items)
        projected["next_offset"] = end if end < result["total"] else None
    return projected
