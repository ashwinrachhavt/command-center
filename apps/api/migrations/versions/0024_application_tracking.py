"""Track application progress without inferring submission from an autofill result."""

import sqlalchemy as sa
from alembic import op

revision = "0024_application_tracking"
down_revision = "0023_application_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_tracks",
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("submission_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id", "owner_id"], ["tasks.id", "tasks.owner_id"]),
        sa.CheckConstraint(
            "status IN ('preparing', 'submitted', 'interviewing', 'offer', "
            "'rejected', 'withdrawn')",
            name="status",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version"),
    )
    op.create_index(op.f("ix_application_tracks_owner_id"), "application_tracks", ["owner_id"])
    op.create_index(op.f("ix_application_tracks_status"), "application_tracks", ["status"])
    op.execute("ALTER TABLE application_tracks ENABLE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO application_tracks "
        "(task_id, owner_id, status, row_version, created_at, updated_at) "
        "SELECT task_id, owner_id, 'preparing', 1, min(created_at), max(updated_at) "
        "FROM application_preparations GROUP BY task_id, owner_id"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM application_tracks "
                "WHERE status <> 'preparing' OR submission_recorded_at IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Application progress exists; refusing to discard recorded outcomes.")
    op.drop_table("application_tracks")
