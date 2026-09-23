"""Persist compacted conversation prefixes and visible answer reuse provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_chat_context"
down_revision = "0030_mcp_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_sessions", sa.Column("context_summary", postgresql.JSONB(), nullable=True))
    op.add_column("agent_messages", sa.Column("answer_cache", postgresql.JSONB(), nullable=True))
    op.create_index(
        "ix_agent_sessions_owner_activity", "agent_sessions", ["owner_id", "updated_at", "id"]
    )


def downgrade() -> None:
    populated = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM agent_sessions WHERE context_summary IS NOT NULL) "
                "OR EXISTS (SELECT 1 FROM agent_messages WHERE answer_cache IS NOT NULL)"
            )
        )
        .scalar_one()
    )
    if populated:
        raise RuntimeError("Preserve compacted context and answer provenance before downgrade")
    op.drop_index("ix_agent_sessions_owner_activity", table_name="agent_sessions")
    op.drop_column("agent_messages", "answer_cache")
    op.drop_column("agent_sessions", "context_summary")
