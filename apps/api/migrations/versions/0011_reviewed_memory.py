"""Reviewed scoped reusable memory.

Revision ID: 0011_reviewed_memory
Revises: 0010_agent_events
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_reviewed_memory"
down_revision: str | None = "0010_agent_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("memory_items", sa.Column("current_revision_id", sa.Uuid(), nullable=True))
    op.add_column("memory_items", sa.Column("active_revision_id", sa.Uuid(), nullable=True))
    op.create_check_constraint("ck_memory_items_row_version", "memory_items", "row_version >= 1")
    op.create_unique_constraint("uq_memory_items_id", "memory_items", ["id", "owner_id"])
    op.create_table(
        "memory_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_memory_revisions_version")),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 200",
            name=op.f("ck_memory_revisions_title_length"),
        ),
        sa.CheckConstraint(
            "length(content) BETWEEN 1 AND 10000",
            name=op.f("ck_memory_revisions_content_length"),
        ),
        sa.CheckConstraint("kind IN ('note', 'preference')", name=op.f("ck_memory_revisions_kind")),
        sa.CheckConstraint(
            "scope_type IN ('global', 'task', 'opportunity')",
            name=op.f("ck_memory_revisions_scope_type"),
        ),
        sa.CheckConstraint(
            "(scope_type = 'global') = (scope_id IS NULL)",
            name=op.f("ck_memory_revisions_scope_id"),
        ),
        sa.CheckConstraint(
            "source IN ('human', 'agent', 'legacy_human', 'legacy_agent')",
            name=op.f("ck_memory_revisions_source"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(reason) <= 2000",
            name=op.f("ck_memory_revisions_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memory_items.id"],
            name=op.f("fk_memory_revisions_memory_id_memory_items"),
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_memory_revisions_source_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_memory_revisions_source_artifact_id_artifacts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_revisions")),
        sa.UniqueConstraint("memory_id", "version", name=op.f("uq_memory_revisions_memory_id")),
        sa.UniqueConstraint("id", "memory_id", name=op.f("uq_memory_revisions_id")),
    )
    op.create_index(
        op.f("ix_memory_revisions_memory_id"),
        "memory_revisions",
        ["memory_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_memory_revisions_valid_until"),
        "memory_revisions",
        ["valid_until"],
        unique=False,
    )
    op.create_index(
        op.f("ix_memory_revisions_source_run_id"),
        "memory_revisions",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_memory_revisions_source_artifact_id"),
        "memory_revisions",
        ["source_artifact_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_revisions_scope",
        "memory_revisions",
        ["scope_type", "scope_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_revisions_search",
        "memory_revisions",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "memory_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'revoked')",
            name=op.f("ck_memory_reviews_decision"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(reason) <= 2000",
            name=op.f("ck_memory_reviews_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memory_items.id"],
            name=op.f("fk_memory_reviews_memory_id_memory_items"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "memory_id"],
            ["memory_revisions.id", "memory_revisions.memory_id"],
            name=op.f("fk_memory_reviews_revision_id_memory_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["actors.id"],
            name=op.f("fk_memory_reviews_reviewer_id_actors"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_reviews")),
    )
    op.create_index(
        op.f("ix_memory_reviews_memory_id"),
        "memory_reviews",
        ["memory_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_memory_reviews_revision_id"),
        "memory_reviews",
        ["revision_id"],
        unique=False,
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, owner_id, title, content, kind, source, created_at FROM memory_items")
    ).mappings()
    for row in rows:
        item_id = UUID(str(row["id"]))
        revision_id = uuid5(NAMESPACE_URL, f"command-center:memory:{item_id}:revision:1")
        source = "legacy_agent" if row["source"] == "agent" else "legacy_human"
        connection.execute(
            sa.text(
                "INSERT INTO memory_revisions "
                "(id, memory_id, version, title, content, kind, scope_type, scope_id, "
                "valid_until, source, source_run_id, source_artifact_id, reason, created_at) "
                "VALUES (:id, :memory_id, 1, :title, :content, :kind, 'global', NULL, "
                "NULL, :source, NULL, NULL, :reason, :created_at)"
            ),
            {
                "id": revision_id,
                "memory_id": item_id,
                "title": row["title"],
                "content": row["content"],
                "kind": row["kind"],
                "source": source,
                "reason": "Imported from the legacy memory store.",
                "created_at": row["created_at"],
            },
        )
        active_id = revision_id if source == "legacy_human" else None
        connection.execute(
            sa.text(
                "UPDATE memory_items SET current_revision_id = :revision_id, "
                "active_revision_id = :active_id WHERE id = :item_id"
            ),
            {"revision_id": revision_id, "active_id": active_id, "item_id": item_id},
        )
        if active_id is not None:
            review_id = uuid5(NAMESPACE_URL, f"command-center:memory:{item_id}:legacy-review")
            connection.execute(
                sa.text(
                    "INSERT INTO memory_reviews "
                    "(id, memory_id, revision_id, reviewer_id, decision, reason, created_at) "
                    "VALUES (:id, :memory_id, :revision_id, :reviewer_id, 'approved', "
                    ":reason, :created_at)"
                ),
                {
                    "id": review_id,
                    "memory_id": item_id,
                    "revision_id": revision_id,
                    "reviewer_id": row["owner_id"],
                    "reason": "Preserved explicit legacy human-authored memory.",
                    "created_at": row["created_at"],
                },
            )

    op.create_foreign_key(
        "fk_memory_items_current_revision",
        "memory_items",
        "memory_revisions",
        ["current_revision_id", "id"],
        ["id", "memory_id"],
    )
    op.create_foreign_key(
        "fk_memory_items_active_revision",
        "memory_items",
        "memory_revisions",
        ["active_revision_id", "id"],
        ["id", "memory_id"],
    )
    op.drop_constraint(op.f("ck_memory_items_source"), "memory_items", type_="check")
    op.drop_constraint(op.f("ck_memory_items_kind"), "memory_items", type_="check")
    for column in ("source", "kind", "content", "title"):
        op.drop_column("memory_items", column)
    for table in ("memory_revisions", "memory_reviews"):
        op.execute(
            f"CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()"
        )


def downgrade() -> None:
    for table in ("memory_reviews", "memory_revisions"):
        op.execute(f"DROP TRIGGER immutable_rows ON {table}")
    op.add_column("memory_items", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column("memory_items", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("memory_items", sa.Column("kind", sa.String(length=20), nullable=True))
    op.add_column("memory_items", sa.Column("source", sa.String(length=20), nullable=True))
    op.execute(
        "UPDATE memory_items AS item SET "
        "title = revision.title, content = revision.content, kind = revision.kind, "
        "source = CASE WHEN revision.source IN ('agent', 'legacy_agent') "
        "THEN 'agent' ELSE 'human' END "
        "FROM memory_revisions AS revision WHERE revision.id = item.current_revision_id"
    )
    for column in ("title", "content", "kind", "source"):
        op.alter_column("memory_items", column, nullable=False)
    op.create_check_constraint(
        op.f("ck_memory_items_kind"),
        "memory_items",
        "kind IN ('note', 'preference')",
    )
    op.create_check_constraint(
        op.f("ck_memory_items_source"),
        "memory_items",
        "source IN ('human', 'agent')",
    )
    op.drop_constraint("fk_memory_items_active_revision", "memory_items", type_="foreignkey")
    op.drop_constraint("fk_memory_items_current_revision", "memory_items", type_="foreignkey")
    op.drop_table("memory_reviews")
    op.drop_table("memory_revisions")
    op.drop_constraint("uq_memory_items_id", "memory_items", type_="unique")
    op.drop_constraint("ck_memory_items_row_version", "memory_items", type_="check")
    op.drop_column("memory_items", "active_revision_id")
    op.drop_column("memory_items", "current_revision_id")
