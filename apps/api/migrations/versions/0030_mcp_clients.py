"""Actor-bound, individually revocable local MCP credentials."""

import sqlalchemy as sa
from alembic import op

revision = "0030_mcp_clients"
down_revision = "0029_connection_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_client_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_mcp_client_credentials_owner_id", "mcp_client_credentials", ["owner_id"])


def downgrade() -> None:
    op.drop_table("mcp_client_credentials")
