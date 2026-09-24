"""Optional one-shot routing with the same spending ledger as other model calls."""

import asyncio
import json
from typing import Any
from uuid import uuid4

import httpx
from pydantic import SecretStr

from command_center.agents.spending import ModelSpendingGate
from command_center.agents.telemetry import current_trace
from command_center.agents.trace_content import TraceContent
from command_center.core.config import Settings
from command_center.db.spending import SpendingDenied
from command_center.integrations.jev import JEV_MODELS, route_request, routing_payload


def jev_secret(settings: Settings) -> SecretStr:
    return {
        "typesafe": settings.jev_api_key,
        "gateway": settings.ai_gateway_api_key,
        "venice": settings.venice_api_key,
    }[settings.jev_provider]


async def suggest_route(
    settings: Settings, request: str, spending: ModelSpendingGate
) -> dict[str, Any]:
    # Skip rather than truncate a long request and route on incomplete instructions.
    if (
        not settings.jev_enabled
        or not jev_secret(settings).get_secret_value()
        or len(request) > 2000
    ):
        return {"status": "skipped"}
    safe = TraceContent.from_settings(settings, enabled=True).capture(request)["content"]
    if not isinstance(safe, str):
        safe = json.dumps(safe)
    if len(safe) > 2000:
        return {"status": "skipped"}
    provider, model = settings.jev_provider, JEV_MODELS[settings.jev_provider]
    payload = routing_payload(safe, provider)
    call_id = uuid4()
    try:
        await spending.reserve(
            call_id,
            role="router",
            provider=provider,
            model=model,
            input_tokens=len(json.dumps(payload).encode()) + 4096,
            output_tokens=4096,
        )
    except SpendingDenied:
        return {"status": "budget_unavailable"}
    trace = current_trace.get()
    if trace:
        trace.model_start(call_id, "router", provider, model, len(safe), 0, 0, messages=payload)
    try:
        async with asyncio.timeout(3), httpx.AsyncClient() as http:
            result = await route_request(
                http, jev_secret(settings).get_secret_value(), payload, provider
            )
    except (httpx.HTTPError, ValueError, TimeoutError):
        await spending.unknown(call_id, "spending_usage_unknown")
        if trace:
            trace.model_end(call_id, {}, error=True)
        return {"status": "unavailable"}
    usage = result.usage.model_dump()
    await spending.settle(call_id, usage["input_tokens"], usage["output_tokens"])
    if trace:
        trace.model_end(
            call_id,
            usage,
            output={key: value.model_dump() for key, value in result.answers.items()},
            cost_details=(
                {"total": result.gateway_cost}
                if result.gateway_cost is not None
                else {"input": usage["input_tokens"] * 0.042 / 1_000_000, "output": 0}
            ),
        )
    answer = result.answers.get("route")
    return {
        "status": "suggested" if result.hint else "uncertain",
        "model": result.model,
        "provider": provider,
        "route": answer.choice if answer else "general",
        "confidence": answer.confidence if answer else None,
        "hint": result.hint,
        "usage": usage,
        "reported_cost_usd": result.gateway_cost,
    }
