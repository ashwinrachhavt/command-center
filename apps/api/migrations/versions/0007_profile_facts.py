"""reviewed candidate profile facts

Revision ID: 0007_profile_facts
Revises: 0006_documents
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_profile_facts"
down_revision: str | None = "0006_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("active_revision_id", sa.Uuid(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "field IN ('full_name', 'email', 'phone', 'location', 'headline', 'website', "
            "'linkedin', 'summary', 'skill', 'experience', 'education', 'answer')",
            name=op.f("ck_profile_facts_field"),
        ),
        sa.CheckConstraint("row_version >= 1", name=op.f("ck_profile_facts_row_version")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_profile_facts_owner_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_facts")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_profile_facts_id")),
    )
    op.create_index(op.f("ix_profile_facts_field"), "profile_facts", ["field"], unique=False)
    op.create_index(op.f("ix_profile_facts_owner_id"), "profile_facts", ["owner_id"], unique=False)
    op.create_index(
        "uq_profile_facts_active_scalar",
        "profile_facts",
        ["owner_id", "field"],
        unique=True,
        postgresql_where=sa.text(
            "active_revision_id IS NOT NULL AND field IN "
            "('full_name', 'email', 'phone', 'location', 'headline', 'website', "
            "'linkedin', 'summary')"
        ),
    )
    op.create_table(
        "profile_fact_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_profile_fact_revisions_version")),
        sa.CheckConstraint(
            "length(value) BETWEEN 1 AND 4000",
            name=op.f("ck_profile_fact_revisions_value_length"),
        ),
        sa.CheckConstraint(
            "context IS NULL OR length(context) <= 1000",
            name=op.f("ck_profile_fact_revisions_context_length"),
        ),
        sa.CheckConstraint(
            "source_excerpt IS NULL OR length(source_excerpt) BETWEEN 1 AND 4000",
            name=op.f("ck_profile_fact_revisions_excerpt_length"),
        ),
        sa.CheckConstraint(
            "source_excerpt IS NULL OR source_version_id IS NOT NULL",
            name=op.f("ck_profile_fact_revisions_excerpt_source"),
        ),
        sa.ForeignKeyConstraint(
            ["fact_id"],
            ["profile_facts.id"],
            name=op.f("fk_profile_fact_revisions_fact_id_profile_facts"),
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_profile_fact_revisions_source_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_profile_fact_revisions_source_version_id_artifact_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_fact_revisions")),
        sa.UniqueConstraint("fact_id", "version", name=op.f("uq_profile_fact_revisions_fact_id")),
        sa.UniqueConstraint("id", "fact_id", name=op.f("uq_profile_fact_revisions_id")),
    )
    op.create_index(
        op.f("ix_profile_fact_revisions_fact_id"),
        "profile_fact_revisions",
        ["fact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_profile_fact_revisions_source_version_id"),
        "profile_fact_revisions",
        ["source_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_profile_fact_revisions_valid_until"),
        "profile_fact_revisions",
        ["valid_until"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_profile_facts_current_revision",
        "profile_facts",
        "profile_fact_revisions",
        ["current_revision_id", "id"],
        ["id", "fact_id"],
    )
    op.create_foreign_key(
        "fk_profile_facts_active_revision",
        "profile_facts",
        "profile_fact_revisions",
        ["active_revision_id", "id"],
        ["id", "fact_id"],
    )
    op.create_table(
        "profile_fact_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'revoked')",
            name=op.f("ck_profile_fact_reviews_decision"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(reason) <= 2000",
            name=op.f("ck_profile_fact_reviews_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["fact_id"],
            ["profile_facts.id"],
            name=op.f("fk_profile_fact_reviews_fact_id_profile_facts"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["actors.id"],
            name=op.f("fk_profile_fact_reviews_reviewer_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "fact_id"],
            ["profile_fact_revisions.id", "profile_fact_revisions.fact_id"],
            name=op.f("fk_profile_fact_reviews_revision_id_profile_fact_revisions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_fact_reviews")),
    )
    op.create_index(
        op.f("ix_profile_fact_reviews_fact_id"),
        "profile_fact_reviews",
        ["fact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_profile_fact_reviews_revision_id"),
        "profile_fact_reviews",
        ["revision_id"],
        unique=False,
    )
    for table in ("profile_fact_revisions", "profile_fact_reviews"):
        op.execute(
            f"CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()"
        )


def downgrade() -> None:
    for table in ("profile_fact_reviews", "profile_fact_revisions"):
        op.execute(f"DROP TRIGGER immutable_rows ON {table}")
    op.drop_table("profile_fact_reviews")
    op.drop_constraint("fk_profile_facts_active_revision", "profile_facts", type_="foreignkey")
    op.drop_constraint("fk_profile_facts_current_revision", "profile_facts", type_="foreignkey")
    op.drop_table("profile_fact_revisions")
    op.drop_table("profile_facts")
