"""Bounded connected-context reads preserve ownership, billing and provenance."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.core.capabilities import issue_run_token
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.conversations import AgentSession
from command_center.db.models import Actor, AuditEvent, Task
from command_center.db.reviewed_actions import (
    ConnectedRequest,
    ExternalAccount,
    ProviderObservation,
)
from command_center.db.spending import SpendingDenied
from command_center.integrations.composio_actions import (
    CONNECTED_ACCOUNTS_LIST_OPERATION,
    IDENTITY_TOOLS,
    AccountMetadata,
    ComposioActionClient,
    ConnectedContextResult,
    VerifiedIdentity,
)
from command_center.main import create_app


class Reservation:
    def __init__(self) -> None:
        self.settled = False

    def settle(self, provider_billed_micros=None) -> None:
        self.settled = True

    def unknown(self, reason: str) -> None:
        raise AssertionError(reason)


@pytest.fixture
def context_client(settings, engine, mocker):
    owner_id, stranger_id = uuid4(), uuid4()
    identities = {
        "googlecalendar": {
            "account_id": "calendar-user",
            "email": "calendar@example.test",
            "primary_calendar_id": "primary",
            "time_zone": "UTC",
        },
        "linear": {"id": "linear-user", "organization_id": "linear-org"},
        "notion": {"id": "notion-user", "name": "Synthetic Notion", "type": "person"},
    }
    account_ids = {toolkit: uuid4() for toolkit in identities}
    foreign_account_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                Actor(id=owner_id, kind="human", display_name="Synthetic context owner"),
                Actor(id=stranger_id, kind="human", display_name="Other context owner"),
                *[
                    ExternalAccount(
                        id=account_id,
                        owner_id=owner_id,
                        toolkit=toolkit,
                        composio_connected_account_id=f"ca_{toolkit}",
                        composio_auth_config_id=f"ac_{toolkit}",
                        display_name=f"Synthetic {toolkit}",
                        provider_identity=identities[toolkit],
                        connection_status="ACTIVE",
                        identity_verified_at=datetime(2026, 9, 21, tzinfo=UTC),
                    )
                    for toolkit, account_id in account_ids.items()
                ],
                ExternalAccount(
                    id=foreign_account_id,
                    owner_id=stranger_id,
                    toolkit="linear",
                    composio_connected_account_id="ca_foreign_linear",
                    composio_auth_config_id="ac_linear",
                    display_name="Foreign Linear",
                    provider_identity={"id": "foreign-user"},
                    connection_status="ACTIVE",
                    identity_verified_at=datetime(2026, 9, 21, tzinfo=UTC),
                ),
            ]
        )

    provider_calls: list[str] = []
    charges: list[tuple[str, UUID, Reservation]] = []
    budget_scopes: list[tuple[UUID, UUID | None, UUID | None, UUID]] = []

    def reserve(slug: str, operation_id: UUID) -> Reservation:
        reservation = Reservation()
        charges.append((slug, operation_id, reservation))
        return reservation

    def budget(owner, task, opportunity, *, request_scope_id, **kwargs):
        budget_scopes.append((owner, task, opportunity, request_scope_id))
        return reserve

    def account_metadata(self, **kwargs):
        assert engine.pool.checkedout() == 0
        provider_calls.append("account")
        reserve_handle = kwargs["reserve_budget"](
            CONNECTED_ACCOUNTS_LIST_OPERATION, kwargs["operation_id"]
        )
        reserve_handle.settle()
        toolkit = kwargs["expected_toolkit"]
        return AccountMetadata(
            connected_account_id=kwargs["connected_account_id"],
            toolkit=toolkit,
            auth_config_id=kwargs["expected_auth_config_id"],
            status="ACTIVE",
            is_disabled=False,
            provider_updated_at=None,
            provider_identity=identities[toolkit],
        )

    def verify_identity(self, account, **kwargs):
        assert engine.pool.checkedout() == 0
        provider_calls.append("identity")
        kwargs["reserve_budget"](
            IDENTITY_TOOLS[account.toolkit], kwargs["charge"].operation_id
        ).settle()
        return VerifiedIdentity(f"Synthetic {account.toolkit}", identities[account.toolkit])

    def read_context(self, query, *, account, **kwargs):
        assert engine.pool.checkedout() == 0
        provider_calls.append("context")
        slug = {
            "calendar_events": "GOOGLECALENDAR_EVENTS_LIST",
            "calendar_event": "GOOGLECALENDAR_EVENTS_GET",
            "linear_issue": "LINEAR_GET_LINEAR_ISSUE",
            "notion_page": "NOTION_RETRIEVE_PAGE",
        }[query.kind]
        kwargs["reserve_budget"](slug, kwargs["charge"].operation_id).settle()
        return ConnectedContextResult(
            context={"issue": {"id": "issue-synthetic", "title": "Readable context"}},
            external_revision="revision-synthetic",
            provider_log_ids=["log-synthetic"],
            truncated=False,
            content_sha256=None,
        )

    mocker.patch.object(ComposioActionClient, "account_metadata", account_metadata)
    mocker.patch.object(ComposioActionClient, "verify_identity", verify_identity)
    mocker.patch.object(ComposioActionClient, "read_context", read_context)
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner_id, "synthetic-context")
    with TestClient(app) as client:
        client.app.state.composio_actions = object.__new__(ComposioActionClient)
        client.app.state.reviewed_action_budget = budget
        yield SimpleNamespace(
            http=client,
            owner_id=owner_id,
            account_ids=account_ids,
            foreign_account_id=foreign_account_id,
            provider_calls=provider_calls,
            charges=charges,
            budget_scopes=budget_scopes,
        )


def post(context_client, body, *, key=None):
    return context_client.http.post(
        "/api/v1/integrations/composio/context",
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def test_context_read_is_bounded_owned_audited_and_idempotent(context_client, engine):
    key = uuid4()
    body = {
        "account_id": str(context_client.account_ids["linear"]),
        "query": {"kind": "linear_issue", "issue_id": "issue-synthetic"},
    }
    first = post(context_client, body, key=key)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["context"]["issue"]["title"] == "Readable context"
    assert result["external_revision"] == "revision-synthetic"
    assert result["provider_log_ids"] == ["log-synthetic"]
    assert post(context_client, body, key=key).json() == result
    assert context_client.provider_calls == ["account", "identity", "context"]
    assert [item[0] for item in context_client.charges] == [
        CONNECTED_ACCOUNTS_LIST_OPERATION,
        "LINEAR_WHO_AM_I",
        "LINEAR_GET_LINEAR_ISSUE",
    ]
    assert all(item[2].settled for item in context_client.charges)
    assert context_client.budget_scopes[0][0] == context_client.owner_id
    assert context_client.budget_scopes[0][1:3] == (None, None)
    with Session(engine) as db:
        observation = db.get(ProviderObservation, UUID(result["observation_id"]))
        assert observation is not None
        assert observation.owner_id == context_client.owner_id
        assert observation.account_id == context_client.account_ids["linear"]
        assert observation.kind == "linear_issue"
        assert observation.external_revision == "revision-synthetic"
        assert observation.result["provider_log_ids"] == ["log-synthetic"]
        assert db.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_id == observation.id,
                AuditEvent.action == "connected_context.observed",
            )
        )
    conflict = post(
        context_client,
        body | {"query": {"kind": "linear_issue", "issue_id": "different"}},
        key=key,
    )
    assert conflict.status_code == 409


def test_context_rejects_foreign_wrong_toolkit_and_invalid_calendar_queries(context_client):
    foreign = post(
        context_client,
        {
            "account_id": str(context_client.foreign_account_id),
            "query": {"kind": "linear_issue", "issue_id": "issue-synthetic"},
        },
    )
    assert foreign.status_code == 404
    wrong_toolkit = post(
        context_client,
        {
            "account_id": str(context_client.account_ids["linear"]),
            "query": {"kind": "notion_page", "page_id": "page-synthetic"},
        },
    )
    assert wrong_toolkit.status_code == 422
    now = datetime.now(UTC)
    invalid = post(
        context_client,
        {
            "account_id": str(context_client.account_ids["googlecalendar"]),
            "query": {
                "kind": "calendar_events",
                "time_min": now.isoformat(),
                "time_max": (now + timedelta(days=32)).isoformat(),
            },
        },
    )
    assert invalid.status_code == 422
    naive = post(
        context_client,
        {
            "account_id": str(context_client.account_ids["googlecalendar"]),
            "query": {
                "kind": "calendar_events",
                "time_min": "2026-10-01T00:00:00",
                "time_max": "2026-10-02T00:00:00",
            },
        },
    )
    assert naive.status_code == 422
    assert context_client.provider_calls == []


@pytest.mark.parametrize("replay_state", ["failed", "running", "outcome_unknown"])
def test_context_budget_denial_is_durable_and_never_observed(context_client, engine, replay_state):
    def denied_budget(*args, **kwargs):
        def reserve(slug, operation_id):
            raise SpendingDenied("spending_work_limit_exceeded")

        return reserve

    context_client.http.app.state.reviewed_action_budget = denied_budget
    body = {
        "account_id": str(context_client.account_ids["linear"]),
        "query": {"kind": "linear_issue", "issue_id": "issue-synthetic"},
    }
    key = uuid4()
    response = post(context_client, body, key=key)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "spending_work_limit_exceeded"
    calls = list(context_client.provider_calls)
    with Session(engine) as db, db.begin():
        claim = db.scalar(
            select(ConnectedRequest)
            .where(ConnectedRequest.actor_id == context_client.owner_id)
            .with_for_update()
        )
        assert claim is not None and claim.state == "failed"
        assert (
            db.scalar(
                select(ProviderObservation).where(
                    ProviderObservation.owner_id == context_client.owner_id
                )
            )
            is None
        )
        claim.state = replay_state
    replay = post(context_client, body, key=key)
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == f"connected_request_{replay_state}"
    assert context_client.provider_calls == calls


def test_agent_context_derives_task_scope_and_fences_terminal_run(context_client, engine):
    profile = AgentProfile(
        name="Synthetic context reader",
        description="Read bounded connected context",
        model="synthetic",
        instructions="Use only the connected context tool.",
        tools=["connected_context"],
    )
    with Session(engine, expire_on_commit=False) as db, db.begin():
        task = Task(owner_id=context_client.owner_id, title="Scoped context task")
        db.add(task)
        db.flush()
        conversation = AgentSession.open(
            db,
            record_id=uuid4(),
            owner_id=context_client.owner_id,
            task_id=task.id,
            opportunity_id=None,
            request_id=uuid4(),
        )
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=context_client.owner_id,
            prompt="Read the synthetic issue",
            profile="synthetic-context",
            configuration=profile.model_dump(),
            revision="synthetic",
            request_id=uuid4(),
            session_id=conversation.id,
        )
        db.flush()
        assert AgentRun.claim(db, run.id) is not None
        db.flush()
        run_id, lease_id, task_id = run.id, run.lease_id, task.id
    assert lease_id is not None
    context_client.http.app.dependency_overrides.pop(authenticate)
    headers = {
        "Authorization": "Bearer "
        + issue_run_token(context_client.http.app.state.settings, run_id, lease_id),
        "Idempotency-Key": str(uuid4()),
    }
    response = context_client.http.post(
        "/api/v1/integrations/composio/context",
        json={
            "account_id": str(context_client.account_ids["linear"]),
            "query": {"kind": "linear_issue", "issue_id": "issue-synthetic"},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    with Session(engine) as db, db.begin():
        observation = db.get(ProviderObservation, UUID(response.json()["observation_id"]))
        assert observation is not None and observation.task_id == task_id
        current = db.get(AgentRun, run_id)
        assert current is not None
        current.finish("cancelled")
    denied = context_client.http.post(
        "/api/v1/integrations/composio/context",
        json={
            "account_id": str(context_client.account_ids["linear"]),
            "query": {"kind": "linear_issue", "issue_id": "another-issue"},
        },
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code == 401
