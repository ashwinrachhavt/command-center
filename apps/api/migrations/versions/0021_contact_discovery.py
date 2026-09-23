"""Preserve Apollo/Hunter evidence when a person is explicitly added to Contacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_contact_discovery"
down_revision: str | None = "0020_contact_follow_ups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_discovery_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(320), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
        sa.ForeignKeyConstraint(
            ["source_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "source_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        sa.UniqueConstraint("owner_id", "provider", "external_id"),
    )
    op.create_index(
        "ix_contact_discovery_evidence_owner_id", "contact_discovery_evidence", ["owner_id"]
    )
    op.create_index(
        "ix_contact_discovery_evidence_contact_id", "contact_discovery_evidence", ["contact_id"]
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM contact_discovery_evidence)"))
        .scalar_one()
    ):
        raise RuntimeError("Cannot downgrade while contact discovery evidence exists")
    op.drop_table("contact_discovery_evidence")
