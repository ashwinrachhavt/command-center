"""Pin whether contact work requires a researched draft."""

import sqlalchemy as sa
from alembic import op

revision = "0027_contact_research"
down_revision = "0026_application_materials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "record_work",
        sa.Column("research_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM record_work WHERE research_requested)"))
        .scalar_one()
    ):
        raise RuntimeError("Cannot discard researched contact work; preserve the request contract")
    op.drop_column("record_work", "research_requested")
