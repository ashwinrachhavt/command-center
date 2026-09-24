"""Pin email delivery timing to the exact reviewed revision."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_email_delivery"
down_revision = "0035_jev_gateways"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reviewed_action_revisions", sa.Column("delivery", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "reviewed_action_revisions",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_reviewed_action_revisions_scheduled_for", "reviewed_action_revisions", ["scheduled_for"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM reviewed_action_revisions "
            "WHERE scheduled_for IS NOT NULL)"
        )
    ):
        raise RuntimeError("Retain email schedules and their review history before downgrading")
    op.drop_index(
        "ix_reviewed_action_revisions_scheduled_for", table_name="reviewed_action_revisions"
    )
    op.drop_column("reviewed_action_revisions", "scheduled_for")
    op.drop_column("reviewed_action_revisions", "delivery")
