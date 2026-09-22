"""isolated research execution and selected-version PDF derivatives

Revision ID: 0013_research_documents
Revises: 0012_reviewed_actions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_research_documents"
down_revision: str | None = "0012_reviewed_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _job_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name=op.f(f"ck_{prefix}_state"),
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 2", name=op.f(f"ck_{prefix}_attempt_count")
        ),
        sa.CheckConstraint("max_attempts = 2", name=op.f(f"ck_{prefix}_max_attempts")),
        sa.CheckConstraint("row_version >= 1", name=op.f(f"ck_{prefix}_row_version")),
        sa.CheckConstraint(
            "(state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name=op.f(f"ck_{prefix}_lease_state"),
        ),
        sa.CheckConstraint(
            "(state = 'completed') = "
            "(output_artifact_id IS NOT NULL AND output_version_id IS NOT NULL)",
            name=op.f(f"ck_{prefix}_output_state"),
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR state = 'failed'", name=op.f(f"ck_{prefix}_error_state")
        ),
    ]


def upgrade() -> None:
    op.create_unique_constraint("uq_artifacts_id_owner_id", "artifacts", ["id", "owner_id"])
    op.create_unique_constraint(
        "uq_artifact_versions_id_artifact_id", "artifact_versions", ["id", "artifact_id"]
    )
    op.create_table(
        "research_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("script_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("script_version_id", sa.Uuid(), nullable=False),
        sa.Column("output_title", sa.String(length=300), nullable=False),
        sa.Column("document_type_id", sa.Uuid(), nullable=False),
        sa.Column("output_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("output_version_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("container_lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_job_constraints("research_executions"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_research_executions_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name=op.f("fk_research_executions_document_type_id_document_types"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "owner_id"],
            ["tasks.id", "tasks.owner_id"],
            name="fk_research_executions_task_owner",
        ),
        sa.ForeignKeyConstraint(
            ["script_artifact_id", "owner_id"],
            ["artifacts.id", "artifacts.owner_id"],
            name="fk_research_executions_script_owner",
        ),
        sa.ForeignKeyConstraint(
            ["script_version_id", "script_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
            name="fk_research_executions_script_version",
        ),
        sa.ForeignKeyConstraint(
            ["output_artifact_id", "owner_id"],
            ["artifacts.id", "artifacts.owner_id"],
            name="fk_research_executions_output_owner",
        ),
        sa.ForeignKeyConstraint(
            ["output_version_id", "output_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
            name="fk_research_executions_output_version",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_executions")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_research_executions_id")),
        sa.UniqueConstraint(
            "script_version_id", name=op.f("uq_research_executions_script_version_id")
        ),
    )
    for column in ("owner_id", "task_id", "state"):
        op.create_index(
            op.f(f"ix_research_executions_{column}"), "research_executions", [column], unique=False
        )
    op.create_table(
        "research_execution_inputs",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "role IN ('material', 'public_source')", name=op.f("ck_research_execution_inputs_role")
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "owner_id"],
            ["research_executions.id", "research_executions.owner_id"],
            name="fk_research_execution_inputs_execution_owner",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "owner_id"],
            ["artifacts.id", "artifacts.owner_id"],
            name="fk_research_execution_inputs_artifact_owner",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
            name="fk_research_execution_inputs_version_artifact",
        ),
        sa.PrimaryKeyConstraint(
            "execution_id", "version_id", name=op.f("pk_research_execution_inputs")
        ),
    )
    op.create_table(
        "pdf_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("output_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("output_version_id", sa.Uuid(), nullable=True),
        sa.Column("renderer_revision", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("container_lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_job_constraints("pdf_exports"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_pdf_exports_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "owner_id"],
            ["tasks.id", "tasks.owner_id"],
            name="fk_pdf_exports_task_owner",
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id", "owner_id"],
            ["artifacts.id", "artifacts.owner_id"],
            name="fk_pdf_exports_source_owner",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "source_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
            name="fk_pdf_exports_source_version",
        ),
        sa.ForeignKeyConstraint(
            ["output_artifact_id", "owner_id"],
            ["artifacts.id", "artifacts.owner_id"],
            name="fk_pdf_exports_output_owner",
        ),
        sa.ForeignKeyConstraint(
            ["output_version_id", "output_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
            name="fk_pdf_exports_output_version",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_exports")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_pdf_exports_id")),
    )
    for column in ("owner_id", "task_id", "source_version_id", "state"):
        op.create_index(op.f(f"ix_pdf_exports_{column}"), "pdf_exports", [column], unique=False)
    op.create_index(
        "uq_pdf_exports_active_source_renderer",
        "pdf_exports",
        ["owner_id", "source_version_id", "renderer_revision"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running')"),
    )
    for table in ("research_executions", "research_execution_inputs", "pdf_exports"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ("pdf_exports", "research_execution_inputs", "research_executions"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("uq_pdf_exports_active_source_renderer", table_name="pdf_exports")
    for column in ("state", "source_version_id", "task_id", "owner_id"):
        op.drop_index(op.f(f"ix_pdf_exports_{column}"), table_name="pdf_exports")
    op.drop_table("pdf_exports")
    op.drop_table("research_execution_inputs")
    for column in ("state", "task_id", "owner_id"):
        op.drop_index(op.f(f"ix_research_executions_{column}"), table_name="research_executions")
    op.drop_table("research_executions")
    op.drop_constraint("uq_artifact_versions_id_artifact_id", "artifact_versions", type_="unique")
    op.drop_constraint("uq_artifacts_id_owner_id", "artifacts", type_="unique")
