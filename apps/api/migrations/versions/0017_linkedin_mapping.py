"""Map professional profile evidence and immutable contact export observations.

Revision ID: 0017_linkedin_mapping
Revises: 0016_agent_questions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_linkedin_mapping"
down_revision: str | None = "0016_agent_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASE_FIELDS = (
    "'full_name', 'email', 'phone', 'location', 'headline', 'website', 'linkedin', "
    "'summary', 'skill', 'experience', 'education', 'answer'"
)
CAREER_FIELDS = "'certification', 'project', 'course', 'language', 'publication', 'recommendation'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_profile_facts_field"), "profile_facts", type_="check")
    op.create_check_constraint(
        op.f("ck_profile_facts_field"),
        "profile_facts",
        f"field IN ({BASE_FIELDS}, {CAREER_FIELDS})",
    )
    op.create_table(
        "contact_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("mapping_version", sa.String(100), nullable=False),
        *[
            sa.Column(name, sa.Text(), nullable=False)
            for name in (
                "first_name",
                "last_name",
                "linkedin_url",
                "email",
                "company",
                "position",
                "connected_on",
            )
        ],
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["actors.id"]),
        sa.ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
        sa.ForeignKeyConstraint(
            ["source_artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "source_artifact_id"],
            ["artifact_versions.id", "artifact_versions.artifact_id"],
        ),
        sa.UniqueConstraint("source_version_id", "source_row"),
        sa.CheckConstraint("source_row > 0", name="source_row"),
    )
    op.create_index("ix_contact_observations_owner_id", "contact_observations", ["owner_id"])
    op.create_index("ix_contact_observations_contact_id", "contact_observations", ["contact_id"])
    op.execute(
        "CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON contact_observations "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()"
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            f"SELECT EXISTS (SELECT 1 FROM contact_observations) OR EXISTS "
            f"(SELECT 1 FROM profile_facts WHERE field IN ({CAREER_FIELDS}))"
        )
    ).scalar_one():
        raise RuntimeError(
            "Cannot downgrade LinkedIn mapping with imported evidence; preserve provenance"
        )
    op.drop_constraint(op.f("ck_profile_facts_field"), "profile_facts", type_="check")
    op.create_check_constraint(
        op.f("ck_profile_facts_field"), "profile_facts", f"field IN ({BASE_FIELDS})"
    )
    op.drop_table("contact_observations")
