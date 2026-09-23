"""Pin source versions and generated documents to each application request."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026_application_materials"
down_revision = "0025_application_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_materials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "job_version_id", sa.Uuid(), sa.ForeignKey("artifact_versions.id"), nullable=False
        ),
        sa.Column(
            "resume_version_id", sa.Uuid(), sa.ForeignKey("artifact_versions.id"), nullable=False
        ),
        sa.Column(
            "resume_text_version_id",
            sa.Uuid(),
            sa.ForeignKey("artifact_versions.id"),
            nullable=False,
        ),
        sa.Column("fact_revision_ids", postgresql.JSONB(), nullable=False),
        sa.Column("used_fact_revision_ids", postgresql.JSONB(), nullable=False),
        sa.Column("output_artifact_id", sa.Uuid()),
        sa.Column("output_version_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        sa.ForeignKeyConstraint(["run_id", "owner_id"], ["agent_runs.id", "agent_runs.owner_id"]),
        sa.ForeignKeyConstraint(
            ["output_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        sa.ForeignKeyConstraint(
            ["output_version_id", "output_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        sa.CheckConstraint("kind IN ('resume', 'cover-letter')", name="kind"),
        sa.CheckConstraint(
            "(output_artifact_id IS NULL) = (output_version_id IS NULL)", name="output"
        ),
    )
    for field in ("owner_id", "task_id"):
        op.create_index(f"ix_application_materials_{field}", "application_materials", [field])
    op.execute("ALTER TABLE application_materials ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM application_materials LIMIT 1")).first():
        raise RuntimeError("Application documents exist; preserve their request and source history")
    op.drop_table("application_materials")
