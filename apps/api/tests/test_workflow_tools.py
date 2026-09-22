"""Network-free workflow tool, queue and spending-wiring regressions."""

import json
from types import SimpleNamespace
from uuid import uuid4, uuid5

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from command_center.agents.config import AgentProfile
from command_center.agents.tools import ToolRegistry


def workflow_profile(**changes) -> AgentProfile:
    values = {
        "name": "Synthetic workflows",
        "description": "Network-free workflow contract",
        "model": "gpt-5-mini",
        "instructions": "Use reviewed workflows only.",
        "tools": [],
    }
    values.update(changes)
    return AgentProfile(**values)


def schemas(registry: ToolRegistry) -> dict[str, dict]:
    return {row["function"]["name"]: row["function"]["parameters"] for row in registry.schemas}


def test_raw_connected_provider_grants_fail_before_tool_discovery() -> None:
    with pytest.raises(ValidationError, match="raw Composio grants cannot bypass"):
        workflow_profile(
            composio_tools=[
                {
                    "toolkit": "gmail",
                    "slug": "GMAIL_FETCH_EMAILS",
                    "version": "20260921_1",
                    "read_only": True,
                }
            ]
        )


def test_workflow_tool_schemas_keep_account_and_scope_at_typed_boundaries(settings) -> None:
    registry = ToolRegistry(
        settings,
        workflow_profile(
            tools=[
                "connected_accounts",
                "connected_context",
                "gmail_search",
                "propose_connected_action",
                "reviewed_action",
            ]
        ),
        uuid4(),
        uuid4(),
        "synthetic-capability",
    )
    discovered = schemas(registry)
    assert set(discovered) == {
        "connected_accounts",
        "connected_context",
        "gmail_search",
        "propose_connected_action",
        "reviewed_action",
    }
    assert discovered["connected_accounts"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    search = discovered["gmail_search"]
    assert search["required"] == ["query"]
    assert "account_id" not in search["properties"]
    context = discovered["connected_context"]
    assert set(context["required"]) == {"account_id", "query"}
    assert set(context["properties"]) == {"account_id", "query"}
    assert context["additionalProperties"] is False
    assert set(context["properties"]["query"]["discriminator"]["mapping"]) == {
        "calendar_events",
        "calendar_event",
        "linear_issue",
        "notion_page",
    }
    proposal = discovered["propose_connected_action"]
    assert {"account_id", "payload", "reason"}.issubset(proposal["required"])
    assert {"task_id", "opportunity_id"}.issubset(proposal["properties"])
    assert proposal["additionalProperties"] is False


def test_connected_context_tool_pins_call_identity_and_rejects_extra_authority(
    settings, mocker
) -> None:
    requests = []
    observation_id = str(uuid4())

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"observation_id": observation_id})

    http_client = httpx.Client
    mocker.patch(
        "command_center.agents.tools.httpx.Client",
        side_effect=lambda **kwargs: http_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    run_id = uuid4()
    registry = ToolRegistry(
        settings,
        workflow_profile(tools=["connected_context"]),
        uuid4(),
        run_id,
        "synthetic-capability",
    )
    arguments = {
        "account_id": str(uuid4()),
        "query": {"kind": "notion_page", "page_id": str(uuid4())},
    }
    for call_id in ("context-1", "context-1", "context-2"):
        result = json.loads(registry.execute("connected_context", arguments, call_id))
        assert result["observation_id"] == observation_id
    assert len(requests) == 3
    for request in requests:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/integrations/composio/context"
        assert json.loads(request.content) == arguments
        assert request.headers["authorization"] == "Bearer synthetic-capability"
    assert requests[0].headers["idempotency-key"] == str(uuid5(run_id, "context-1"))
    assert requests[1].headers["idempotency-key"] == requests[0].headers["idempotency-key"]
    assert requests[2].headers["idempotency-key"] != requests[0].headers["idempotency-key"]

    for unexpected in ("owner_id", "task_id", "agent_run_id"):
        result = registry.execute(
            "connected_context", {**arguments, unexpected: str(uuid4())}, "invalid"
        )
        assert "invalid" in result
    assert "Denied" in registry.execute("propose_connected_action", arguments, "write")
    assert len(requests) == 3


@pytest.mark.parametrize(
    ("task_id", "opportunity_id", "request_scope"),
    [(uuid4(), None, None), (None, uuid4(), None), (None, None, "action")],
)
def test_reviewed_action_queue_binds_one_durable_budget_scope(
    mocker, task_id, opportunity_id, request_scope
) -> None:
    from command_center.agents import queue

    action_id = uuid4()
    action = SimpleNamespace(
        id=action_id,
        owner_id=uuid4(),
        task_id=task_id,
        opportunity_id=opportunity_id,
    )
    engine = mocker.MagicMock()
    mocker.patch.object(queue, "create_database_engine", return_value=engine)
    db = mocker.MagicMock()
    db.get.return_value = action
    session = mocker.patch.object(queue, "Session")
    session.return_value.__enter__.return_value = db
    reserve = object()
    reserver = mocker.patch.object(queue, "connected_tool_reserver", return_value=reserve)
    perform = mocker.patch.object(queue, "perform_reviewed_action", return_value=True)

    assert queue.execute_reviewed_action.run(str(action_id)) is True
    reserver.assert_called_once_with(
        engine,
        owner_id=action.owner_id,
        task_id=task_id,
        opportunity_id=opportunity_id,
        request_scope_id=action_id if request_scope == "action" else None,
    )
    perform.assert_called_once_with(
        engine,
        queue.settings,
        str(action_id),
        reserve_budget=reserve,
    )
    engine.dispose.assert_called_once_with()


def test_dispatch_recovers_expired_spend_and_routes_paid_work(mocker) -> None:
    from command_center.agents import queue

    assert queue.celery.conf.task_acks_late is True
    assert queue.celery.conf.task_reject_on_worker_lost is True
    assert queue.celery.conf.worker_prefetch_multiplier == 1
    assert queue.celery.conf.task_routes["command_center.execute_run"]["queue"] == "agents"
    assert (
        queue.celery.conf.task_routes["command_center.execute_reviewed_action"]["queue"]
        == "actions"
    )

    engine = mocker.MagicMock()
    mocker.patch.object(queue, "create_database_engine", return_value=engine)
    db = mocker.MagicMock()
    db.scalars.return_value = []
    session = mocker.patch.object(queue, "Session")
    session.return_value.__enter__.return_value = db
    spending_expiry = mocker.patch.object(queue.SpendingReservation, "expire_stale")
    for model in (
        queue.AgentRun,
        queue.DocumentImport,
        queue.ReviewedAction,
        queue.ResearchExecution,
        queue.PdfExport,
    ):
        mocker.patch.object(model, "expire_stale")

    assert queue.dispatch.run() == 0
    spending_expiry.assert_called_once_with(db)
    engine.dispose.assert_called_once_with()


def test_main_lifespan_forwards_owned_scope_to_spending_factory(settings, mocker) -> None:
    from command_center import main
    from command_center.core.identity import Identity, authenticate
    from command_center.db.reviewed_actions import TOOL_FOR_KIND
    from command_center.db.spending import SpendingDenied
    from command_center.integrations.composio_actions import CONNECTED_OPERATION_LABELS

    engine = mocker.MagicMock()
    mocker.patch.object(main, "create_database_engine", return_value=engine)
    reserve = object()
    connected = mocker.patch.object(main, "connected_tool_reserver", return_value=reserve)
    app = main.create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(uuid4(), "synthetic")

    @app.get("/synthetic-spending-denial")
    def synthetic_denial() -> None:
        raise SpendingDenied("spending_work_limit")

    owner_id, task_id = uuid4(), uuid4()
    with TestClient(app) as client:
        factory = app.state.reviewed_action_budget
        assert factory(owner_id, task_id, None, request_scope_id=None) is reserve
        connected.assert_called_once_with(
            engine,
            owner_id=owner_id,
            task_id=task_id,
            opportunity_id=None,
            request_scope_id=None,
        )
        connected.reset_mock()
        request_scope_id = uuid4()
        assert factory(owner_id, None, None, request_scope_id=request_scope_id) is reserve
        connected.assert_called_once_with(
            engine,
            owner_id=owner_id,
            task_id=None,
            opportunity_id=None,
            request_scope_id=request_scope_id,
        )
        connected.reset_mock()
        run_id, lease_id = uuid4(), uuid4()
        assert (
            factory(
                owner_id,
                task_id,
                None,
                request_scope_id=uuid4(),
                agent_run_id=run_id,
                agent_lease_id=lease_id,
            )
            is reserve
        )
        connected.assert_called_once_with(
            engine,
            owner_id=owner_id,
            run_id=run_id,
            lease_id=lease_id,
        )
        denied = client.get("/synthetic-spending-denial")
        assert denied.status_code == 409
        assert denied.json() == {
            "detail": {
                "code": "spending_work_limit",
                "message": "This operation would exceed the configured work limit.",
            }
        }
        catalog = client.get("/api/v1/spending/catalog")
        assert catalog.status_code == 200
        payload = catalog.json()
        models = [(row["provider"], row["model"]) for row in payload["models"]]
        assert models == sorted(set(models))
        assert models
        tool_slugs = {row["slug"] for row in payload["tools"]}
        assert tool_slugs == set(CONNECTED_OPERATION_LABELS) | set(TOOL_FOR_KIND.values())
        assert all(set(row) == {"slug", "label"} for row in payload["tools"])
    engine.dispose.assert_called_once_with()
