"""durable work conversations

Revision ID: 0004_conversations
Revises: 0003_memory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_conversations"
down_revision: str | None = "0003_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_tasks_id"), "tasks", ["id", "owner_id"])
    op.create_table(
        "agent_sessions",
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("last_sequence >= 0", name=op.f("ck_agent_sessions_last_sequence")),
        sa.CheckConstraint(
            "(task_id IS NOT NULL) <> (opportunity_id IS NOT NULL)",
            name=op.f("ck_agent_sessions_one_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id", "owner_id"],
            ["opportunities.id", "opportunities.owner_id"],
            name=op.f("fk_agent_sessions_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_agent_sessions_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "owner_id"],
            ["tasks.id", "tasks.owner_id"],
            name=op.f("fk_agent_sessions_task_id_tasks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_sessions")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_agent_sessions_id")),
    )
    op.create_index(
        op.f("ix_agent_sessions_opportunity_id"),
        "agent_sessions",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_sessions_owner_id"), "agent_sessions", ["owner_id"], unique=False
    )
    op.create_index(op.f("ix_agent_sessions_task_id"), "agent_sessions", ["task_id"], unique=False)
    op.create_index(
        "uq_agent_sessions_owner_opportunity",
        "agent_sessions",
        ["owner_id", "opportunity_id"],
        unique=True,
        postgresql_where=sa.text("opportunity_id IS NOT NULL"),
    )
    op.create_index(
        "uq_agent_sessions_owner_task",
        "agent_sessions",
        ["owner_id", "task_id"],
        unique=True,
        postgresql_where=sa.text("task_id IS NOT NULL"),
    )

    op.add_column("agent_runs", sa.Column("session_id", sa.Uuid(), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("input_sequence", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column("consumed_sequence", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_agent_runs_input_sequence"), "agent_runs", "input_sequence >= 0"
    )
    op.create_check_constraint(
        op.f("ck_agent_runs_consumed_sequence"), "agent_runs", "consumed_sequence >= 0"
    )
    op.create_unique_constraint(op.f("uq_agent_runs_id"), "agent_runs", ["id", "owner_id"])
    op.create_foreign_key(
        op.f("fk_agent_runs_session_id_agent_sessions"),
        "agent_runs",
        "agent_sessions",
        ["session_id", "owner_id"],
        ["id", "owner_id"],
    )
    op.create_index(op.f("ix_agent_runs_session_id"), "agent_runs", ["session_id"], unique=False)
    op.create_index(
        "uq_agent_runs_active_session",
        "agent_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL AND state IN ('queued', 'running')"),
    )

    op.create_table(
        "agent_messages",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(length=20), nullable=False),
        sa.Column("profile", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "author IN ('user', 'assistant')", name=op.f("ck_agent_messages_author")
        ),
        sa.CheckConstraint("length(trim(content)) > 0", name=op.f("ck_agent_messages_content")),
        sa.CheckConstraint("length(trim(profile)) > 0", name=op.f("ck_agent_messages_profile")),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_agent_messages_sequence")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_agent_messages_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name=op.f("fk_agent_messages_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["agent_sessions.id", "agent_sessions.owner_id"],
            name=op.f("fk_agent_messages_session_id_agent_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_messages")),
        sa.UniqueConstraint("session_id", "sequence", name=op.f("uq_agent_messages_session_id")),
    )
    op.create_index(
        op.f("ix_agent_messages_owner_id"), "agent_messages", ["owner_id"], unique=False
    )
    op.create_index(op.f("ix_agent_messages_run_id"), "agent_messages", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_agent_messages_session_id"), "agent_messages", ["session_id"], unique=False
    )

    op.execute("ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE SCHEMA IF NOT EXISTS agent_checkpoints")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS agent_checkpoints CASCADE")
    op.drop_index(op.f("ix_agent_messages_session_id"), table_name="agent_messages")
    op.drop_index(op.f("ix_agent_messages_run_id"), table_name="agent_messages")
    op.drop_index(op.f("ix_agent_messages_owner_id"), table_name="agent_messages")
    op.drop_table("agent_messages")

    op.drop_index("uq_agent_runs_active_session", table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_session_id"), table_name="agent_runs")
    op.drop_constraint(
        op.f("fk_agent_runs_session_id_agent_sessions"), "agent_runs", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_agent_runs_id"), "agent_runs", type_="unique")
    op.drop_constraint(op.f("ck_agent_runs_consumed_sequence"), "agent_runs", type_="check")
    op.drop_constraint(op.f("ck_agent_runs_input_sequence"), "agent_runs", type_="check")
    op.drop_column("agent_runs", "consumed_sequence")
    op.drop_column("agent_runs", "input_sequence")
    op.drop_column("agent_runs", "session_id")

    op.drop_index("uq_agent_sessions_owner_task", table_name="agent_sessions")
    op.drop_index("uq_agent_sessions_owner_opportunity", table_name="agent_sessions")
    op.drop_index(op.f("ix_agent_sessions_task_id"), table_name="agent_sessions")
    op.drop_index(op.f("ix_agent_sessions_owner_id"), table_name="agent_sessions")
    op.drop_index(op.f("ix_agent_sessions_opportunity_id"), table_name="agent_sessions")
    op.drop_table("agent_sessions")
    op.drop_constraint(op.f("uq_tasks_id"), "tasks", type_="unique")
