"""Bounded periodic recovery copies for working drafts.

Revision ID: 0019_writing_recovery
Revises: 0018_writing_drafts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_writing_recovery"
down_revision: str | None = "0018_writing_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "writing_recovery_copies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["writing_drafts.id"]),
        sa.UniqueConstraint("draft_id", "row_version"),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM writing_recovery_copies)"))
        .scalar_one()
    ):
        raise RuntimeError("Cannot downgrade while recovery copies exist; preserve writing")
    op.drop_table("writing_recovery_copies")
