"""Persistent owner-scoped Spaces with canonical record memberships."""

import sqlalchemy as sa
from alembic import op

revision = "0038_spaces"
down_revision = "0037_task_waiting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("purpose", sa.Text()),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "owner_id"),
        sa.CheckConstraint("state IN ('active', 'archived')", name="state"),
        sa.CheckConstraint("(state = 'archived') = (archived_at IS NOT NULL)", name="archive"),
        sa.CheckConstraint("row_version >= 1", name="row_version"),
        sa.CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
    )
    for field in ("owner_id", "state"):
        op.create_index(f"ix_spaces_{field}", "spaces", [field])
    targets = {
        "task": "tasks",
        "artifact": "artifacts",
        "contact": "contacts",
        "company": "companies",
        "opportunity": "opportunities",
    }
    op.create_table(
        "space_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("actors.id"), nullable=False),
        *(sa.Column(f"{kind}_id", sa.Uuid()) for kind in targets),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["space_id", "owner_id"], ["spaces.id", "spaces.owner_id"]),
        *(
            sa.ForeignKeyConstraint(
                [f"{kind}_id", "owner_id"], [f"{table}.id", f"{table}.owner_id"]
            )
            for kind, table in targets.items()
        ),
        *(
            sa.UniqueConstraint("space_id", f"{kind}_id", name=f"uq_space_links_space_{kind}")
            for kind in targets
        ),
        sa.CheckConstraint(
            "num_nonnulls(task_id, artifact_id, contact_id, company_id, opportunity_id) = 1",
            name="one_record",
        ),
    )
    for field in ("space_id", "owner_id", *(f"{kind}_id" for kind in targets)):
        op.create_index(f"ix_space_links_{field}", "space_links", [field])
    op.execute("ALTER TABLE spaces ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE space_links ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM spaces)")):
        raise RuntimeError("Cannot downgrade while Spaces exist; preserve their work context")
    op.drop_table("space_links")
    op.drop_table("spaces")
