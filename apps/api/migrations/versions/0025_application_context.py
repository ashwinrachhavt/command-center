"""Attach versioned job requirements to the canonical application task."""

import sqlalchemy as sa
from alembic import op

revision = "0025_application_context"
down_revision = "0024_application_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("application_tracks", sa.Column("job_context_artifact_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_application_tracks_job_context_artifact_id_artifacts",
        "application_tracks",
        "artifacts",
        ["job_context_artifact_id", "owner_id"],
        ["id", "owner_id"],
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM application_tracks WHERE job_context_artifact_id IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Application job descriptions exist; refusing to discard their links.")
    op.drop_constraint(
        "fk_application_tracks_job_context_artifact_id_artifacts",
        "application_tracks",
        type_="foreignkey",
    )
    op.drop_column("application_tracks", "job_context_artifact_id")
