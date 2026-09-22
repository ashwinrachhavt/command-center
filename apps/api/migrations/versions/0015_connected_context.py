"""Add bounded calendar-list provider observations.

Revision ID: 0015_connected_context
Revises: 0014_spending_controls
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_connected_context"
down_revision: str | None = "0014_spending_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "'gmail_search','calendar_event','linear_issue','notion_page'"
NEW_KINDS = "'gmail_search','calendar_events','calendar_event','linear_issue','notion_page'"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_provider_observations_kind"), "provider_observations", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_provider_observations_kind"),
        "provider_observations",
        f"kind IN ({NEW_KINDS})",
    )


def downgrade() -> None:
    exists = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM provider_observations WHERE kind='calendar_events')")
    )
    if exists:
        raise RuntimeError(
            "Cannot downgrade while calendar_events provider observations exist; "
            "preserve provenance and restore from a compatible backup instead"
        )
    op.drop_constraint(
        op.f("ck_provider_observations_kind"), "provider_observations", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_provider_observations_kind"),
        "provider_observations",
        f"kind IN ({OLD_KINDS})",
    )
