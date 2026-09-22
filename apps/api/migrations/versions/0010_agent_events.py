"""Durable per-run agent activity.

Revision ID: 0010_agent_events
Revises: 0009_application_preparations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_agent_events"
down_revision: str | None = "0009_application_preparations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_agent_events_sequence")),
        sa.CheckConstraint(
            "type IN ('text-delta', 'tool-input-available', 'tool-output-available', "
            "'tool-output-error', 'usage', 'run-status')",
            name=op.f("ck_agent_events_type"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(data) = 'object'", name=op.f("ck_agent_events_data_object")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name=op.f("fk_agent_events_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence", name=op.f("pk_agent_events")),
    )
    op.create_index(
        "ix_agent_events_owner_run_sequence",
        "agent_events",
        ["owner_id", "run_id", "sequence"],
    )
    op.execute("ALTER TABLE agent_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("agent_events")
