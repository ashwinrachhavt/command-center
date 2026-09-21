"""foundation records and shared artifact lifecycle

Revision ID: 0001_foundation
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "actors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('human', 'agent', 'service')", name=op.f("ck_actors_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actors")),
    )
    op.create_table(
        "blobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=71), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_blobs_sha256")),
        sa.CheckConstraint("storage_key = 'sha256/' || sha256", name=op.f("ck_blobs_storage_key")),
        sa.CheckConstraint("byte_size >= 0", name=op.f("ck_blobs_byte_size")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blobs")),
        sa.UniqueConstraint("id", "sha256", name=op.f("uq_blobs_id")),
        sa.UniqueConstraint("sha256", name=op.f("uq_blobs_sha256")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_blobs_storage_key")),
    )
    op.create_table(
        "document_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_types")),
        sa.UniqueConstraint("slug", name=op.f("uq_document_types_slug")),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("sensitivity", sa.String(length=20), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('document', 'message', 'research', 'package', 'source')",
            name=op.f("ck_artifacts_kind"),
        ),
        sa.CheckConstraint(
            "sensitivity IN ('public', 'private', 'restricted')",
            name=op.f("ck_artifacts_sensitivity"),
        ),
        sa.CheckConstraint("row_version >= 1", name=op.f("ck_artifacts_row_version")),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["actors.id"], name=op.f("fk_artifacts_created_by_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_artifacts_owner_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint("id", "kind", name=op.f("uq_artifacts_id")),
    )
    op.create_index(op.f("ix_artifacts_owner_id"), "artifacts", ["owner_id"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'", name=op.f("ck_audit_events_details_object")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["actors.id"], name=op.f("fk_audit_events_actor_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"], unique=False)
    op.create_index(
        op.f("ix_audit_events_occurred_at"), "audit_events", ["occurred_at"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_request_id"), "audit_events", ["request_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_subject_id"), "audit_events", ["subject_id"], unique=False
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(state = 'done') = (completed_at IS NOT NULL)", name=op.f("ck_tasks_completion")
        ),
        sa.CheckConstraint(
            "state IN ('open', 'in_progress', 'snoozed', 'done', 'cancelled')",
            name=op.f("ck_tasks_state"),
        ),
        sa.CheckConstraint(
            "NOT (due_date IS NOT NULL AND due_at IS NOT NULL)", name=op.f("ck_tasks_due_semantics")
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_tasks_title_not_blank")),
        sa.CheckConstraint("priority BETWEEN 0 AND 3", name=op.f("ck_tasks_priority")),
        sa.CheckConstraint("row_version >= 1", name=op.f("ck_tasks_row_version")),
        sa.ForeignKeyConstraint(["owner_id"], ["actors.id"], name=op.f("fk_tasks_owner_id_actors")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_owner_id"), "tasks", ["owner_id"], unique=False)
    op.create_index(op.f("ix_tasks_state"), "tasks", ["state"], unique=False)
    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("blob_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("schema_key", sa.String(length=100), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(payload IS NULL AND schema_key IS NULL) OR "
            "(payload IS NOT NULL AND schema_key IS NOT NULL "
            "AND jsonb_typeof(payload) = 'object')",
            name=op.f("ck_artifact_versions_structured_schema"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_artifact_versions_content_sha256")
        ),
        sa.CheckConstraint(
            "(blob_id IS NULL) <> (payload IS NULL)",
            name=op.f("ck_artifact_versions_one_content_source"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_artifact_versions_version")),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_artifact_versions_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["blob_id", "content_sha256"],
            ["blobs.id", "blobs.sha256"],
            name=op.f("fk_artifact_versions_blob_id_blobs"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["actors.id"], name=op.f("fk_artifact_versions_created_by_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_versions")),
        sa.UniqueConstraint(
            "artifact_id", "version", name=op.f("uq_artifact_versions_artifact_id")
        ),
    )
    op.create_index(
        op.f("ix_artifact_versions_artifact_id"), "artifact_versions", ["artifact_id"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=20), nullable=False),
        sa.Column("document_type_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("artifact_kind = 'document'", name=op.f("ck_documents_document_kind")),
        sa.ForeignKeyConstraint(
            ["artifact_id", "artifact_kind"],
            ["artifacts.id", "artifacts.kind"],
            name=op.f("fk_documents_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name=op.f("fk_documents_document_type_id_document_types"),
        ),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_documents")),
    )
    op.create_index(
        op.f("ix_documents_document_type_id"), "documents", ["document_type_id"], unique=False
    )
    op.create_table(
        "task_artifacts",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["artifacts.id"], name=op.f("fk_task_artifacts_artifact_id_artifacts")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_artifacts_task_id_tasks")
        ),
        sa.PrimaryKeyConstraint("task_id", "artifact_id", name=op.f("pk_task_artifacts")),
    )
    op.create_index(
        op.f("ix_task_artifacts_artifact_id"), "task_artifacts", ["artifact_id"], unique=False
    )
    op.create_table(
        "artifact_derivations",
        sa.Column("output_version_id", sa.Uuid(), nullable=False),
        sa.Column("input_version_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "output_version_id <> input_version_id", name=op.f("ck_artifact_derivations_not_self")
        ),
        sa.ForeignKeyConstraint(
            ["input_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_artifact_derivations_input_version_id_artifact_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["output_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_artifact_derivations_output_version_id_artifact_versions"),
        ),
        sa.PrimaryKeyConstraint(
            "output_version_id", "input_version_id", name=op.f("pk_artifact_derivations")
        ),
    )
    op.create_table(
        "artifact_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'revoked')",
            name=op.f("ck_artifact_reviews_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_artifact_reviews_artifact_version_id_artifact_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["actors.id"], name=op.f("fk_artifact_reviews_reviewer_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_reviews")),
    )
    op.create_index(
        op.f("ix_artifact_reviews_artifact_version_id"),
        "artifact_reviews",
        ["artifact_version_id"],
        unique=False,
    )
    op.create_table(
        "source_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("account_scope", sa.String(length=200), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"],
            ["artifact_versions.id"],
            name=op.f("fk_source_records_artifact_version_id_artifact_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_records")),
    )
    op.create_index(
        op.f("ix_source_records_artifact_version_id"),
        "source_records",
        ["artifact_version_id"],
        unique=False,
    )
    op.create_table(
        "evidence_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("source_span", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IN ('unknown', 'low', 'medium', 'high')",
            name=op.f("ck_evidence_claims_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_evidence_claims_source_record_id_source_records"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_claims")),
    )
    op.create_index(
        op.f("ix_evidence_claims_source_record_id"),
        "evidence_claims",
        ["source_record_id"],
        unique=False,
    )
    op.create_table(
        "task_evidence",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_claim_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_claim_id"],
            ["evidence_claims.id"],
            name=op.f("fk_task_evidence_evidence_claim_id_evidence_claims"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_evidence_task_id_tasks")
        ),
        sa.PrimaryKeyConstraint("task_id", "evidence_claim_id", name=op.f("pk_task_evidence")),
    )
    op.create_index(
        op.f("ix_task_evidence_evidence_claim_id"),
        "task_evidence",
        ["evidence_claim_id"],
        unique=False,
    )

    op.execute("""
        CREATE FUNCTION reject_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '23514';
        END;
        $$
    """)
    for table in (
        "blobs",
        "artifact_versions",
        "artifact_reviews",
        "artifact_derivations",
        "audit_events",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()"
        )

    # A document is an artifact facet. Defer until commit so both rows can be inserted together.
    op.execute("""
        CREATE FUNCTION require_document_facet() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            affected_id uuid;
        BEGIN
            IF TG_TABLE_NAME = 'artifacts' THEN
                affected_id := NEW.id;
            ELSE
                affected_id := OLD.artifact_id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM artifacts a WHERE a.id = affected_id AND a.kind = 'document'
                AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.artifact_id = a.id)
            ) THEN
                RAISE EXCEPTION 'Document artifacts require a document facet'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER require_document_facet
        AFTER INSERT OR UPDATE ON artifacts DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_document_facet()
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER retain_document_facet
        AFTER DELETE OR UPDATE ON documents DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_document_facet()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER retain_document_facet ON documents")
    op.execute("DROP TRIGGER require_document_facet ON artifacts")
    op.execute("DROP FUNCTION require_document_facet()")
    op.drop_index(op.f("ix_task_evidence_evidence_claim_id"), table_name="task_evidence")
    op.drop_table("task_evidence")
    op.drop_index(op.f("ix_evidence_claims_source_record_id"), table_name="evidence_claims")
    op.drop_table("evidence_claims")
    op.drop_index(op.f("ix_source_records_artifact_version_id"), table_name="source_records")
    op.drop_table("source_records")
    op.drop_index(op.f("ix_artifact_reviews_artifact_version_id"), table_name="artifact_reviews")
    op.drop_table("artifact_reviews")
    op.drop_table("artifact_derivations")
    op.drop_index(op.f("ix_task_artifacts_artifact_id"), table_name="task_artifacts")
    op.drop_table("task_artifacts")
    op.drop_index(op.f("ix_documents_document_type_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_artifact_versions_artifact_id"), table_name="artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_index(op.f("ix_tasks_state"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_owner_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_audit_events_subject_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_request_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_occurred_at"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_artifacts_owner_id"), table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_table("document_types")
    op.drop_table("blobs")
    op.drop_table("actors")
    op.execute("DROP FUNCTION reject_immutable_change()")
