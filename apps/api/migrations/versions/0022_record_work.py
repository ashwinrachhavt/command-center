"""Attach company research and follow-up work to canonical tasks and exact outputs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_record_work"
down_revision: str | None = "0021_contact_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "record_work",
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("output_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("output_version_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        sa.ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
        sa.ForeignKeyConstraint(["company_id", "owner_id"], ["companies.id", "companies.owner_id"]),
        sa.ForeignKeyConstraint(
            ["output_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        sa.ForeignKeyConstraint(
            ["output_version_id", "output_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        sa.CheckConstraint("num_nonnulls(contact_id, company_id) = 1", name="target"),
        sa.CheckConstraint("channel IN ('linkedin', 'email')", name="channel"),
        sa.CheckConstraint(
            "(output_artifact_id IS NULL) = (output_version_id IS NULL)", name="output"
        ),
    )
    for field in ("owner_id", "contact_id", "company_id"):
        op.create_index(f"ix_record_work_{field}", "record_work", [field])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM record_work)")).scalar_one():
        raise RuntimeError("Cannot downgrade while record work exists; preserve task context")
    op.drop_table("record_work")
