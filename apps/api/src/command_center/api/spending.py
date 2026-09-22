"""Human spending configuration and readable ledger summaries."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import Field
from sqlalchemy import select

from command_center.agents.config import load_profiles
from command_center.api import schemas as s
from command_center.api.workspace import Database, WriteKey, owned
from command_center.core.identity import CurrentIdentity
from command_center.db.agents import AgentRun
from command_center.db.idempotency import RequestReceipt
from command_center.db.reviewed_actions import ACTION_LABEL_FOR_KIND, TOOL_FOR_KIND
from command_center.db.spending import (
    SpendingDenied,
    SpendingPeriod,
    SpendingPolicy,
    SpendingRateCard,
    SpendingReservation,
    SpendingWorkBudget,
    ensure_default_spending_policy,
    utc_month,
)
from command_center.integrations.composio_actions import CONNECTED_OPERATION_LABELS

router = APIRouter(prefix="/api/v1/spending", tags=["spending"])

MESSAGES = {
    "cost_bound_unavailable": "Add an immutable rate for every selected provider model or tool.",
    "spending_limit_below_committed": (
        "The limit cannot be below reserved, accounted, or unknown spend."
    ),
    "spending_monthly_limit": "This operation would exceed the configured monthly limit.",
    "spending_period_expired": "This run's monthly spending snapshot expired. Start a new run.",
    "spending_policy_changed": "Spending settings changed. Refresh before saving again.",
    "spending_policy_unconfigured": "Configure and activate spending limits and a rate card first.",
    "spending_work_budget_changed": "This work limit changed. Refresh before saving again.",
    "spending_work_limit": "This operation would exceed the configured work limit.",
    "spending_work_scope_unavailable": "Choose an owned task or opportunity.",
}


class ModelRate(s.Contract):
    provider: str = Field(min_length=1, max_length=30)
    model: str = Field(min_length=1, max_length=200)
    input_per_million_micros: int = Field(ge=0)
    output_per_million_micros: int = Field(ge=0)
    fixed_micros: int = Field(ge=0)


class ToolRate(s.Contract):
    slug: str = Field(min_length=1, max_length=200)
    fixed_micros: int = Field(ge=0)


class RateCardCreate(s.Contract):
    name: str = Field(min_length=1, max_length=200)
    source_label: str = Field(min_length=1, max_length=500)
    models: list[ModelRate]
    tools: list[ToolRate] = Field(default_factory=list)


class RateSet(s.Contract):
    models: list[ModelRate]
    tools: list[ToolRate]


class RateCardRead(s.Contract):
    id: UUID
    name: str
    source_label: str
    currency: Literal["USD"]
    rates: RateSet
    sha256: str
    created_at: datetime


class CatalogModel(s.Contract):
    provider: str
    model: str
    label: str


class CatalogTool(s.Contract):
    slug: str
    label: str


class SpendingCatalog(s.Contract):
    models: list[CatalogModel]
    tools: list[CatalogTool]


class PolicyUpdate(s.Contract):
    rate_card_id: UUID
    monthly_limit_micros: int = Field(ge=0)
    default_work_limit_micros: int = Field(ge=0)
    active: bool = True
    expected_version: int | None = Field(default=None, ge=0)


class PolicyRead(s.Contract):
    active: bool
    rate_card_id: UUID
    monthly_limit_micros: int
    default_work_limit_micros: int
    row_version: int


class WorkLimitUpdate(s.Contract):
    limit_micros: int = Field(ge=0)
    expected_version: int | None = Field(default=None, ge=0)


class Scope(s.Contract):
    type: Literal["task", "opportunity", "request"]
    id: UUID


class WorkBudgetRead(s.Contract):
    id: UUID
    scope: Scope | None
    standalone_run_id: UUID | None
    limit_micros: int
    reserved_micros: int
    accounted_micros: int
    unknown_micros: int
    committed_micros: int
    row_version: int


class Readiness(s.Contract):
    code: str
    message: str


class PeriodRead(s.Contract):
    starts_at: datetime
    ends_at: datetime
    limit_micros: int
    reserved_micros: int
    accounted_micros: int
    unknown_micros: int
    committed_micros: int


class SpendingSummary(s.Contract):
    currency: Literal["USD"]
    configured: bool
    active: bool
    rate_card_id: UUID | None
    monthly_limit_micros: int | None
    default_work_limit_micros: int | None
    row_version: int | None
    readiness: Readiness | None
    period: PeriodRead | None
    work_budgets: list[WorkBudgetRead]
    invoice_note: str


class SpendingSnapshot(s.Contract):
    policy_version: int
    rate_card_id: UUID
    rate_card_sha256: str
    monthly_limit_micros: int
    default_work_limit_micros: int
    period_id: UUID
    period_starts_at: datetime
    period_ends_at: datetime
    work_budget_id: UUID
    work_limit_micros: int
    currency: Literal["USD"]


class RunTotals(s.Contract):
    reserved_micros: int
    accounted_micros: int
    unknown_micros: int


class ReservationUsage(s.Contract):
    input_tokens: int | None = None
    output_tokens: int | None = None
    operation_id: UUID | None = None


class ReservationRead(s.Contract):
    id: UUID
    kind: Literal["model", "connected_tool"]
    operation_id: UUID
    role: str
    provider: str
    resource: str
    state: Literal["reserved", "settled", "unknown", "released"]
    reserved_micros: int
    accounted_micros: int | None
    provider_billed_micros: int | None
    usage: ReservationUsage
    error_code: str | None
    created_at: datetime
    settled_at: datetime | None


class RunSpendingRead(s.Contract):
    run_id: UUID
    currency: Literal["USD"]
    snapshot: SpendingSnapshot | None
    totals: RunTotals
    reservations: list[ReservationRead]


def denied(exc: SpendingDenied) -> HTTPException:
    return HTTPException(
        409,
        {"code": exc.code, "message": MESSAGES.get(exc.code, "Spending control denied it.")},
    )


def card_json(card: SpendingRateCard) -> dict[str, Any]:
    return dict(
        jsonable_encoder(
            {
                "id": card.id,
                "name": card.name,
                "source_label": card.source_label,
                "currency": card.currency,
                "rates": card.rates,
                "sha256": card.sha256,
                "created_at": card.created_at,
            }
        )
    )


def budget_json(budget: SpendingWorkBudget) -> dict[str, Any]:
    scope = (
        Scope(type="task", id=budget.task_id)
        if budget.task_id
        else Scope(type="opportunity", id=budget.opportunity_id)
        if budget.opportunity_id
        else Scope(type="request", id=budget.request_scope_id)
        if budget.request_scope_id
        else None
    )
    return dict(
        jsonable_encoder(
            {
                "id": budget.id,
                "scope": scope,
                "standalone_run_id": budget.standalone_run_id,
                "limit_micros": budget.limit_micros,
                "reserved_micros": budget.reserved_micros,
                "accounted_micros": budget.accounted_micros,
                "unknown_micros": budget.unknown_micros,
                "committed_micros": budget.committed_micros,
                "row_version": budget.row_version,
            }
        )
    )


@router.get("/catalog", response_model=SpendingCatalog)
def catalog(identity: CurrentIdentity, request: Request) -> SpendingCatalog:
    configured, _ = load_profiles(
        request.app.state.settings.agent_config,
        request.app.state.settings.agent_skills_dir,
    )
    pending = list(configured.values())
    model_ids: set[tuple[str, str]] = set()
    while pending:
        profile = pending.pop()
        model_ids.add((profile.provider, profile.model))
        pending.extend(profile.specialists.values())
    action_operations = {TOOL_FOR_KIND[kind]: ACTION_LABEL_FOR_KIND[kind] for kind in TOOL_FOR_KIND}
    operations = {**CONNECTED_OPERATION_LABELS, **action_operations}
    return SpendingCatalog(
        models=[
            CatalogModel(
                provider=provider,
                model=model,
                label=f"{provider.title()} · {model}",
            )
            for provider, model in sorted(model_ids)
        ],
        tools=[
            CatalogTool(slug=slug, label=label)
            for slug, label in sorted(operations.items(), key=lambda item: (item[1], item[0]))
        ],
    )


@router.get("", response_model=SpendingSummary)
def spending(identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    policy = db.get(SpendingPolicy, identity.id)
    start, _ = utc_month()
    period = db.scalar(
        select(SpendingPeriod).where(
            SpendingPeriod.owner_id == identity.id,
            SpendingPeriod.starts_at == start,
        )
    )
    budgets = db.scalars(
        select(SpendingWorkBudget)
        .where(SpendingWorkBudget.owner_id == identity.id)
        .order_by(SpendingWorkBudget.updated_at.desc())
        .limit(100)
    ).all()
    readiness = (
        None
        if policy is not None and policy.active
        else {
            "code": "spending_policy_unconfigured",
            "message": MESSAGES["spending_policy_unconfigured"],
        }
    )
    return {
        "currency": "USD",
        "configured": policy is not None,
        "active": policy.active if policy else False,
        "rate_card_id": policy.active_rate_card_id if policy else None,
        "monthly_limit_micros": policy.monthly_limit_micros if policy else None,
        "default_work_limit_micros": policy.default_work_limit_micros if policy else None,
        "row_version": policy.row_version if policy else None,
        "readiness": readiness,
        "period": (
            {
                "starts_at": period.starts_at,
                "ends_at": period.ends_at,
                "limit_micros": period.limit_micros,
                "reserved_micros": period.reserved_micros,
                "accounted_micros": period.accounted_micros,
                "unknown_micros": period.unknown_micros,
                "committed_micros": period.committed_micros,
            }
            if period
            else None
        ),
        "work_budgets": [budget_json(row) for row in budgets],
        "invoice_note": (
            "Configured rates are conservative application bounds. Provider invoices remain "
            "authoritative; unknown spend is retained until reconciled."
        ),
    }


@router.get("/rate-cards", response_model=list[RateCardRead])
def rate_cards(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SpendingRateCard)
        .where(SpendingRateCard.owner_id == identity.id)
        .order_by(SpendingRateCard.created_at.desc())
    ).all()
    return [card_json(row) for row in rows]


@router.post("/rate-cards", response_model=RateCardRead, status_code=201)
def create_rate_card(
    body: RateCardCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(row_id: UUID) -> dict[str, Any]:
        card = SpendingRateCard.create(
            db,
            owner_id=identity.id,
            name=body.name,
            source_label=body.source_label,
            rates={
                "models": [row.model_dump() for row in body.models],
                "tools": [row.model_dump() for row in body.tools],
            },
            request_id=row_id,
            card_id=row_id,
        )
        return card_json(card)

    return RequestReceipt.execute(
        db,
        actor_id=identity.id,
        key=key,
        operation="POST:spending-rate-cards",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.put("/policy", response_model=PolicyRead)
def update_policy(
    body: PolicyUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(request_id: UUID) -> dict[str, Any]:
        try:
            policy = SpendingPolicy.configure(
                db,
                owner_id=identity.id,
                rate_card_id=body.rate_card_id,
                monthly_limit_micros=body.monthly_limit_micros,
                default_work_limit_micros=body.default_work_limit_micros,
                active=body.active,
                request_id=request_id,
                expected_version=body.expected_version,
            )
        except SpendingDenied as exc:
            raise denied(exc) from exc
        db.flush([policy])
        return dict(
            jsonable_encoder(
                {
                    "active": policy.active,
                    "rate_card_id": policy.active_rate_card_id,
                    "monthly_limit_micros": policy.monthly_limit_micros,
                    "default_work_limit_micros": policy.default_work_limit_micros,
                    "row_version": policy.row_version,
                }
            )
        )

    return RequestReceipt.execute(
        db,
        actor_id=identity.id,
        key=key,
        operation="PUT:spending-policy",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.post("/defaults", response_model=SpendingSummary)
def apply_defaults(
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    def change(request_id: UUID) -> dict[str, Any]:
        ensure_default_spending_policy(db, identity.id, request_id=request_id)
        db.flush()
        return dict(jsonable_encoder(spending(identity, db)))

    return RequestReceipt.execute(
        db,
        actor_id=identity.id,
        key=key,
        operation="POST:spending-defaults",
        payload={},
        change=change,
    )


def configure_work(
    scope_type: Literal["task", "opportunity"],
    scope_id: UUID,
    body: WorkLimitUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: UUID,
) -> dict[str, Any]:
    def change(request_id: UUID) -> dict[str, Any]:
        try:
            budget = SpendingWorkBudget.configure_limit(
                db,
                owner_id=identity.id,
                task_id=scope_id if scope_type == "task" else None,
                opportunity_id=scope_id if scope_type == "opportunity" else None,
                limit_micros=body.limit_micros,
                expected_version=body.expected_version,
                request_id=request_id,
            )
        except SpendingDenied as exc:
            raise denied(exc) from exc
        db.flush([budget])
        return budget_json(budget)

    return RequestReceipt.execute(
        db,
        actor_id=identity.id,
        key=key,
        operation=f"PUT:spending-work:{scope_type}:{scope_id}",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.put("/tasks/{task_id}", response_model=WorkBudgetRead)
def configure_task(
    task_id: UUID,
    body: WorkLimitUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    return configure_work("task", task_id, body, identity, db, key)


@router.put("/opportunities/{opportunity_id}", response_model=WorkBudgetRead)
def configure_opportunity(
    opportunity_id: UUID,
    body: WorkLimitUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    return configure_work("opportunity", opportunity_id, body, identity, db, key)


@router.get("/agent-runs/{run_id}", response_model=RunSpendingRead)
def run_spending(run_id: UUID, identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    run = owned(db, AgentRun, run_id, identity.id)
    rows = db.scalars(
        select(SpendingReservation)
        .where(
            SpendingReservation.owner_id == identity.id,
            SpendingReservation.agent_run_id == run.id,
        )
        .order_by(SpendingReservation.created_at)
    ).all()
    return {
        "run_id": run.id,
        "currency": "USD",
        "snapshot": run.config_snapshot.get("spending"),
        "totals": {
            "reserved_micros": sum(row.reserved_micros for row in rows if row.state == "reserved"),
            "accounted_micros": sum(row.accounted_micros or 0 for row in rows),
            "unknown_micros": sum(row.reserved_micros for row in rows if row.state == "unknown"),
        },
        "reservations": [
            {
                "id": row.id,
                "kind": row.kind,
                "operation_id": row.operation_id,
                "role": row.role,
                "provider": row.provider,
                "resource": row.resource,
                "state": row.state,
                "reserved_micros": row.reserved_micros,
                "accounted_micros": row.accounted_micros,
                "provider_billed_micros": row.provider_billed_micros,
                "usage": row.usage,
                "error_code": row.error_code,
                "created_at": row.created_at,
                "settled_at": row.settled_at,
            }
            for row in rows
        ],
    }
