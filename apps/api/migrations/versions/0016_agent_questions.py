"""Add durable branch-specific agent questions and resume intents.

Revision ID: 0016_agent_questions
Revises: 0015_connected_context
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_agent_questions"
down_revision: str | None = "0015_connected_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_agent_runs_active_session", table_name="agent_runs")
    op.drop_constraint(op.f("ck_agent_runs_state"), "agent_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_agent_runs_state"),
        "agent_runs",
        "state IN ('queued', 'running', 'waiting_for_user', 'completed', 'failed', 'cancelled')",
    )
    op.create_index(
        "uq_agent_runs_active_session",
        "agent_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(
            "session_id IS NOT NULL AND state IN ('queued', 'running', 'waiting_for_user')"
        ),
    )
    op.create_table(
        "agent_questions",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("interrupt_id", sa.String(length=100), nullable=False),
        sa.Column("branch_id", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("tool_call_id", sa.String(length=200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(state = 'open' AND answer IS NULL AND answered_at IS NULL) OR "
            "(state IN ('answered', 'resumed') AND answer IS NOT NULL AND answered_at IS NOT "
            "NULL) OR state = 'cancelled'",
            name=op.f("ck_agent_questions_answer_state"),
        ),
        sa.CheckConstraint(
            "length(branch_id) BETWEEN 1 AND 100",
            name=op.f("ck_agent_questions_branch_length"),
        ),
        sa.CheckConstraint(
            "length(interrupt_id) BETWEEN 1 AND 100",
            name=op.f("ck_agent_questions_interrupt_length"),
        ),
        sa.CheckConstraint(
            "length(trim(prompt)) BETWEEN 1 AND 10000",
            name=op.f("ck_agent_questions_prompt_length"),
        ),
        sa.CheckConstraint(
            "length(role) BETWEEN 1 AND 100", name=op.f("ck_agent_questions_role_length")
        ),
        sa.CheckConstraint(
            "state IN ('open', 'answered', 'resumed', 'cancelled')",
            name=op.f("ck_agent_questions_state"),
        ),
        sa.CheckConstraint(
            "length(tool_call_id) BETWEEN 1 AND 200",
            name=op.f("ck_agent_questions_tool_call_length"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_agent_questions_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name=op.f("fk_agent_questions_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["agent_sessions.id", "agent_sessions.owner_id"],
            name=op.f("fk_agent_questions_session_id_agent_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_questions")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_agent_questions_id")),
        sa.UniqueConstraint("run_id", "interrupt_id", name=op.f("uq_agent_questions_run_id")),
    )
    op.create_index(
        op.f("ix_agent_questions_owner_id"), "agent_questions", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_agent_questions_session_id"), "agent_questions", ["session_id"], unique=False
    )
    op.create_index(op.f("ix_agent_questions_state"), "agent_questions", ["state"], unique=False)
    op.create_index(
        "ix_agent_questions_owner_run_state",
        "agent_questions",
        ["owner_id", "run_id", "state"],
        unique=False,
    )
    op.create_table(
        "agent_resume_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("interrupt_id", sa.String(length=100), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'applied', 'cancelled')",
            name=op.f("ck_agent_resume_intents_state"),
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "owner_id"],
            ["agent_questions.id", "agent_questions.owner_id"],
            name=op.f("fk_agent_resume_intents_question_id_agent_questions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name=op.f("fk_agent_resume_intents_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_resume_intents")),
        sa.UniqueConstraint("question_id", name=op.f("uq_agent_resume_intents_question_id")),
    )
    op.create_index(
        op.f("ix_agent_resume_intents_state"),
        "agent_resume_intents",
        ["state"],
        unique=False,
    )
    op.create_index(
        "ix_agent_resume_intents_run_state",
        "agent_resume_intents",
        ["run_id", "state"],
        unique=False,
    )


def downgrade() -> None:
    exists = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM agent_questions) "
            "OR EXISTS (SELECT 1 FROM agent_runs WHERE state = 'waiting_for_user')"
        )
    )
    if exists:
        raise RuntimeError(
            "Cannot downgrade while durable agent questions exist; preserve conversation "
            "interrupt provenance and restore from a compatible backup instead"
        )
    op.drop_index("ix_agent_resume_intents_run_state", table_name="agent_resume_intents")
    op.drop_index(op.f("ix_agent_resume_intents_state"), table_name="agent_resume_intents")
    op.drop_table("agent_resume_intents")
    op.drop_index("ix_agent_questions_owner_run_state", table_name="agent_questions")
    op.drop_index(op.f("ix_agent_questions_state"), table_name="agent_questions")
    op.drop_index(op.f("ix_agent_questions_session_id"), table_name="agent_questions")
    op.drop_index(op.f("ix_agent_questions_owner_id"), table_name="agent_questions")
    op.drop_table("agent_questions")
    op.drop_index("uq_agent_runs_active_session", table_name="agent_runs")
    op.drop_constraint(op.f("ck_agent_runs_state"), "agent_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_agent_runs_state"),
        "agent_runs",
        "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
    )
    op.create_index(
        "uq_agent_runs_active_session",
        "agent_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL AND state IN ('queued', 'running')"),
    )
