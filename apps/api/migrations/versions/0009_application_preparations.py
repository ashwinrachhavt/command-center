"""Application preparations over the shared immutable artifact lifecycle.

Revision ID: 0009_application_preparations
Revises: 0008_browser_assistance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_application_preparations"
down_revision: str | None = "0008_browser_assistance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_preparations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["actors.id"]),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "owner_id"], ["browser_snapshots.id", "browser_snapshots.owner_id"]
        ),
        sa.ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        sa.ForeignKeyConstraint(
            ["opportunity_id", "owner_id"], ["opportunities.id", "opportunities.owner_id"]
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["current_version_id"], ["artifact_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
        sa.UniqueConstraint("artifact_id"),
    )
    for column in ("owner_id", "snapshot_id", "opportunity_id"):
        op.create_index(
            op.f(f"ix_application_preparations_{column}"), "application_preparations", [column]
        )
    op.execute("ALTER TABLE application_preparations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("application_preparations")
