"""browser protocol v2 and exact resume upload commands

Revision ID: 0008_browser_assistance
Revises: 0007_profile_facts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_browser_assistance"
down_revision: str | None = "0007_profile_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_snapshots",
        sa.Column("protocol_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_browser_snapshots_protocol_version"),
        "browser_snapshots",
        "protocol_version IN (1, 2)",
    )
    op.create_unique_constraint(
        "uq_browser_snapshots_id_owner", "browser_snapshots", ["id", "owner_id"]
    )

    op.drop_constraint(op.f("ck_browser_commands_state"), "browser_commands", type_="check")
    op.create_check_constraint(
        op.f("ck_browser_commands_state"),
        "browser_commands",
        "state IN ('pending', 'claimed', 'applied', 'partial', 'rejected', 'failed', "
        "'outcome_unknown')",
    )
    op.add_column(
        "browser_commands",
        sa.Column(
            "uploads",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "browser_commands",
        sa.Column(
            "replace_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("browser_commands", sa.Column("preparation_version_id", sa.Uuid(), nullable=True))
    op.add_column(
        "browser_commands",
        sa.Column(
            "upload_files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "browser_commands",
        sa.Column(
            "field_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        op.f("fk_browser_commands_preparation_version_id_artifact_versions"),
        "browser_commands",
        "artifact_versions",
        ["preparation_version_id"],
        ["id"],
    )
    for name, expression in (
        ("uploads_object", "jsonb_typeof(uploads) = 'object'"),
        ("replace_fields_array", "jsonb_typeof(replace_fields) = 'array'"),
        ("upload_files_object", "jsonb_typeof(upload_files) = 'object'"),
        ("field_results_object", "jsonb_typeof(field_results) = 'object'"),
    ):
        op.create_check_constraint(
            op.f(f"ck_browser_commands_{name}"), "browser_commands", expression
        )
    op.alter_column("browser_snapshots", "protocol_version", server_default=None)
    for column in ("uploads", "replace_fields", "upload_files", "field_results"):
        op.alter_column("browser_commands", column, server_default=None)


def downgrade() -> None:
    # The old protocol cannot represent a partially applied command. Preserve
    # uncertainty and prevent a downgraded client from treating it as complete.
    op.execute("UPDATE browser_commands SET state = 'outcome_unknown' WHERE state = 'partial'")
    for name in (
        "field_results_object",
        "upload_files_object",
        "replace_fields_array",
        "uploads_object",
    ):
        op.drop_constraint(op.f(f"ck_browser_commands_{name}"), "browser_commands", type_="check")
    op.drop_constraint(
        op.f("fk_browser_commands_preparation_version_id_artifact_versions"),
        "browser_commands",
        type_="foreignkey",
    )
    op.drop_column("browser_commands", "field_results")
    op.drop_column("browser_commands", "upload_files")
    op.drop_column("browser_commands", "preparation_version_id")
    op.drop_column("browser_commands", "replace_fields")
    op.drop_column("browser_commands", "uploads")
    op.drop_constraint(op.f("ck_browser_commands_state"), "browser_commands", type_="check")
    op.create_check_constraint(
        op.f("ck_browser_commands_state"),
        "browser_commands",
        "state IN ('pending', 'claimed', 'applied', 'rejected', 'failed', 'outcome_unknown')",
    )
    op.drop_constraint(
        op.f("ck_browser_snapshots_protocol_version"), "browser_snapshots", type_="check"
    )
    op.drop_constraint("uq_browser_snapshots_id_owner", "browser_snapshots", type_="unique")
    op.drop_column("browser_snapshots", "protocol_version")
