"""Conversation checkpoints and reviewed session-scoped memory."""

from alembic import op

revision = "0040_session_checkpoints"
down_revision = "0039_document_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE session_checkpoints (
            id UUID PRIMARY KEY,
            owner_id UUID NOT NULL,
            session_id UUID NOT NULL,
            sequence INTEGER NOT NULL,
            kind VARCHAR(20) NOT NULL,
            title VARCHAR(200) NOT NULL,
            run_id UUID,
            summary TEXT,
            summary_revision INTEGER,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT fk_session_checkpoints_session_id_agent_sessions
                FOREIGN KEY (session_id, owner_id) REFERENCES agent_sessions (id, owner_id),
            CONSTRAINT fk_session_checkpoints_run_id_agent_runs
                FOREIGN KEY (run_id, owner_id) REFERENCES agent_runs (id, owner_id),
            CONSTRAINT ck_session_checkpoints_sequence CHECK (sequence >= 1),
            CONSTRAINT ck_session_checkpoints_kind
                CHECK (kind IN ('saved', 'continued', 'compacted')),
            CONSTRAINT ck_session_checkpoints_title_length CHECK (length(title) BETWEEN 1 AND 200),
            CONSTRAINT ck_session_checkpoints_summary_length
                CHECK (summary IS NULL OR length(summary) BETWEEN 1 AND 10000),
            CONSTRAINT uq_session_checkpoints_session_id UNIQUE (session_id, summary_revision)
        )
    """)
    op.execute(
        "CREATE INDEX ix_session_checkpoints_session_created "
        "ON session_checkpoints (session_id, created_at, id)"
    )
    op.execute("""
        INSERT INTO session_checkpoints
            (id, owner_id, session_id, sequence, kind, title, run_id,
             summary, summary_revision, created_at)
        SELECT gen_random_uuid(), owner_id, id, (context_summary->>'covered_sequence')::integer,
            'compacted', 'Context summarized', (context_summary->>'run_id')::uuid,
            context_summary->>'summary', (context_summary->>'revision')::integer,
            (context_summary->>'created_at')::timestamptz
        FROM agent_sessions WHERE context_summary IS NOT NULL
            AND (context_summary->>'covered_sequence')::integer > 0
    """)
    op.drop_constraint(op.f("ck_memory_revisions_scope_type"), "memory_revisions", type_="check")
    op.create_check_constraint(
        "scope_type",
        "memory_revisions",
        "scope_type IN ('global', 'task', 'opportunity', 'session')",
    )
    op.execute("""
        CREATE FUNCTION reject_session_checkpoint_changes() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Conversation checkpoints are immutable';
        END;
        $$;
        CREATE TRIGGER session_checkpoints_immutable BEFORE UPDATE OR DELETE ON session_checkpoints
            FOR EACH ROW EXECUTE FUNCTION reject_session_checkpoint_changes();
    """)


def downgrade() -> None:
    # Avoid silently deleting scoped memories to fit an older schema.
    op.drop_constraint(op.f("ck_memory_revisions_scope_type"), "memory_revisions", type_="check")
    op.create_check_constraint(
        "scope_type", "memory_revisions", "scope_type IN ('global', 'task', 'opportunity')"
    )
    op.execute("DROP TABLE session_checkpoints")
    op.execute("DROP FUNCTION reject_session_checkpoint_changes()")
