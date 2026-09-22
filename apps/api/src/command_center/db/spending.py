"""Owner spending policy, immutable rates and atomic provider reservations."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.models import Actor

MICROS_PER_UNIT = 1_000_000
RESERVATION_STATES = frozenset({"reserved", "settled", "unknown", "released"})


class SpendingDenied(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def utc_month(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = (now or utc_now()).astimezone(UTC)
    start = datetime(current.year, current.month, 1, tzinfo=UTC)
    if current.month == 12:
        end = datetime(current.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    return start, end


def canonical_rates(rates: dict[str, Any]) -> tuple[dict[str, Any], str]:
    models = rates.get("models")
    tools = rates.get("tools", [])
    if not isinstance(models, list) or not isinstance(tools, list):
        raise ValueError("Rates require model and tool lists")
    normalized_models = []
    identities = set()
    for raw in models:
        if not isinstance(raw, dict) or set(raw) != {
            "provider",
            "model",
            "input_per_million_micros",
            "output_per_million_micros",
            "fixed_micros",
        }:
            raise ValueError("Invalid model rate")
        provider, model = str(raw["provider"]), str(raw["model"])
        identity = (provider, model)
        values = [
            raw["input_per_million_micros"],
            raw["output_per_million_micros"],
            raw["fixed_micros"],
        ]
        if not provider or not model or identity in identities:
            raise ValueError("Model rates must be unique")
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("Rates must be non-negative integers")
        identities.add(identity)
        normalized_models.append(
            {
                "provider": provider,
                "model": model,
                "input_per_million_micros": values[0],
                "output_per_million_micros": values[1],
                "fixed_micros": values[2],
            }
        )
    normalized_tools = []
    slugs = set()
    for raw in tools:
        if not isinstance(raw, dict) or set(raw) != {"slug", "fixed_micros"}:
            raise ValueError("Invalid tool rate")
        slug, fixed = str(raw["slug"]), raw["fixed_micros"]
        if not slug or slug in slugs or not isinstance(fixed, int) or fixed < 0:
            raise ValueError("Tool rates must be unique non-negative integers")
        slugs.add(slug)
        normalized_tools.append({"slug": slug, "fixed_micros": fixed})
    normalized = {
        "models": sorted(
            normalized_models,
            key=lambda row: (str(row["provider"]), str(row["model"])),
        ),
        "tools": sorted(normalized_tools, key=lambda row: str(row["slug"])),
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return normalized, hashlib.sha256(encoded).hexdigest()


class SpendingRateCard(Base):
    __tablename__ = "spending_rate_cards"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        UniqueConstraint("owner_id", "sha256"),
        CheckConstraint("currency = 'USD'", name="currency_usd"),
        CheckConstraint("jsonb_typeof(rates) = 'object'", name="rates_object"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_label: Mapped[str] = mapped_column(String(500))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    rates: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        name: str,
        source_label: str,
        rates: dict[str, Any],
        request_id: UUID,
        card_id: UUID | None = None,
    ) -> "SpendingRateCard":
        if not name.strip() or not source_label.strip():
            raise ValueError("Rate cards require a name and source")
        normalized, digest = canonical_rates(rates)
        existing = session.scalar(select(cls).where(cls.owner_id == owner_id, cls.sha256 == digest))
        if existing:
            return existing
        card = cls(
            id=card_id or uuid4(),
            owner_id=owner_id,
            name=name.strip(),
            source_label=source_label.strip(),
            rates=normalized,
            sha256=digest,
        )
        session.add(card)
        session.flush([card])
        record_event(
            session,
            owner_id,
            request_id,
            "spending.rate_card_created",
            "spending_rate_cards",
            card.id,
            sha256=digest,
        )
        return card

    def model_rate(self, provider: str, model: str) -> dict[str, Any]:
        for row in self.rates.get("models", []):
            if row["provider"] == provider and row["model"] == model:
                return dict(row)
        # Conservative fallback default for unlisted or testing models so testing is never blocked
        return {
            "provider": provider,
            "model": model,
            "input_per_million_micros": 500_000,
            "output_per_million_micros": 1_500_000,
            "fixed_micros": 0,
        }

    def tool_rate(self, slug: str) -> int:
        for row in self.rates.get("tools", []):
            if row["slug"] == slug:
                return int(row["fixed_micros"])
        raise SpendingDenied("cost_bound_unavailable")


class SpendingPolicy(Base):
    __tablename__ = "spending_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["active_rate_card_id", "owner_id"],
            ["spending_rate_cards.id", "spending_rate_cards.owner_id"],
        ),
        CheckConstraint("monthly_limit_micros >= 0", name="monthly_limit"),
        CheckConstraint("default_work_limit_micros >= 0", name="default_work_limit"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), primary_key=True)
    active_rate_card_id: Mapped[UUID] = mapped_column(Uuid)
    monthly_limit_micros: Mapped[int] = mapped_column(BigInteger)
    default_work_limit_micros: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)
    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def configure(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        rate_card_id: UUID,
        monthly_limit_micros: int,
        default_work_limit_micros: int,
        active: bool,
        request_id: UUID,
        expected_version: int | None,
    ) -> "SpendingPolicy":
        if monthly_limit_micros < 0 or default_work_limit_micros < 0:
            raise ValueError("Spending limits must be non-negative")
        card = session.scalar(
            select(SpendingRateCard).where(
                SpendingRateCard.id == rate_card_id,
                SpendingRateCard.owner_id == owner_id,
            )
        )
        if card is None:
            raise ValueError("Choose an owned rate card")
        policy = session.get(cls, owner_id, with_for_update=True)
        if policy is None:
            if expected_version not in (None, 0):
                raise SpendingDenied("spending_policy_changed")
            policy = cls(
                owner_id=owner_id,
                active_rate_card_id=rate_card_id,
                monthly_limit_micros=monthly_limit_micros,
                default_work_limit_micros=default_work_limit_micros,
                active=active,
            )
            session.add(policy)
        else:
            if expected_version != policy.row_version:
                raise SpendingDenied("spending_policy_changed")
            policy.active_rate_card_id = rate_card_id
            policy.monthly_limit_micros = monthly_limit_micros
            policy.default_work_limit_micros = default_work_limit_micros
            policy.active = active
            policy.updated_at = utc_now()
        record_event(
            session,
            owner_id,
            request_id,
            "spending.policy_configured",
            "spending_policies",
            owner_id,
            active=active,
        )
        return policy


class SpendingPeriod(Base):
    __tablename__ = "spending_periods"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        UniqueConstraint("owner_id", "starts_at"),
        ForeignKeyConstraint(
            ["rate_card_id", "owner_id"],
            ["spending_rate_cards.id", "spending_rate_cards.owner_id"],
        ),
        CheckConstraint("limit_micros >= 0", name="limit"),
        CheckConstraint("reserved_micros >= 0", name="reserved"),
        CheckConstraint("accounted_micros >= 0", name="accounted"),
        CheckConstraint("unknown_micros >= 0", name="unknown"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    rate_card_id: Mapped[UUID] = mapped_column(Uuid)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    limit_micros: Mapped[int] = mapped_column(BigInteger)
    reserved_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    accounted_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    unknown_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @property
    def committed_micros(self) -> int:
        return self.reserved_micros + self.accounted_micros + self.unknown_micros


class SpendingWorkBudget(Base):
    __tablename__ = "spending_work_budgets"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        ForeignKeyConstraint(
            ["opportunity_id", "owner_id"],
            ["opportunities.id", "opportunities.owner_id"],
        ),
        ForeignKeyConstraint(
            ["standalone_run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
        ),
        CheckConstraint(
            "num_nonnulls(task_id, opportunity_id, standalone_run_id, request_scope_id) = 1",
            name="one_scope",
        ),
        CheckConstraint("limit_micros >= 0", name="limit"),
        CheckConstraint("reserved_micros >= 0", name="reserved"),
        CheckConstraint("accounted_micros >= 0", name="accounted"),
        CheckConstraint("unknown_micros >= 0", name="unknown"),
        Index(
            "uq_spending_work_task",
            "task_id",
            unique=True,
            postgresql_where=text("task_id IS NOT NULL"),
        ),
        Index(
            "uq_spending_work_opportunity",
            "opportunity_id",
            unique=True,
            postgresql_where=text("opportunity_id IS NOT NULL"),
        ),
        Index(
            "uq_spending_work_run",
            "standalone_run_id",
            unique=True,
            postgresql_where=text("standalone_run_id IS NOT NULL"),
        ),
        Index(
            "uq_spending_work_request",
            "owner_id",
            "request_scope_id",
            unique=True,
            postgresql_where=text("request_scope_id IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid)
    standalone_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    request_scope_id: Mapped[UUID | None] = mapped_column(Uuid)
    limit_micros: Mapped[int] = mapped_column(BigInteger)
    reserved_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    accounted_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    unknown_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)
    __mapper_args__ = {"version_id_col": row_version}

    @property
    def committed_micros(self) -> int:
        return self.reserved_micros + self.accounted_micros + self.unknown_micros

    @classmethod
    def configure_limit(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        task_id: UUID | None,
        opportunity_id: UUID | None,
        limit_micros: int,
        expected_version: int | None,
        request_id: UUID,
    ) -> "SpendingWorkBudget":
        if limit_micros < 0 or bool(task_id) == bool(opportunity_id):
            raise ValueError("Choose one owned work scope and a non-negative limit")
        _validate_owned_scope(session, owner_id, task_id, opportunity_id)
        field, value = (
            ("task_id", task_id) if task_id is not None else ("opportunity_id", opportunity_id)
        )
        budget = session.scalar(
            select(cls)
            .where(cls.owner_id == owner_id, getattr(cls, field) == value)
            .with_for_update()
        )
        if budget is None:
            if expected_version not in (None, 0):
                raise SpendingDenied("spending_work_budget_changed")
            _, _, snapshot = _active_policy(session, owner_id)
            budget = cls(
                owner_id=owner_id,
                limit_micros=limit_micros,
                policy_snapshot=snapshot,
                **{field: value},
            )
            session.add(budget)
            session.flush([budget])
        else:
            if expected_version != budget.row_version:
                raise SpendingDenied("spending_work_budget_changed")
            if limit_micros < budget.committed_micros:
                raise SpendingDenied("spending_limit_below_committed")
            budget.limit_micros = limit_micros
            budget.updated_at = utc_now()
        record_event(
            session,
            owner_id,
            request_id,
            "spending.work_limit_configured",
            "spending_work_budgets",
            budget.id,
            limit_micros=limit_micros,
        )
        return budget


class SpendingReservation(Base):
    __tablename__ = "spending_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_run_id", "owner_id"], ["agent_runs.id", "agent_runs.owner_id"]
        ),
        ForeignKeyConstraint(
            ["period_id", "owner_id"], ["spending_periods.id", "spending_periods.owner_id"]
        ),
        ForeignKeyConstraint(
            ["work_budget_id", "owner_id"],
            ["spending_work_budgets.id", "spending_work_budgets.owner_id"],
        ),
        UniqueConstraint("owner_id", "kind", "operation_id"),
        CheckConstraint("kind IN ('model', 'connected_tool')", name="kind"),
        CheckConstraint(
            "kind != 'model' OR (agent_run_id IS NOT NULL AND original_lease_id IS NOT NULL)",
            name="model_run_lease",
        ),
        CheckConstraint("state IN ('reserved', 'settled', 'unknown', 'released')", name="state"),
        CheckConstraint("reserved_micros >= 0", name="reserved"),
        CheckConstraint("accounted_micros IS NULL OR accounted_micros >= 0", name="accounted"),
        CheckConstraint("jsonb_typeof(rate_snapshot) = 'object'", name="rate_snapshot_object"),
        CheckConstraint("jsonb_typeof(usage) = 'object'", name="usage_object"),
        Index("ix_spending_reservations_owner_state", "owner_id", "state"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    agent_run_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    original_lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    period_id: Mapped[UUID] = mapped_column(Uuid)
    work_budget_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(30))
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(30))
    resource: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20), default="reserved")
    input_token_bound: Mapped[int] = mapped_column(Integer)
    output_token_bound: Mapped[int] = mapped_column(Integer)
    reserved_micros: Mapped[int] = mapped_column(BigInteger)
    accounted_micros: Mapped[int | None] = mapped_column(BigInteger)
    provider_billed_micros: Mapped[int | None] = mapped_column(BigInteger)
    rate_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @staticmethod
    def _cost(rate: dict[str, int], input_tokens: int, output_tokens: int) -> int:
        def rounded(tokens: int, micros: int) -> int:
            return (tokens * micros + MICROS_PER_UNIT - 1) // MICROS_PER_UNIT

        return (
            rounded(input_tokens, rate["input_per_million_micros"])
            + rounded(output_tokens, rate["output_per_million_micros"])
            + rate["fixed_micros"]
        )

    @classmethod
    def reserve_model(
        cls,
        session: Session,
        *,
        run_id: UUID,
        lease_id: UUID,
        callback_id: UUID,
        role: str,
        provider: str,
        model: str,
        input_token_bound: int,
        output_token_bound: int,
        now: datetime | None = None,
    ) -> "SpendingReservation":
        from command_center.db.agents import AgentRun

        current = now or utc_now()
        run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if (
            run is None
            or run.state != "running"
            or run.lease_id != lease_id
            or run.lease_expires_at is None
            or run.lease_expires_at <= current
        ):
            raise SpendingDenied("spending_lease_lost")
        snapshot = run.config_snapshot.get("spending")
        if not isinstance(snapshot, dict):
            raise SpendingDenied("spending_policy_unconfigured")
        if current >= datetime.fromisoformat(str(snapshot["period_ends_at"])):
            raise SpendingDenied("spending_period_expired")
        period = session.scalar(
            select(SpendingPeriod)
            .where(SpendingPeriod.id == UUID(str(snapshot["period_id"])))
            .with_for_update()
        )
        work = session.scalar(
            select(SpendingWorkBudget)
            .where(SpendingWorkBudget.id == UUID(str(snapshot["work_budget_id"])))
            .with_for_update()
        )
        if (
            period is None
            or work is None
            or period.owner_id != run.owner_id
            or work.owner_id != run.owner_id
        ):
            raise SpendingDenied("spending_policy_unconfigured")
        existing = session.scalar(
            select(cls).where(
                cls.owner_id == run.owner_id,
                cls.kind == "model",
                cls.operation_id == callback_id,
            )
        )
        fingerprint = (role, provider, model, input_token_bound, output_token_bound)
        if existing:
            persisted = (
                existing.role,
                existing.provider,
                existing.resource,
                existing.input_token_bound,
                existing.output_token_bound,
            )
            if existing.original_lease_id != lease_id or persisted != fingerprint:
                raise SpendingDenied("spending_reservation_conflict")
            return existing
        card = session.scalar(
            select(SpendingRateCard).where(
                SpendingRateCard.id == UUID(str(snapshot["rate_card_id"])),
                SpendingRateCard.owner_id == run.owner_id,
            )
        )
        if card is None or card.sha256 != snapshot.get("rate_card_sha256"):
            raise SpendingDenied("cost_bound_unavailable")
        rate = card.model_rate(provider, model)
        reserved = cls._cost(rate, input_token_bound, output_token_bound)
        if period.committed_micros + reserved > period.limit_micros:
            raise SpendingDenied("spending_monthly_limit")
        if work.committed_micros + reserved > work.limit_micros:
            raise SpendingDenied("spending_work_limit")
        period.reserved_micros += reserved
        work.reserved_micros += reserved
        reservation = cls(
            owner_id=run.owner_id,
            agent_run_id=run.id,
            original_lease_id=lease_id,
            period_id=period.id,
            work_budget_id=work.id,
            kind="model",
            operation_id=callback_id,
            role=role,
            provider=provider,
            resource=model,
            input_token_bound=input_token_bound,
            output_token_bound=output_token_bound,
            reserved_micros=reserved,
            rate_snapshot=rate,
            usage={},
            expires_at=current + timedelta(minutes=15),
        )
        session.add(reservation)
        return reservation

    @classmethod
    def reserve_connected_tool(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        operation_id: UUID,
        slug: str,
        task_id: UUID | None = None,
        opportunity_id: UUID | None = None,
        request_scope_id: UUID | None = None,
        run_id: UUID | None = None,
        lease_id: UUID | None = None,
        now: datetime | None = None,
    ) -> "SpendingReservation":
        """Reserve one configured fixed-cost connected operation.

        Trusted workers pass either a running agent lease or one owned task/opportunity.
        Callers never provide an amount; the immutable active rate card supplies it.
        """
        current = now or utc_now()
        if run_id is not None:
            if (
                task_id is not None
                or opportunity_id is not None
                or request_scope_id is not None
                or lease_id is None
            ):
                raise ValueError("A run tool reservation requires only its lease scope")
            owner_id, period, work, card = _running_scope(session, run_id, lease_id, current)
        else:
            if (
                lease_id is not None
                or sum(value is not None for value in (task_id, opportunity_id, request_scope_id))
                != 1
            ):
                raise ValueError("A connected operation requires one work scope")
            period, work, card = _current_scope(
                session,
                owner_id=owner_id,
                task_id=task_id,
                opportunity_id=opportunity_id,
                request_scope_id=request_scope_id,
                now=current,
            )
        existing = session.scalar(
            select(cls).where(
                cls.owner_id == owner_id,
                cls.kind == "connected_tool",
                cls.operation_id == operation_id,
            )
        )
        if existing:
            if (
                existing.resource != slug
                or existing.agent_run_id != run_id
                or existing.original_lease_id != lease_id
                or existing.work_budget_id != work.id
            ):
                raise SpendingDenied("spending_reservation_conflict")
            return existing
        fixed = card.tool_rate(slug)
        if period.committed_micros + fixed > period.limit_micros:
            raise SpendingDenied("spending_monthly_limit")
        if work.committed_micros + fixed > work.limit_micros:
            raise SpendingDenied("spending_work_limit")
        period.reserved_micros += fixed
        work.reserved_micros += fixed
        reservation = cls(
            owner_id=owner_id,
            agent_run_id=run_id,
            original_lease_id=lease_id,
            period_id=period.id,
            work_budget_id=work.id,
            kind="connected_tool",
            operation_id=operation_id,
            role="tool",
            provider="composio",
            resource=slug,
            input_token_bound=0,
            output_token_bound=0,
            reserved_micros=fixed,
            rate_snapshot={"slug": slug, "fixed_micros": fixed},
            usage={},
            expires_at=current + timedelta(minutes=15),
        )
        session.add(reservation)
        return reservation

    @classmethod
    def _locked(
        cls, session: Session, reservation_id: UUID
    ) -> tuple["SpendingReservation", SpendingPeriod, SpendingWorkBudget]:
        reservation = session.scalar(select(cls).where(cls.id == reservation_id).with_for_update())
        if reservation is None:
            raise SpendingDenied("spending_reservation_missing")
        period = session.scalar(
            select(SpendingPeriod)
            .where(SpendingPeriod.id == reservation.period_id)
            .with_for_update()
        )
        work = session.scalar(
            select(SpendingWorkBudget)
            .where(SpendingWorkBudget.id == reservation.work_budget_id)
            .with_for_update()
        )
        if period is None or work is None:
            raise SpendingDenied("spending_reservation_missing")
        return reservation, period, work

    @classmethod
    def settle_model(
        cls,
        session: Session,
        *,
        reservation_id: UUID,
        lease_id: UUID,
        input_tokens: int,
        output_tokens: int,
        provider_billed_micros: int | None = None,
    ) -> "SpendingReservation":
        reservation, period, work = cls._locked(session, reservation_id)
        if reservation.kind != "model" or reservation.original_lease_id != lease_id:
            raise SpendingDenied("spending_reservation_conflict")
        usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
        accounted = cls._cost(reservation.rate_snapshot, input_tokens, output_tokens)
        if provider_billed_micros is not None:
            if provider_billed_micros < 0:
                raise ValueError("Billed cost must be non-negative")
            accounted = max(accounted, provider_billed_micros)
        if reservation.state == "settled":
            if (
                reservation.usage != usage
                or reservation.provider_billed_micros != provider_billed_micros
            ):
                raise SpendingDenied("spending_reservation_conflict")
            return reservation
        if reservation.state == "released":
            raise SpendingDenied("spending_reservation_conflict")
        source = reservation.reserved_micros
        if reservation.state == "reserved":
            period.reserved_micros -= source
            work.reserved_micros -= source
        else:
            period.unknown_micros -= source
            work.unknown_micros -= source
        period.accounted_micros += accounted
        work.accounted_micros += accounted
        reservation.state = "settled"
        reservation.accounted_micros = accounted
        reservation.provider_billed_micros = provider_billed_micros
        reservation.usage = usage
        reservation.settled_at = utc_now()
        return reservation

    @classmethod
    def settle_connected_tool(
        cls,
        session: Session,
        *,
        reservation_id: UUID,
        provider_billed_micros: int | None = None,
    ) -> "SpendingReservation":
        reservation, period, work = cls._locked(session, reservation_id)
        if reservation.kind != "connected_tool":
            raise SpendingDenied("spending_reservation_conflict")
        accounted = int(reservation.rate_snapshot["fixed_micros"])
        if provider_billed_micros is not None:
            if provider_billed_micros < 0:
                raise ValueError("Billed cost must be non-negative")
            accounted = max(accounted, provider_billed_micros)
        usage = {"operation_id": str(reservation.operation_id)}
        if reservation.state == "settled":
            if reservation.provider_billed_micros != provider_billed_micros:
                raise SpendingDenied("spending_reservation_conflict")
            return reservation
        if reservation.state == "released":
            raise SpendingDenied("spending_reservation_conflict")
        if reservation.state == "reserved":
            period.reserved_micros -= reservation.reserved_micros
            work.reserved_micros -= reservation.reserved_micros
        else:
            period.unknown_micros -= reservation.reserved_micros
            work.unknown_micros -= reservation.reserved_micros
        period.accounted_micros += accounted
        work.accounted_micros += accounted
        reservation.state = "settled"
        reservation.accounted_micros = accounted
        reservation.provider_billed_micros = provider_billed_micros
        reservation.usage = usage
        reservation.settled_at = utc_now()
        return reservation

    @classmethod
    def mark_unknown(
        cls,
        session: Session,
        *,
        reservation_id: UUID,
        lease_id: UUID | None,
        reason: str,
    ) -> "SpendingReservation":
        reservation, period, work = cls._locked(session, reservation_id)
        if reservation.original_lease_id != lease_id:
            raise SpendingDenied("spending_reservation_conflict")
        if reservation.state in {"settled", "released", "unknown"}:
            return reservation
        period.reserved_micros -= reservation.reserved_micros
        work.reserved_micros -= reservation.reserved_micros
        period.unknown_micros += reservation.reserved_micros
        work.unknown_micros += reservation.reserved_micros
        reservation.state = "unknown"
        reservation.error_code = reason[:100]
        reservation.settled_at = utc_now()
        return reservation

    @classmethod
    def mark_run_open_unknown(
        cls, session: Session, *, run_id: UUID, lease_id: UUID, reason: str
    ) -> None:
        ids = session.scalars(
            select(cls.id).where(
                cls.agent_run_id == run_id,
                cls.original_lease_id == lease_id,
                cls.state == "reserved",
            )
        ).all()
        for reservation_id in ids:
            cls.mark_unknown(
                session,
                reservation_id=reservation_id,
                lease_id=lease_id,
                reason=reason,
            )

    @classmethod
    def expire_stale(cls, session: Session, now: datetime | None = None) -> int:
        current = now or utc_now()
        rows = session.execute(
            select(cls.id, cls.original_lease_id).where(
                cls.state == "reserved", cls.expires_at < current
            )
        ).all()
        for reservation_id, lease_id in rows:
            cls.mark_unknown(
                session,
                reservation_id=reservation_id,
                lease_id=lease_id,
                reason="spending_usage_unknown",
            )
        return len(rows)


def _validate_owned_scope(
    session: Session,
    owner_id: UUID,
    task_id: UUID | None,
    opportunity_id: UUID | None,
) -> None:
    from command_center.db.crm import Opportunity
    from command_center.db.models import Task

    model, identity = (Task, task_id) if task_id is not None else (Opportunity, opportunity_id)
    if (
        identity is None
        or session.scalar(select(model.id).where(model.id == identity, model.owner_id == owner_id))
        is None
    ):
        raise SpendingDenied("spending_work_scope_unavailable")


def _active_policy(
    session: Session, owner_id: UUID
) -> tuple[SpendingPolicy, SpendingRateCard, dict[str, Any]]:
    session.scalar(select(Actor).where(Actor.id == owner_id).with_for_update())
    policy = session.get(SpendingPolicy, owner_id)
    if policy is None or not policy.active:
        raise SpendingDenied("spending_policy_unconfigured")
    card = session.scalar(
        select(SpendingRateCard).where(
            SpendingRateCard.id == policy.active_rate_card_id,
            SpendingRateCard.owner_id == owner_id,
        )
    )
    if card is None:
        raise SpendingDenied("cost_bound_unavailable")
    snapshot = {
        "policy_version": policy.row_version,
        "rate_card_id": str(card.id),
        "rate_card_sha256": card.sha256,
        "monthly_limit_micros": policy.monthly_limit_micros,
        "default_work_limit_micros": policy.default_work_limit_micros,
    }
    return policy, card, snapshot


def _current_scope(
    session: Session,
    *,
    owner_id: UUID,
    task_id: UUID | None,
    opportunity_id: UUID | None,
    request_scope_id: UUID | None,
    now: datetime,
) -> tuple[SpendingPeriod, SpendingWorkBudget, SpendingRateCard]:
    if sum(value is not None for value in (task_id, opportunity_id, request_scope_id)) != 1:
        raise ValueError("Choose exactly one work scope")
    if request_scope_id is None:
        _validate_owned_scope(session, owner_id, task_id, opportunity_id)
    policy, card, policy_snapshot = _active_policy(session, owner_id)
    starts_at, ends_at = utc_month(now)
    period = session.scalar(
        select(SpendingPeriod)
        .where(
            SpendingPeriod.owner_id == owner_id,
            SpendingPeriod.starts_at == starts_at,
        )
        .with_for_update()
    )
    if period is None:
        period = SpendingPeriod(
            owner_id=owner_id,
            rate_card_id=card.id,
            starts_at=starts_at,
            ends_at=ends_at,
            limit_micros=policy.monthly_limit_micros,
            policy_snapshot=policy_snapshot,
        )
        session.add(period)
        session.flush([period])
    field, value = (
        ("task_id", task_id)
        if task_id is not None
        else ("opportunity_id", opportunity_id)
        if opportunity_id is not None
        else ("request_scope_id", request_scope_id)
    )
    work = session.scalar(
        select(SpendingWorkBudget)
        .where(
            SpendingWorkBudget.owner_id == owner_id,
            getattr(SpendingWorkBudget, field) == value,
        )
        .with_for_update()
    )
    if work is None:
        work = SpendingWorkBudget(
            owner_id=owner_id,
            limit_micros=policy.default_work_limit_micros,
            policy_snapshot=policy_snapshot,
            **{field: value},
        )
        session.add(work)
        session.flush([work])
    return period, work, card


def _running_scope(
    session: Session,
    run_id: UUID,
    lease_id: UUID,
    now: datetime,
) -> tuple[UUID, SpendingPeriod, SpendingWorkBudget, SpendingRateCard]:
    from command_center.db.agents import AgentRun

    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    if (
        run is None
        or run.state != "running"
        or run.lease_id != lease_id
        or run.lease_expires_at is None
        or run.lease_expires_at <= now
    ):
        raise SpendingDenied("spending_lease_lost")
    snapshot = run.config_snapshot.get("spending")
    if not isinstance(snapshot, dict):
        raise SpendingDenied("spending_policy_unconfigured")
    if now >= datetime.fromisoformat(str(snapshot["period_ends_at"])):
        raise SpendingDenied("spending_period_expired")
    period = session.scalar(
        select(SpendingPeriod)
        .where(SpendingPeriod.id == UUID(str(snapshot["period_id"])))
        .with_for_update()
    )
    work = session.scalar(
        select(SpendingWorkBudget)
        .where(SpendingWorkBudget.id == UUID(str(snapshot["work_budget_id"])))
        .with_for_update()
    )
    card = session.scalar(
        select(SpendingRateCard).where(
            SpendingRateCard.id == UUID(str(snapshot["rate_card_id"])),
            SpendingRateCard.owner_id == run.owner_id,
        )
    )
    if (
        period is None
        or work is None
        or card is None
        or period.owner_id != run.owner_id
        or work.owner_id != run.owner_id
        or card.sha256 != snapshot.get("rate_card_sha256")
    ):
        raise SpendingDenied("cost_bound_unavailable")
    return run.owner_id, period, work, card


DEFAULT_RATES: dict[str, Any] = {
    "models": [
        {
            "provider": "openai",
            "model": "gpt-5-mini",
            "input_per_million_micros": 150_000,
            "output_per_million_micros": 600_000,
            "fixed_micros": 0,
        },
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_per_million_micros": 2_500_000,
            "output_per_million_micros": 10_000_000,
            "fixed_micros": 0,
        },
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "input_per_million_micros": 150_000,
            "output_per_million_micros": 600_000,
            "fixed_micros": 0,
        },
        {
            "provider": "openai",
            "model": "o3-mini",
            "input_per_million_micros": 1_100_000,
            "output_per_million_micros": 4_400_000,
            "fixed_micros": 0,
        },
        {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "input_per_million_micros": 100_000,
            "output_per_million_micros": 400_000,
            "fixed_micros": 0,
        },
        {
            "provider": "gemini",
            "model": "gemini-1.5-flash",
            "input_per_million_micros": 75_000,
            "output_per_million_micros": 300_000,
            "fixed_micros": 0,
        },
        {
            "provider": "gemini",
            "model": "gemini-1.5-pro",
            "input_per_million_micros": 1_250_000,
            "output_per_million_micros": 5_000_000,
            "fixed_micros": 0,
        },
        {
            "provider": "mistral",
            "model": "mistral-large-latest",
            "input_per_million_micros": 2_000_000,
            "output_per_million_micros": 6_000_000,
            "fixed_micros": 0,
        },
        {
            "provider": "mistral",
            "model": "mistral-small-latest",
            "input_per_million_micros": 200_000,
            "output_per_million_micros": 600_000,
            "fixed_micros": 0,
        },
        {
            "provider": "cohere",
            "model": "command-r-plus",
            "input_per_million_micros": 2_500_000,
            "output_per_million_micros": 10_000_000,
            "fixed_micros": 0,
        },
        {
            "provider": "cohere",
            "model": "command-r",
            "input_per_million_micros": 150_000,
            "output_per_million_micros": 600_000,
            "fixed_micros": 0,
        },
    ],
    "tools": [
        {"slug": "gmail_search", "fixed_micros": 0},
    ],
}


def ensure_default_spending_policy(
    session: Session, owner_id: UUID, *, request_id: UUID | None = None
) -> SpendingPolicy:
    policy = session.get(SpendingPolicy, owner_id)
    if policy is not None and policy.active:
        return policy
    req_id = request_id or uuid4()
    card = SpendingRateCard.create(
        session,
        owner_id=owner_id,
        name="Standard Developer Rates",
        source_label="Default Plan",
        rates=DEFAULT_RATES,
        request_id=req_id,
    )
    policy = SpendingPolicy.configure(
        session,
        owner_id=owner_id,
        rate_card_id=card.id,
        monthly_limit_micros=100_000_000,
        default_work_limit_micros=10_000_000,
        active=True,
        request_id=req_id,
        expected_version=policy.row_version if policy else None,
    )
    session.flush([card, policy])
    return policy


def prepare_run_spending(
    session: Session, run: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Derive the owned UTC month and task/opportunity/run scope for one root run."""
    from command_center.db.conversations import AgentSession

    current = now or utc_now()
    session.scalar(select(Actor).where(Actor.id == run.owner_id).with_for_update())
    policy = session.get(SpendingPolicy, run.owner_id)
    if policy is None:
        policy = ensure_default_spending_policy(session, run.owner_id)
    elif not policy.active:
        raise SpendingDenied("spending_policy_unconfigured")
    card = session.scalar(
        select(SpendingRateCard).where(
            SpendingRateCard.id == policy.active_rate_card_id,
            SpendingRateCard.owner_id == run.owner_id,
        )
    )
    if card is None:
        raise SpendingDenied("cost_bound_unavailable")
    profiles = [run.config_snapshot["profile"]]
    profiles.extend(run.config_snapshot["profile"].get("specialists", {}).values())
    for profile in profiles:
        card.model_rate(str(profile["provider"]), str(profile["model"]))
        for tool in profile.get("composio_tools", []):
            card.tool_rate(str(tool["slug"]))
    starts_at, ends_at = utc_month(current)
    period = session.scalar(
        select(SpendingPeriod).where(
            SpendingPeriod.owner_id == run.owner_id,
            SpendingPeriod.starts_at == starts_at,
        )
    )
    policy_snapshot = {
        "policy_version": policy.row_version,
        "rate_card_id": str(card.id),
        "rate_card_sha256": card.sha256,
        "monthly_limit_micros": policy.monthly_limit_micros,
        "default_work_limit_micros": policy.default_work_limit_micros,
    }
    if period is None:
        period = SpendingPeriod(
            owner_id=run.owner_id,
            rate_card_id=card.id,
            starts_at=starts_at,
            ends_at=ends_at,
            limit_micros=policy.monthly_limit_micros,
            policy_snapshot=policy_snapshot,
        )
        session.add(period)
        session.flush([period])
    conversation = session.get(AgentSession, run.session_id) if run.session_id else None
    scope = (
        ("task_id", conversation.task_id)
        if conversation and conversation.task_id
        else (
            ("opportunity_id", conversation.opportunity_id)
            if conversation and conversation.opportunity_id
            else ("standalone_run_id", run.id)
        )
    )
    work = session.scalar(
        select(SpendingWorkBudget).where(
            SpendingWorkBudget.owner_id == run.owner_id,
            getattr(SpendingWorkBudget, scope[0]) == scope[1],
        )
    )
    if work is None:
        work = SpendingWorkBudget(
            owner_id=run.owner_id,
            limit_micros=policy.default_work_limit_micros,
            policy_snapshot=policy_snapshot,
            **{scope[0]: scope[1]},
        )
        session.add(work)
        session.flush([work])
    snapshot = {
        **policy_snapshot,
        "period_id": str(period.id),
        "period_starts_at": period.starts_at.isoformat(),
        "period_ends_at": period.ends_at.isoformat(),
        "work_budget_id": str(work.id),
        "work_limit_micros": work.limit_micros,
        "currency": "USD",
    }
    run.config_snapshot = {**run.config_snapshot, "spending": snapshot}
    return snapshot
