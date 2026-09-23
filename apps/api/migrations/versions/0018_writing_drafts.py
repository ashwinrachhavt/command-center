"""Recoverable autosaved writing, separate from immutable approved versions.

Revision ID: 0018_writing_drafts
Revises: 0017_linkedin_mapping
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_writing_drafts"
down_revision: str | None = "0017_linkedin_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "writing_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("data", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("last_save_key", sa.Uuid(), nullable=True),
        sa.Column("last_save_hash", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["actors.id"]),
        sa.UniqueConstraint("owner_id", "scope_key"),
        sa.CheckConstraint("row_version >= 0", name="row_version"),
        sa.CheckConstraint("length(scope_key) BETWEEN 1 AND 200", name="scope_key"),
    )
    op.create_index("ix_writing_drafts_owner_id", "writing_drafts", ["owner_id"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM writing_drafts)")).scalar_one():
        raise RuntimeError("Cannot downgrade while saved draft revisions exist; preserve writing")
    op.drop_table("writing_drafts")
