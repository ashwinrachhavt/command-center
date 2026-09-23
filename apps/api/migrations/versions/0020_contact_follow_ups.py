"""Link follow-up message artifacts to their contact.

Revision ID: 0020_contact_follow_ups
Revises: 0019_writing_recovery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_contact_follow_ups"
down_revision: str | None = "0019_writing_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follow_ups",
        sa.Column("artifact_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        sa.ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
    )
    op.create_index("ix_follow_ups_owner_id", "follow_ups", ["owner_id"])
    op.create_index("ix_follow_ups_contact_id", "follow_ups", ["contact_id"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM follow_ups)")).scalar_one():
        raise RuntimeError("Cannot downgrade while follow-ups exist; preserve correspondence")
    op.drop_table("follow_ups")
