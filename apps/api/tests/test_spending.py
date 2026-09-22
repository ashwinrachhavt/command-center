"""Atomic spending controls at model and connected-provider boundaries."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.models import Actor, Task
from command_center.db.spending import (
    SpendingDenied,
    SpendingPeriod,
    SpendingPolicy,
    SpendingRateCard,
    SpendingReservation,
    SpendingWorkBudget,
)
from command_center.main import create_app


def rates(*, tool_cost: int = 25) -> dict[str, object]:
    return {
        "models": [
            {
                "provider": "openai",
                "model": "gpt-5-mini",
                "input_per_million_micros": 0,
                "output_per_million_micros": 0,
                "fixed_micros": 100,
            }
        ],
        "tools": [{"slug": "gmail_search", "fixed_micros": tool_cost}],
    }


def configure(
    db: Session,
    owner_id: UUID,
    *,
    monthly_limit: int = 1_000,
    work_limit: int = 1_000,
) -> SpendingRateCard:
    card = SpendingRateCard.create(
        db,
        owner_id=owner_id,
        name="Synthetic rates",
        source_label="Synthetic test fixture",
        rates=rates(),
        request_id=uuid4(),
    )
    SpendingPolicy.configure(
        db,
        owner_id=owner_id,
        rate_card_id=card.id,
        monthly_limit_micros=monthly_limit,
        default_work_limit_micros=work_limit,
        active=True,
        request_id=uuid4(),
        expected_version=None,
    )
    db.flush()
    return card


def queued_run(db: Session, owner_id: UUID) -> AgentRun:
    profile = AgentProfile(
        name="Synthetic lead",
        description="Synthetic",
        provider="openai",
        model="gpt-5-mini",
        instructions="Reply briefly.",
    )
    return AgentRun.enqueue(
        db,
        record_id=uuid4(),
        owner_id=owner_id,
        prompt="Synthetic bounded request",
        profile="lead",
        configuration=profile.model_dump(mode="json"),
        revision="synthetic",
        request_id=uuid4(),
    )


def committed_running_run(
    engine: Engine, *, monthly_limit: int = 1_000, work_limit: int = 1_000
) -> tuple[UUID, UUID, UUID]:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Synthetic spender")
        db.add(owner)
        db.flush()
        configure(
            db,
            owner.id,
            monthly_limit=monthly_limit,
            work_limit=work_limit,
        )
        run = queued_run(db, owner.id)
        claimed = AgentRun.claim(db, run.id)
        assert claimed is not None and claimed.lease_id is not None
        return owner.id, claimed.id, claimed.lease_id


def test_rate_cards_are_canonical_immutable_and_require_exact_resources(session: Session) -> None:
    owner = Actor(id=uuid4(), kind="human", display_name="Rate owner")
    session.add(owner)
    session.flush()
    first = SpendingRateCard.create(
        session,
        owner_id=owner.id,
        name="First",
        source_label="Synthetic",
        rates=rates(),
        request_id=uuid4(),
    )
    replay = SpendingRateCard.create(
        session,
        owner_id=owner.id,
        name="Same values",
        source_label="Synthetic",
        rates={"tools": list(reversed(rates()["tools"])), "models": rates()["models"]},
        request_id=uuid4(),
    )
    assert replay.id == first.id
    assert first.tool_rate("gmail_search") == 25
    with pytest.raises(SpendingDenied, match="cost_bound_unavailable"):
        first.tool_rate("unpriced_tool")


def test_concurrent_model_reservations_share_one_atomic_work_cap(engine: Engine) -> None:
    owner_id, run_id, lease_id = committed_running_run(engine, monthly_limit=100, work_limit=100)

    def reserve(operation_id: UUID) -> str:
        try:
            with Session(engine) as db, db.begin():
                row = SpendingReservation.reserve_model(
                    db,
                    run_id=run_id,
                    lease_id=lease_id,
                    callback_id=operation_id,
                    role="lead",
                    provider="openai",
                    model="gpt-5-mini",
                    input_token_bound=10,
                    output_token_bound=10,
                )
                db.flush([row])
            return "reserved"
        except SpendingDenied as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [uuid4(), uuid4()]))
    assert sorted(results) == ["reserved", "spending_monthly_limit"]
    with Session(engine) as db:
        period = db.scalar(select(SpendingPeriod).where(SpendingPeriod.owner_id == owner_id))
        work = db.scalar(
            select(SpendingWorkBudget).where(SpendingWorkBudget.standalone_run_id == run_id)
        )
        assert period is not None and period.reserved_micros == 100
        assert work is not None and work.reserved_micros == 100


def test_unknown_model_usage_can_settle_late_without_releasing_the_bound(engine: Engine) -> None:
    _, run_id, lease_id = committed_running_run(engine)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        row = SpendingReservation.reserve_model(
            db,
            run_id=run_id,
            lease_id=lease_id,
            callback_id=uuid4(),
            role="lead",
            provider="openai",
            model="gpt-5-mini",
            input_token_bound=100,
            output_token_bound=100,
        )
        db.flush([row])
        reservation_id = row.id
    with Session(engine) as db, db.begin():
        SpendingReservation.mark_unknown(
            db,
            reservation_id=reservation_id,
            lease_id=lease_id,
            reason="provider_timeout",
        )
    with Session(engine) as db, db.begin():
        settled = SpendingReservation.settle_model(
            db,
            reservation_id=reservation_id,
            lease_id=lease_id,
            input_tokens=12,
            output_tokens=8,
            provider_billed_micros=120,
        )
        assert settled.state == "settled"
        assert settled.accounted_micros == 120
        period = db.get(SpendingPeriod, settled.period_id)
        assert period is not None
        assert (period.reserved_micros, period.unknown_micros) == (0, 0)
        assert period.accounted_micros == 120


def test_connected_operations_use_owned_scope_and_idempotent_operation_id(engine: Engine) -> None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Tool spender")
        task = Task(owner_id=owner.id, title="Synthetic provider read")
        db.add_all([owner, task])
        db.flush()
        configure(db, owner.id)
        owner_id, task_id = owner.id, task.id
    operation_id = uuid4()
    with Session(engine, expire_on_commit=False) as db, db.begin():
        first = SpendingReservation.reserve_connected_tool(
            db,
            owner_id=owner_id,
            task_id=task_id,
            operation_id=operation_id,
            slug="gmail_search",
        )
        db.flush([first])
        reservation_id = first.id
    with Session(engine) as db, db.begin():
        replay = SpendingReservation.reserve_connected_tool(
            db,
            owner_id=owner_id,
            task_id=task_id,
            operation_id=operation_id,
            slug="gmail_search",
        )
        assert replay.id == reservation_id
        SpendingReservation.settle_connected_tool(db, reservation_id=replay.id)
    with Session(engine) as db:
        row = db.get(SpendingReservation, reservation_id)
        assert row is not None
        assert row.state == "settled"
        assert row.accounted_micros == 25
        assert row.input_token_bound == row.output_token_bound == 0

    request_scope_id = uuid4()
    with Session(engine, expire_on_commit=False) as db, db.begin():
        request_scoped = SpendingReservation.reserve_connected_tool(
            db,
            owner_id=owner_id,
            request_scope_id=request_scope_id,
            operation_id=uuid4(),
            slug="gmail_search",
        )
        db.flush([request_scoped])
        request_budget = db.get(SpendingWorkBudget, request_scoped.work_budget_id)
        assert request_budget is not None
        assert request_budget.request_scope_id == request_scope_id
        assert request_budget.task_id is None
        assert request_budget.opportunity_id is None


def test_spending_configuration_http_is_owned_replayable_and_readable(settings, engine) -> None:
    owner_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner_id, kind="human", display_name="Settings owner"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner_id, "synthetic")
    with TestClient(app) as client:
        before = client.get("/api/v1/spending")
        assert before.status_code == 200
        assert before.json()["readiness"]["code"] == "spending_policy_unconfigured"
        key = str(uuid4())
        payload = {
            "name": "Synthetic rates",
            "source_label": "Synthetic fixture",
            **rates(),
        }
        created = client.post(
            "/api/v1/spending/rate-cards",
            headers={"Idempotency-Key": key},
            json=payload,
        )
        assert created.status_code == 201
        assert (
            client.post(
                "/api/v1/spending/rate-cards",
                headers={"Idempotency-Key": key},
                json=payload,
            ).json()
            == created.json()
        )
        policy = client.put(
            "/api/v1/spending/policy",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "rate_card_id": created.json()["id"],
                "monthly_limit_micros": 500,
                "default_work_limit_micros": 250,
                "active": True,
            },
        )
        assert policy.status_code == 200
        summary = client.get("/api/v1/spending").json()
        assert summary["active"] is True
        assert summary["currency"] == "USD"
        assert "Provider invoices remain authoritative" in summary["invoice_note"]


def test_worker_fails_closed_before_provider_dispatch_without_human_policy(
    settings, engine, mocker
) -> None:
    from command_center.agents.worker import perform_next

    with Session(engine, expire_on_commit=False) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Unconfigured spender")
        db.add(owner)
        db.flush()
        run = queued_run(db, owner.id)
        run_id = run.id
    create_model = mocker.patch("command_center.agents.worker.create_chat_model")
    assert perform_next(engine, settings, run_id)
    create_model.assert_not_called()
    with Session(engine) as db:
        failed = db.get(AgentRun, run_id)
        assert failed is not None
        assert failed.state == "failed"
        assert failed.error_code == "spending_policy_unconfigured"


def test_spending_defaults_endpoint_and_fallback_unblocks_testing(settings, engine) -> None:
    owner_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner_id, kind="human", display_name="Defaults user"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner_id, "synthetic")
    with TestClient(app) as client:
        before = client.get("/api/v1/spending").json()
        assert before["configured"] is False
        assert before["readiness"]["code"] == "spending_policy_unconfigured"

        applied = client.post(
            "/api/v1/spending/defaults",
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert applied.status_code == 200
        data = applied.json()
        assert data["configured"] is True
        assert data["active"] is True
        assert data["monthly_limit_micros"] == 100_000_000

        with Session(engine) as db:
            card = db.get(SpendingRateCard, UUID(data["rate_card_id"]))
            assert card is not None
            fallback_rate = card.model_rate("openai", "experimental-unlisted-model")
            assert fallback_rate["input_per_million_micros"] == 500_000
            assert fallback_rate["output_per_million_micros"] == 1_500_000
