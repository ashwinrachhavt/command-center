"""Allow durable standalone chats alongside task and opportunity conversations."""

import sqlalchemy as sa
from alembic import op

revision = "0028_standalone_conversations"
down_revision = "0027_contact_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_agent_sessions_one_scope"), "agent_sessions", type_="check")
    op.create_check_constraint(
        "one_scope", "agent_sessions", "num_nonnulls(task_id, opportunity_id) <= 1"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM agent_sessions "
                "WHERE task_id IS NULL AND opportunity_id IS NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Cannot discard standalone conversations; preserve chat history")
    op.drop_constraint(op.f("ck_agent_sessions_one_scope"), "agent_sessions", type_="check")
    op.create_check_constraint(
        "one_scope", "agent_sessions", "(task_id IS NOT NULL) <> (opportunity_id IS NOT NULL)"
    )
