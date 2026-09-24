"""Small public updates and bounded continuation context from saved tool receipts."""

import json
from collections import Counter
from typing import Any

from command_center.agents.trace_content import TraceContent


def completed_tools(checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in checkpoint.get("tools", [])
        if isinstance(item, dict) and item.get("state") == "output-available"
    ]


def operation_label(tool: dict[str, Any]) -> str:
    name = tool.get("summary") if tool.get("name") == "catalog_execute" else tool.get("name")
    return str(name or "operation").removeprefix("cc_").replace("_", " ")[:100]


def receipt_data(tool: dict[str, Any]) -> Any:
    return TraceContent(enabled=True).capture(tool.get("output"))["content"]


def record_references(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep primary record identifiers separately from source excerpts and lookup tails."""

    def identifiers(value: Any, path: str = "") -> dict[str, str]:
        result: dict[str, str] = {}
        if isinstance(value, dict):
            for key, child in value.items():
                name = f"{path}.{key}" if path else key
                if (key == "id" or key.endswith("_id")) and isinstance(child, str):
                    result[name[:100]] = child[:200]
                elif isinstance(child, (dict, list)):
                    result.update(identifiers(child, name))
        elif isinstance(value, list):
            for child in value[:10]:
                result.update(identifiers(child, path))
        return dict(list(result.items())[:8])

    records = []
    size = 0
    for tool in completed_tools({"tools": tools}):
        label = operation_label(tool)
        if not any(verb in label for verb in ("create", "save", "capture lead", "draft")):
            continue
        refs = identifiers(receipt_data(tool))
        if not refs:
            continue
        record = {"operation": label, "references": refs}
        size += len(json.dumps(record))
        if size > 4500:
            break
        records.append(record)
    return records


def source_excerpts(tools: list[dict[str, Any]]) -> list[dict[str, str]]:
    excerpts = {}

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for child in value[:5]:
                collect(child)
        elif isinstance(value, dict):
            url = value.get("url")
            if (
                isinstance(url, str)
                and len(url) <= 1500
                and url.startswith(("https://", "http://"))
            ):
                excerpts[url] = {
                    "url": url,
                    "title": str(value.get("title", ""))[:200],
                    "content": str(value.get("content", ""))[:500],
                }
            else:
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        collect(child)

    searches = [
        tool
        for tool in completed_tools({"tools": tools})
        if operation_label(tool) == "research search"
    ]
    for tool in searches[-2:]:
        collect(receipt_data(tool))
    return list(excerpts.values())[:3]


def saved_findings(tools: list[dict[str, Any]], *, limit: int = 6500) -> str:
    lines: list[str] = []

    def append(block: str) -> None:
        # Keep complete receipt/source blocks; never leave an unattributed clipped claim.
        if len("\n\n".join([*lines, block])) <= limit:
            lines.append(block)

    refs = record_references(tools)
    if refs:
        append("Returned save receipts:")
        for record in refs:
            details = ", ".join(f"{key}={value}" for key, value in record["references"].items())
            append(f"- {record['operation']}: {details}")
    excerpts = source_excerpts(tools)
    if excerpts:
        append("Collected source excerpts (unverified source claims):")
        for source in excerpts:
            excerpt = f"Source: {source['url']}\n{source['title']}: {source['content']}"
            append("> " + excerpt.replace("\n", "\n> "))
    return "\n\n".join(lines)


def progress_text(tools: list[dict[str, Any]]) -> str:
    completed = completed_tools({"tools": tools})
    failed = sum(item.get("state") == "output-error" for item in tools)
    if completed:
        text = (
            f"I've completed {len(completed)} operations. Latest: {operation_label(completed[-1])}."
        )
    else:
        text = "I'm still working on the current operation."
    if failed:
        text += f" {failed} operations need attention."
    findings = saved_findings(tools[-5:], limit=1200)
    if findings:
        text += "\n\n" + findings
    return text + " Progress is saved; I'm continuing with the remaining work."


def partial_reply(checkpoint: dict[str, Any], error_code: str | None) -> str:
    reasons = {
        "tool_limit": "the tool-call limit",
        "model_limit": "the model-call limit",
        "execution_timeout": "the time limit",
        "context_limit": "the context limit",
        "worker_interrupted": "an interruption",
        "cancelled": "cancellation",
    }
    reason = reasons.get(error_code or "", "an execution problem")
    completed = completed_tools(checkpoint)
    counts = Counter(operation_label(item) for item in completed)
    lines = [f"I stopped because of {reason}. The request is not complete."]
    if counts:
        lines.append(
            "Completed operations: " + "; ".join(f"{name} ({n})" for name, n in counts.items())
        )
    else:
        lines.append("No completed operations are recorded.")
    findings = saved_findings(checkpoint.get("tools", []))
    if findings:
        lines.append(findings)
    lines.append(
        'Saved results and checkpoints are retained. Say "continue" to work from them. '
        "I will check saved records before retrying an interrupted action."
    )
    return "\n\n".join(lines)


def continuation_context(checkpoint: dict[str, Any]) -> str:
    """Reuse recent receipts, without promoting them to reviewed long-term memory."""
    tools = checkpoint.get("tools", [])
    captures = [item for item in tools if operation_label(item) == "capture research source"]
    chosen = {str(item.get("id")): item for item in [*tools[-2:], *captures[-2:]]}
    receipts = []
    for item in chosen.values():
        content = receipt_data(item)
        serialized = json.dumps(content, ensure_ascii=False, default=str)
        receipts.append(
            {
                "operation": operation_label(item),
                "state": item.get("state"),
                "receipt": serialized[:700],
                "truncated": len(serialized) > 700,
            }
        )
    payload = {"records": record_references(tools), "receipts": receipts}
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    while len(serialized) > 9000 and receipts:
        receipts.pop()
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    return serialized
