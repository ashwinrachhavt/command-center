"""Reviewed connected actions and exact provider receipts.

Revision ID: 0012_reviewed_actions
Revises: 0011_reviewed_memory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_reviewed_actions"
down_revision: str | None = "0011_reviewed_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def owned_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "external_accounts",
        *owned_columns(),
        sa.Column("toolkit", sa.String(length=30), nullable=False),
        sa.Column("composio_connected_account_id", sa.String(length=200), nullable=False),
        sa.Column("composio_auth_config_id", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("provider_identity", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("connection_status", sa.String(length=20), nullable=False),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("identity_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selected_purpose", sa.String(length=50), nullable=True),
        sa.CheckConstraint(
            "toolkit IN ('gmail', 'googlecalendar', 'linear', 'notion')",
            name=op.f("ck_external_accounts_toolkit"),
        ),
        sa.CheckConstraint(
            "connection_status IN ('ACTIVE', 'INACTIVE', 'EXPIRED', 'REVOKED', 'FAILED')",
            name=op.f("ck_external_accounts_connection_status"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_external_accounts_owner_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_accounts")),
        sa.UniqueConstraint(
            "owner_id",
            "composio_connected_account_id",
            name=op.f("uq_external_accounts_owner_id"),
        ),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_external_accounts_id")),
    )
    op.create_index(op.f("ix_external_accounts_owner_id"), "external_accounts", ["owner_id"])
    op.create_index(op.f("ix_external_accounts_toolkit"), "external_accounts", ["toolkit"])
    op.create_index(
        "uq_external_accounts_selected_purpose",
        "external_accounts",
        ["owner_id", "selected_purpose"],
        unique=True,
        postgresql_where=sa.text("selected_purpose IS NOT NULL"),
    )

    op.create_table(
        "reviewed_actions",
        *owned_columns(),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("approved_revision_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.CheckConstraint(
            "kind IN ('gmail_send','calendar_create','calendar_update','linear_create',"
            "'linear_update','notion_publish','notion_update')",
            name=op.f("ck_reviewed_actions_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('proposed','queued','running','succeeded','failed','outcome_unknown',"
            "'partial','conflicted','rejected','revoked')",
            name=op.f("ck_reviewed_actions_state"),
        ),
        sa.CheckConstraint("row_version >= 1", name=op.f("ck_reviewed_actions_row_version")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_reviewed_actions_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "owner_id"],
            ["external_accounts.id", "external_accounts.owner_id"],
            name=op.f("fk_reviewed_actions_account_id_external_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_reviewed_actions_task_id_tasks")
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_reviewed_actions_opportunity_id_opportunities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviewed_actions")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_reviewed_actions_id")),
    )
    for column in ("owner_id", "kind", "account_id", "task_id", "opportunity_id", "state"):
        op.create_index(op.f(f"ix_reviewed_actions_{column}"), "reviewed_actions", [column])

    op.create_table(
        "reviewed_action_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tool_slug", sa.String(length=100), nullable=False),
        sa.Column("toolkit_version", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("expected_remote_revision", sa.String(length=500), nullable=True),
        sa.Column("observed_target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposed_by_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_reviewed_action_revisions_version")),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_reviewed_action_revisions_payload_hash"),
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 1 AND 2000",
            name=op.f("ck_reviewed_action_revisions_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["reviewed_actions.id"],
            name=op.f("fk_reviewed_action_revisions_action_id_reviewed_actions"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_reviewed_action_revisions_source_version_id_artifact_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_reviewed_action_revisions_source_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_id"],
            ["actors.id"],
            name=op.f("fk_reviewed_action_revisions_proposed_by_id_actors"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviewed_action_revisions")),
        sa.UniqueConstraint(
            "action_id", "version", name=op.f("uq_reviewed_action_revisions_action_id")
        ),
        sa.UniqueConstraint("id", "action_id", name=op.f("uq_reviewed_action_revisions_id")),
    )
    for column in ("action_id", "source_version_id", "source_run_id", "expires_at"):
        op.create_index(
            op.f(f"ix_reviewed_action_revisions_{column}"),
            "reviewed_action_revisions",
            [column],
        )
    op.create_foreign_key(
        "fk_reviewed_actions_current_revision",
        "reviewed_actions",
        "reviewed_action_revisions",
        ["current_revision_id", "id"],
        ["id", "action_id"],
    )
    op.create_foreign_key(
        "fk_reviewed_actions_approved_revision",
        "reviewed_actions",
        "reviewed_action_revisions",
        ["approved_revision_id", "id"],
        ["id", "action_id"],
    )

    op.create_table(
        "reviewed_action_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_reviewed_action_attachments_position")),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_reviewed_action_attachments_content_sha256"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["reviewed_action_revisions.id"],
            name=op.f("fk_reviewed_action_attachments_revision_id_reviewed_action_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_reviewed_action_attachments_artifact_version_id_artifact_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviewed_action_attachments")),
        sa.UniqueConstraint(
            "revision_id", "position", name=op.f("uq_reviewed_action_attachments_revision_id")
        ),
        sa.UniqueConstraint(
            "revision_id",
            "artifact_version_id",
            name="uq_reviewed_action_attachments_revision_artifact",
        ),
    )
    op.create_index(
        op.f("ix_reviewed_action_attachments_revision_id"),
        "reviewed_action_attachments",
        ["revision_id"],
    )

    op.create_table(
        "reviewed_action_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved','rejected','revoked')",
            name=op.f("ck_reviewed_action_reviews_decision"),
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 1 AND 2000",
            name=op.f("ck_reviewed_action_reviews_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["reviewed_actions.id"],
            name=op.f("fk_reviewed_action_reviews_action_id_reviewed_actions"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "action_id"],
            ["reviewed_action_revisions.id", "reviewed_action_revisions.action_id"],
            name=op.f("fk_reviewed_action_reviews_revision_id_reviewed_action_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["actors.id"],
            name=op.f("fk_reviewed_action_reviews_reviewer_id_actors"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviewed_action_reviews")),
    )
    for column in ("action_id", "revision_id"):
        op.create_index(
            op.f(f"ix_reviewed_action_reviews_{column}"), "reviewed_action_reviews", [column]
        )

    op.create_table(
        "reviewed_action_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_log_id", sa.String(length=300), nullable=True),
        sa.Column("provider_external_id", sa.String(length=500), nullable=True),
        sa.Column("provider_url", sa.Text(), nullable=True),
        sa.Column("receipt", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observed_before_revision", sa.String(length=500), nullable=True),
        sa.Column("observed_after_revision", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("reconciliation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('running','succeeded','failed','outcome_unknown','partial','conflicted')",
            name=op.f("ck_reviewed_action_attempts_state"),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1", name=op.f("ck_reviewed_action_attempts_attempt_number")
        ),
        sa.CheckConstraint(
            "(state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_reviewed_action_attempts_lease_state"),
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["reviewed_actions.id"],
            name=op.f("fk_reviewed_action_attempts_action_id_reviewed_actions"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["reviewed_action_revisions.id"],
            name=op.f("fk_reviewed_action_attempts_revision_id_reviewed_action_revisions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviewed_action_attempts")),
        sa.UniqueConstraint("revision_id", name=op.f("uq_reviewed_action_attempts_revision_id")),
    )
    for column in ("action_id", "revision_id", "state"):
        op.create_index(
            op.f(f"ix_reviewed_action_attempts_{column}"), "reviewed_action_attempts", [column]
        )

    op.create_table(
        "provider_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("external_revision", sa.String(length=500), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('gmail_search','calendar_event','linear_issue','notion_page')",
            name=op.f("ck_provider_observations_kind"),
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64", name=op.f("ck_provider_observations_request_hash")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_provider_observations_owner_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["external_accounts.id"],
            name=op.f("fk_provider_observations_account_id_external_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_provider_observations_task_id_tasks")
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_provider_observations_opportunity_id_opportunities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_observations")),
    )
    for column in ("owner_id", "account_id", "task_id", "opportunity_id"):
        op.create_index(
            op.f(f"ix_provider_observations_{column}"), "provider_observations", [column]
        )
    op.create_index(
        "ix_provider_observations_owner_kind",
        "provider_observations",
        ["owner_id", "kind", "observed_at"],
    )

    op.create_table(
        "connected_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=300), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('running','completed','failed','outcome_unknown')",
            name=op.f("ck_connected_requests_state"),
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64", name=op.f("ck_connected_requests_request_hash")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["actors.id"], name=op.f("fk_connected_requests_actor_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connected_requests")),
        sa.UniqueConstraint("actor_id", "key", name=op.f("uq_connected_requests_actor_id")),
    )
    op.create_index(op.f("ix_connected_requests_actor_id"), "connected_requests", ["actor_id"])
    op.create_index(op.f("ix_connected_requests_state"), "connected_requests", ["state"])

    for table in (
        "reviewed_action_revisions",
        "reviewed_action_attachments",
        "reviewed_action_reviews",
        "provider_observations",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()"
        )


def downgrade() -> None:
    for table in (
        "provider_observations",
        "reviewed_action_reviews",
        "reviewed_action_attachments",
        "reviewed_action_revisions",
    ):
        op.execute(f"DROP TRIGGER immutable_rows ON {table}")
    op.drop_constraint(
        "fk_reviewed_actions_approved_revision", "reviewed_actions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_reviewed_actions_current_revision", "reviewed_actions", type_="foreignkey"
    )
    op.drop_table("connected_requests")
    op.drop_table("provider_observations")
    op.drop_table("reviewed_action_attempts")
    op.drop_table("reviewed_action_reviews")
    op.drop_table("reviewed_action_attachments")
    op.drop_table("reviewed_action_revisions")
    op.drop_table("reviewed_actions")
    op.drop_table("external_accounts")
