"""Keep quick connection notes distinct from full contact research."""

import sqlalchemy as sa
from alembic import op

revision = "0029_connection_notes"
down_revision = "0028_standalone_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "record_work",
        sa.Column("connection_note", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM record_work WHERE connection_note)"))
        .scalar_one()
    ):
        raise RuntimeError("Cannot discard connection note limits; preserve the request contract")
    op.drop_column("record_work", "connection_note")
