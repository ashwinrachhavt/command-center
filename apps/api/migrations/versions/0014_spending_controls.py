"""Atomic owner/month and work spending controls.

Revision ID: 0014_spending_controls
Revises: 0013_research_documents
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_spending_controls"
down_revision: str | None = "0013_research_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spending_rate_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_label", sa.String(length=500), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("rates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency = 'USD'", name=op.f("ck_spending_rate_cards_currency_usd")),
        sa.CheckConstraint(
            "jsonb_typeof(rates) = 'object'",
            name=op.f("ck_spending_rate_cards_rates_object"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_spending_rate_cards_owner_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spending_rate_cards")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_spending_rate_cards_id")),
        sa.UniqueConstraint("owner_id", "sha256", name=op.f("uq_spending_rate_cards_owner_id")),
    )
    op.create_index(op.f("ix_spending_rate_cards_owner_id"), "spending_rate_cards", ["owner_id"])
    op.execute("ALTER TABLE spending_rate_cards ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "spending_policies",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("active_rate_card_id", sa.Uuid(), nullable=False),
        sa.Column("monthly_limit_micros", sa.BigInteger(), nullable=False),
        sa.Column("default_work_limit_micros", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "default_work_limit_micros >= 0",
            name=op.f("ck_spending_policies_default_work_limit"),
        ),
        sa.CheckConstraint(
            "monthly_limit_micros >= 0",
            name=op.f("ck_spending_policies_monthly_limit"),
        ),
        sa.ForeignKeyConstraint(
            ["active_rate_card_id", "owner_id"],
            ["spending_rate_cards.id", "spending_rate_cards.owner_id"],
            name=op.f("fk_spending_policies_active_rate_card_id_spending_rate_cards"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_spending_policies_owner_id_actors")
        ),
        sa.PrimaryKeyConstraint("owner_id", name=op.f("pk_spending_policies")),
    )
    op.execute("ALTER TABLE spending_policies ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "spending_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("rate_card_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limit_micros", sa.BigInteger(), nullable=False),
        sa.Column("reserved_micros", sa.BigInteger(), nullable=False),
        sa.Column("accounted_micros", sa.BigInteger(), nullable=False),
        sa.Column("unknown_micros", sa.BigInteger(), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("accounted_micros >= 0", name=op.f("ck_spending_periods_accounted")),
        sa.CheckConstraint("limit_micros >= 0", name=op.f("ck_spending_periods_limit")),
        sa.CheckConstraint("reserved_micros >= 0", name=op.f("ck_spending_periods_reserved")),
        sa.CheckConstraint("unknown_micros >= 0", name=op.f("ck_spending_periods_unknown")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_spending_periods_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["rate_card_id", "owner_id"],
            ["spending_rate_cards.id", "spending_rate_cards.owner_id"],
            name=op.f("fk_spending_periods_rate_card_id_spending_rate_cards"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spending_periods")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_spending_periods_id")),
        sa.UniqueConstraint("owner_id", "starts_at", name=op.f("uq_spending_periods_owner_id")),
    )
    op.create_index(op.f("ix_spending_periods_owner_id"), "spending_periods", ["owner_id"])
    op.execute("ALTER TABLE spending_periods ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "spending_work_budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("standalone_run_id", sa.Uuid(), nullable=True),
        sa.Column("request_scope_id", sa.Uuid(), nullable=True),
        sa.Column("limit_micros", sa.BigInteger(), nullable=False),
        sa.Column("reserved_micros", sa.BigInteger(), nullable=False),
        sa.Column("accounted_micros", sa.BigInteger(), nullable=False),
        sa.Column("unknown_micros", sa.BigInteger(), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "accounted_micros >= 0", name=op.f("ck_spending_work_budgets_accounted")
        ),
        sa.CheckConstraint("limit_micros >= 0", name=op.f("ck_spending_work_budgets_limit")),
        sa.CheckConstraint(
            "num_nonnulls(task_id, opportunity_id, standalone_run_id, request_scope_id) = 1",
            name=op.f("ck_spending_work_budgets_one_scope"),
        ),
        sa.CheckConstraint("reserved_micros >= 0", name=op.f("ck_spending_work_budgets_reserved")),
        sa.CheckConstraint("unknown_micros >= 0", name=op.f("ck_spending_work_budgets_unknown")),
        sa.ForeignKeyConstraint(
            ["opportunity_id", "owner_id"],
            ["opportunities.id", "opportunities.owner_id"],
            name=op.f("fk_spending_work_budgets_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_spending_work_budgets_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["standalone_run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name=op.f("fk_spending_work_budgets_standalone_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "owner_id"],
            ["tasks.id", "tasks.owner_id"],
            name=op.f("fk_spending_work_budgets_task_id_tasks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spending_work_budgets")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_spending_work_budgets_id")),
    )
    for column in ("owner_id",):
        op.create_index(
            op.f(f"ix_spending_work_budgets_{column}"), "spending_work_budgets", [column]
        )
    op.create_index(
        "uq_spending_work_task",
        "spending_work_budgets",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("task_id IS NOT NULL"),
    )
    op.create_index(
        "uq_spending_work_opportunity",
        "spending_work_budgets",
        ["opportunity_id"],
        unique=True,
        postgresql_where=sa.text("opportunity_id IS NOT NULL"),
    )
    op.create_index(
        "uq_spending_work_run",
        "spending_work_budgets",
        ["standalone_run_id"],
        unique=True,
        postgresql_where=sa.text("standalone_run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_spending_work_request",
        "spending_work_budgets",
        ["owner_id", "request_scope_id"],
        unique=True,
        postgresql_where=sa.text("request_scope_id IS NOT NULL"),
    )
    op.execute("ALTER TABLE spending_work_budgets ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "spending_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("original_lease_id", sa.Uuid(), nullable=True),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("work_budget_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("resource", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("input_token_bound", sa.Integer(), nullable=False),
        sa.Column("output_token_bound", sa.Integer(), nullable=False),
        sa.Column("reserved_micros", sa.BigInteger(), nullable=False),
        sa.Column("accounted_micros", sa.BigInteger(), nullable=True),
        sa.Column("provider_billed_micros", sa.BigInteger(), nullable=True),
        sa.Column("rate_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "accounted_micros IS NULL OR accounted_micros >= 0",
            name=op.f("ck_spending_reservations_accounted"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rate_snapshot) = 'object'",
            name=op.f("ck_spending_reservations_rate_snapshot_object"),
        ),
        sa.CheckConstraint(
            "kind IN ('model', 'connected_tool')",
            name=op.f("ck_spending_reservations_kind"),
        ),
        sa.CheckConstraint(
            "kind != 'model' OR (agent_run_id IS NOT NULL AND original_lease_id IS NOT NULL)",
            name=op.f("ck_spending_reservations_model_run_lease"),
        ),
        sa.CheckConstraint("reserved_micros >= 0", name=op.f("ck_spending_reservations_reserved")),
        sa.CheckConstraint(
            "state IN ('reserved', 'settled', 'unknown', 'released')",
            name=op.f("ck_spending_reservations_state"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(usage) = 'object'",
            name=op.f("ck_spending_reservations_usage_object"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name=op.f("fk_spending_reservations_agent_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_spending_reservations_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["period_id", "owner_id"],
            ["spending_periods.id", "spending_periods.owner_id"],
            name=op.f("fk_spending_reservations_period_id_spending_periods"),
        ),
        sa.ForeignKeyConstraint(
            ["work_budget_id", "owner_id"],
            ["spending_work_budgets.id", "spending_work_budgets.owner_id"],
            name=op.f("fk_spending_reservations_work_budget_id_spending_work_budgets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spending_reservations")),
        sa.UniqueConstraint(
            "owner_id",
            "kind",
            "operation_id",
            name=op.f("uq_spending_reservations_owner_id"),
        ),
    )
    op.create_index(
        op.f("ix_spending_reservations_agent_run_id"),
        "spending_reservations",
        ["agent_run_id"],
    )
    op.create_index(
        op.f("ix_spending_reservations_owner_id"), "spending_reservations", ["owner_id"]
    )
    op.create_index(
        "ix_spending_reservations_owner_state",
        "spending_reservations",
        ["owner_id", "state"],
    )
    op.execute("ALTER TABLE spending_reservations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("spending_reservations")
    op.drop_table("spending_work_budgets")
    op.drop_table("spending_periods")
    op.drop_table("spending_policies")
    op.drop_table("spending_rate_cards")
