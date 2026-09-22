"""durable document imports and exact default resume

Revision ID: 0006_documents
Revises: 0005_job_leads
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_documents"
down_revision: str | None = "0005_job_leads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("default_resume_version_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_candidate_profiles_default_resume_version_id_artifact_versions"),
        "candidate_profiles",
        "artifact_versions",
        ["default_resume_version_id"],
        ["id"],
    )
    op.create_table(
        "document_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("extraction_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("extraction_version_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_document_imports_state"),
        ),
        sa.CheckConstraint(
            "byte_size BETWEEN 1 AND 20971520",
            name=op.f("ck_document_imports_byte_size"),
        ),
        sa.CheckConstraint("row_version >= 1", name=op.f("ck_document_imports_row_version")),
        sa.CheckConstraint(
            "(state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_document_imports_lease_state"),
        ),
        sa.CheckConstraint(
            "(state = 'completed') = "
            "(extraction_artifact_id IS NOT NULL AND extraction_version_id IS NOT NULL)",
            name=op.f("ck_document_imports_output_state"),
        ),
        sa.CheckConstraint(
            "error IS NULL OR state = 'failed'", name=op.f("ck_document_imports_error_state")
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_document_imports_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["extraction_artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_document_imports_extraction_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["extraction_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_document_imports_extraction_version_id_artifact_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_document_imports_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_document_imports_source_version_id_artifact_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_document_imports_task_id_tasks")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_imports")),
        sa.UniqueConstraint(
            "source_version_id", name=op.f("uq_document_imports_source_version_id")
        ),
        sa.UniqueConstraint("task_id", name=op.f("uq_document_imports_task_id")),
    )
    op.create_index(
        op.f("ix_document_imports_artifact_id"),
        "document_imports",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_imports_owner_id"), "document_imports", ["owner_id"], unique=False
    )
    op.create_index(op.f("ix_document_imports_state"), "document_imports", ["state"], unique=False)
    op.execute("ALTER TABLE document_imports ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE document_imports DISABLE ROW LEVEL SECURITY")
    op.drop_index(op.f("ix_document_imports_state"), table_name="document_imports")
    op.drop_index(op.f("ix_document_imports_owner_id"), table_name="document_imports")
    op.drop_index(op.f("ix_document_imports_artifact_id"), table_name="document_imports")
    op.drop_table("document_imports")
    op.drop_constraint(
        op.f("fk_candidate_profiles_default_resume_version_id_artifact_versions"),
        "candidate_profiles",
        type_="foreignkey",
    )
    op.drop_column("candidate_profiles", "default_resume_version_id")
