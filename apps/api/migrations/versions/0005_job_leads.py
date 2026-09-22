"""link immutable source acquisitions to opportunities

Revision ID: 0005_job_leads
Revises: 0004_conversations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_job_leads"
down_revision: str | None = "0004_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_records", sa.Column("opportunity_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_source_records_opportunity_id"),
        "source_records",
        ["opportunity_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_source_records_opportunity_id_opportunities"),
        "source_records",
        "opportunities",
        ["opportunity_id"],
        ["id"],
    )
    op.execute(
        "CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON source_records "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER immutable_rows ON source_records")
    op.drop_constraint(
        op.f("fk_source_records_opportunity_id_opportunities"),
        "source_records",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_source_records_opportunity_id"), table_name="source_records")
    op.drop_column("source_records", "opportunity_id")
