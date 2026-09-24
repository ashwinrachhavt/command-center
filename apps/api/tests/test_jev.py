"""Synthetic router contracts, confidence gating and spend accounting; no paid calls."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from command_center.agents.routing import suggest_route
from command_center.agents.spending import ModelSpendingGate
from command_center.db.spending import SpendingDenied
from command_center.integrations.jev import (
    JEV_ENDPOINTS,
    JEV_MODEL,
    JEV_MODELS,
    JevResult,
    route_request,
    routing_payload,
)


def response(confidence=0.95, choice="documents"):
    return {
        "model": JEV_MODEL,
        "answers": {
            "route": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {
                    "documents": 0.96,
                    "gmail": 0.01,
                    "crm": 0.01,
                    "research": 0.01,
                    "general": 0.01,
                },
            }
        },
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }


@pytest.mark.parametrize("provider", ["typesafe", "gateway", "venice"])
def test_jev_http_contract_and_bounded_request(provider):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={**response(), "model": JEV_MODELS[provider]})

    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            return await route_request(
                http, "synthetic-key", routing_payload("Read my uploads", provider), provider
            )

    result = asyncio.run(call())
    assert result.hint and "document vault" in result.hint
    assert len(requests) == 1
    assert str(requests[0].url) == JEV_ENDPOINTS[provider]
    assert requests[0].headers["authorization"] == "Bearer synthetic-key"
    assert json.loads(requests[0].content)["questions"]["route"]["type"] == "choice"
    assert json.loads(requests[0].content)["model"] == JEV_MODELS[provider]
    with pytest.raises(ValueError):
        routing_payload("x" * 2001)


def test_uncertain_and_invalid_answers_never_supply_a_hint():
    assert JevResult.model_validate(response(0.5)).hint is None
    for change in (
        {"choice": "send_email"},
        {"confidence": float("nan")},
        {"probabilities": {"documents": 1.0}},
    ):
        data = response()
        data["answers"]["route"].update(change)
        with pytest.raises(ValidationError):
            JevResult.model_validate(data)


@pytest.mark.parametrize(
    "enabled,key,prompt", [(False, "key", "hello"), (True, "", "hello"), (True, "key", "x" * 2001)]
)
def test_disabled_or_oversized_routing_makes_no_call(settings, mocker, enabled, key, prompt):
    gate = mocker.create_autospec(ModelSpendingGate, instance=True)
    network = mocker.patch("command_center.agents.routing.route_request")
    configured = settings.model_copy(update={"jev_enabled": enabled, "jev_api_key": SecretStr(key)})
    assert asyncio.run(suggest_route(configured, prompt, gate)) == {"status": "skipped"}
    gate.reserve.assert_not_called()
    network.assert_not_called()


def test_routing_reserves_before_dispatch_and_settles_reported_usage(settings, mocker):
    gate = mocker.create_autospec(ModelSpendingGate, instance=True)
    configured = settings.model_copy(update={"jev_enabled": True, "jev_api_key": SecretStr("key")})

    async def dispatch(*args):
        gate.reserve.assert_awaited_once()
        assert "jordan@" not in json.dumps(args[2])
        return JevResult.model_validate(response())

    network = mocker.patch("command_center.agents.routing.route_request", side_effect=dispatch)
    result = asyncio.run(suggest_route(configured, "Read uploads from jordan@example.test", gate))
    assert result["status"] == "suggested"
    call_id = gate.reserve.call_args.args[0]
    gate.settle.assert_awaited_once_with(call_id, 300, 20)
    gate.unknown.assert_not_called()
    network.assert_awaited_once()


def test_outage_has_no_retry_and_reserves_unknown_cost(settings, mocker):
    gate = mocker.create_autospec(ModelSpendingGate, instance=True)
    configured = settings.model_copy(update={"jev_enabled": True, "jev_api_key": SecretStr("key")})
    network = mocker.patch(
        "command_center.agents.routing.route_request", side_effect=httpx.ReadTimeout("synthetic")
    )
    assert asyncio.run(suggest_route(configured, "Read uploads", gate))["status"] == "unavailable"
    network.assert_awaited_once()
    gate.unknown.assert_awaited_once()
    gate.settle.assert_not_called()


def test_spending_denial_skips_router(settings, mocker):
    gate = mocker.create_autospec(ModelSpendingGate, instance=True)
    gate.reserve.side_effect = SpendingDenied("spending_work_limit")
    network = mocker.patch("command_center.agents.routing.route_request")
    configured = settings.model_copy(update={"jev_enabled": True, "jev_api_key": SecretStr("key")})
    assert (
        asyncio.run(suggest_route(configured, "Read uploads", gate))["status"]
        == "budget_unavailable"
    )
    network.assert_not_called()


def test_gateway_uses_only_selected_key_and_accounts_for_reported_zero_cost(settings, mocker):
    gate = mocker.create_autospec(ModelSpendingGate, instance=True)
    trace = mocker.Mock()
    mocker.patch("command_center.agents.routing.current_trace").get.return_value = trace
    configured = settings.model_copy(
        update={
            "jev_enabled": True,
            "jev_provider": "gateway",
            "ai_gateway_api_key": SecretStr("gateway-secret"),
            "venice_api_key": SecretStr("venice-secret"),
        }
    )
    result = JevResult.model_validate(
        {
            **response(),
            "model": "typesafe-ai/jev",
            "provider_metadata": {"gateway": {"cost": "0"}},
        }
    )
    network = mocker.patch("command_center.agents.routing.route_request", return_value=result)
    output = asyncio.run(suggest_route(configured, "Read uploads venice-secret", gate))
    assert output["provider"] == "gateway"
    assert output["reported_cost_usd"] == 0
    assert gate.reserve.call_args.kwargs["provider"] == "gateway"
    args = network.call_args.args
    assert args[1] == "gateway-secret"
    assert args[3] == "gateway"
    assert "venice-secret" not in json.dumps(args[2])
    assert trace.model_end.call_args.kwargs["cost_details"] == {"total": 0.0}


@pytest.mark.parametrize("cost", [None, "NaN", "-0.5", "invalid", "Infinity"])
def test_invalid_gateway_cost_remains_unknown(cost):
    result = JevResult.model_validate(
        {
            **response(),
            "model": "typesafe-ai/jev",
            "provider_metadata": {"gateway": {"cost": cost}},
        }
    )
    assert result.gateway_cost is None


@pytest.mark.parametrize("kind", [{"name": "invoice"}, ["invoice"]])
def test_structured_json_requests_cannot_crash_optional_routing(settings, mocker, kind):
    gate = mocker.create_autospec(ModelSpendingGate, instance=True)
    configured = settings.model_copy(update={"jev_enabled": True, "jev_api_key": SecretStr("key")})
    network = mocker.patch(
        "command_center.agents.routing.route_request",
        return_value=JevResult.model_validate(response()),
    )
    request = {"type": kind, "request": "Read my uploaded invoice"}
    result = asyncio.run(suggest_route(configured, json.dumps(request), gate))
    assert result["status"] == "suggested"
    assert json.loads(network.call_args.args[2]["state"]["request"]) == request
    gate.settle.assert_awaited_once()
