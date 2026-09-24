"""Durable document decisions, human type review and display-title proposals."""

import sqlalchemy as sa
from alembic import op

revision = "0039_document_decisions"
down_revision = "0038_spaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE document_policies (
	owner_id UUID NOT NULL,
	revision INTEGER NOT NULL,
	classification_mode VARCHAR(30) NOT NULL,
	catalog_ids JSONB NOT NULL,
	rename_mode VARCHAR(20) NOT NULL,
	rename_template VARCHAR(250) NOT NULL,
	timezone VARCHAR(100) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_document_policies PRIMARY KEY (owner_id),
	CONSTRAINT ck_document_policies_classification_mode
            CHECK (classification_mode IN ('off', 'after_extraction')),
	CONSTRAINT ck_document_policies_rename_mode
            CHECK (rename_mode IN ('off', 'task')),
	CONSTRAINT ck_document_policies_revision
            CHECK (revision >= 1),
	CONSTRAINT fk_document_policies_owner_id_actors
            FOREIGN KEY(owner_id)
            REFERENCES actors (id)
)
    """)
    op.execute("""
CREATE TABLE document_decisions (
	id UUID NOT NULL,
	owner_id UUID NOT NULL,
	artifact_id UUID NOT NULL,
	import_id UUID NOT NULL,
	task_id UUID NOT NULL,
	source_version_id UUID NOT NULL,
	extraction_version_id UUID NOT NULL,
	metadata_revision INTEGER NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	attempt INTEGER NOT NULL,
	trigger VARCHAR(20) NOT NULL,
	state VARCHAR(20) NOT NULL,
	lease_id UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	proposed_type_id UUID,
	reason_codes JSONB NOT NULL,
	provider VARCHAR(30) NOT NULL,
	requested_model VARCHAR(100) NOT NULL,
	returned_model VARCHAR(100),
	resolved_model VARCHAR(100),
	question_version VARCHAR(100) NOT NULL,
	policy_version VARCHAR(100) NOT NULL,
	catalog_snapshot JSONB NOT NULL,
	catalog_hash VARCHAR(64) NOT NULL,
	state_hash VARCHAR(64) NOT NULL,
	question_hash VARCHAR(64) NOT NULL,
	input_manifest JSONB NOT NULL,
	questions JSONB NOT NULL,
	answers JSONB,
	usage JSONB,
	cost_status VARCHAR(20) NOT NULL,
	provenance VARCHAR(30),
	latency_ms INTEGER,
	error VARCHAR(100),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_document_decisions PRIMARY KEY (id),
	CONSTRAINT uq_document_decisions_id UNIQUE (id, owner_id),
	CONSTRAINT uq_document_decisions_owner_id UNIQUE (owner_id, fingerprint, attempt),
	CONSTRAINT ck_document_decisions_state
            CHECK (state IN ('queued', 'running', 'proposed', 'needs_review',
                'unavailable', 'cancelled', 'superseded')),
	CONSTRAINT ck_document_decisions_lease
            CHECK ((state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)),
	CONSTRAINT ck_document_decisions_cost_status
            CHECK (cost_status IN ('not_started', 'reserved', 'settled', 'unknown')),
	CONSTRAINT ck_document_decisions_attempt
            CHECK (attempt >= 1),
	CONSTRAINT fk_document_decisions_owner_id_actors
            FOREIGN KEY(owner_id)
            REFERENCES actors (id),
	CONSTRAINT fk_document_decisions_artifact_id_artifacts
            FOREIGN KEY(artifact_id)
            REFERENCES artifacts (id),
	CONSTRAINT fk_document_decisions_import_id_document_imports
            FOREIGN KEY(import_id)
            REFERENCES document_imports (id),
	CONSTRAINT fk_document_decisions_task_id_tasks
            FOREIGN KEY(task_id)
            REFERENCES tasks (id),
	CONSTRAINT fk_document_decisions_source_version_id_artifact_versions
            FOREIGN KEY(source_version_id)
            REFERENCES artifact_versions (id),
	CONSTRAINT fk_document_decisions_extraction_version_id_artifact_versions
            FOREIGN KEY(extraction_version_id)
            REFERENCES artifact_versions (id),
	CONSTRAINT fk_document_decisions_proposed_type_id_document_types
            FOREIGN KEY(proposed_type_id)
            REFERENCES document_types (id)
)
    """)
    op.execute("""
CREATE INDEX ix_document_decisions_artifact_id ON document_decisions (artifact_id)
    """)
    op.execute("""
CREATE INDEX ix_document_decisions_owner_id ON document_decisions (owner_id)
    """)
    op.execute("""
CREATE INDEX ix_document_decisions_state ON document_decisions (state)
    """)
    op.execute("""
CREATE TABLE document_classification_reviews (
	id UUID NOT NULL,
	owner_id UUID NOT NULL,
	artifact_id UUID NOT NULL,
	decision_id UUID,
	reviewer_id UUID NOT NULL,
	source_version_id UUID NOT NULL,
	extraction_version_id UUID NOT NULL,
	metadata_revision INTEGER NOT NULL,
	outcome VARCHAR(30) NOT NULL,
	accepted_type_id UUID NOT NULL,
	reason TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_document_classification_reviews PRIMARY KEY (id),
	CONSTRAINT ck_document_classification_reviews_outcome
            CHECK (outcome IN ('accept', 'retain', 'request_better_file')),
	CONSTRAINT fk_document_classification_reviews_owner_id_actors
            FOREIGN KEY(owner_id)
            REFERENCES actors (id),
	CONSTRAINT fk_document_classification_reviews_artifact_id_artifacts
            FOREIGN KEY(artifact_id)
            REFERENCES artifacts (id),
	CONSTRAINT fk_document_classification_reviews_decision_id_document_210f
            FOREIGN KEY(decision_id)
            REFERENCES document_decisions (id),
	CONSTRAINT fk_document_classification_reviews_reviewer_id_actors
            FOREIGN KEY(reviewer_id)
            REFERENCES actors (id),
	CONSTRAINT fk_document_classification_reviews_source_version_id_ar_5650
            FOREIGN KEY(source_version_id)
            REFERENCES artifact_versions (id),
	CONSTRAINT fk_document_classification_reviews_extraction_version_i_3c6c
            FOREIGN KEY(extraction_version_id)
            REFERENCES artifact_versions (id),
	CONSTRAINT fk_document_classification_reviews_accepted_type_id_doc_8820
            FOREIGN KEY(accepted_type_id)
            REFERENCES document_types (id)
)
    """)
    op.execute("""
CREATE INDEX ix_document_classification_reviews_artifact_id
    ON document_classification_reviews (artifact_id)
    """)
    op.execute("""
CREATE INDEX ix_document_classification_reviews_owner_id
    ON document_classification_reviews (owner_id)
    """)
    op.execute("""
CREATE TABLE document_renames (
	id UUID NOT NULL,
	owner_id UUID NOT NULL,
	artifact_id UUID NOT NULL,
	review_id UUID NOT NULL,
	policy_revision INTEGER NOT NULL,
	metadata_revision INTEGER NOT NULL,
	task_id UUID NOT NULL,
	before_title VARCHAR(300) NOT NULL,
	after_title VARCHAR(300),
	template VARCHAR(250) NOT NULL,
	render_inputs JSONB NOT NULL,
	state VARCHAR(30) NOT NULL,
	error VARCHAR(100),
	row_version INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_document_renames PRIMARY KEY (id),
	CONSTRAINT uq_document_renames_artifact_id UNIQUE (artifact_id, review_id, policy_revision),
	CONSTRAINT ck_document_renames_state
            CHECK (state IN ('pending', 'needs_correction', 'applied', 'cancelled', 'superseded')),
	CONSTRAINT fk_document_renames_owner_id_actors
            FOREIGN KEY(owner_id)
            REFERENCES actors (id),
	CONSTRAINT fk_document_renames_artifact_id_artifacts
            FOREIGN KEY(artifact_id)
            REFERENCES artifacts (id),
	CONSTRAINT fk_document_renames_review_id_document_classification_reviews
            FOREIGN KEY(review_id)
            REFERENCES document_classification_reviews (id),
	CONSTRAINT uq_document_renames_task_id UNIQUE (task_id),
	CONSTRAINT fk_document_renames_task_id_tasks
            FOREIGN KEY(task_id)
            REFERENCES tasks (id)
)
    """)
    op.execute("""
CREATE INDEX ix_document_renames_artifact_id ON document_renames (artifact_id)
    """)
    op.execute("""
CREATE INDEX ix_document_renames_owner_id ON document_renames (owner_id)
    """)
    for table in (
        "document_policies",
        "document_decisions",
        "document_classification_reviews",
        "document_renames",
    ):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    for slug, description in {
        "resume": "A career summary listing experience, education, skills and qualifications.",
        "cover-letter": "A candidate's letter describing fit and motivation for a role.",
        "research": "A research brief with sourced findings about a topic or organization.",
        "interview": "An interview preparation brief, question set or interview notes.",
        "notes": "General notes or reference material without another specific catalog purpose.",
    }.items():
        op.execute(
            sa.text(
                "UPDATE document_types SET description=:description WHERE slug=:slug "
                "AND (description IS NULL OR trim(description)='')"
            ).bindparams(slug=slug, description=description)
        )
    op.add_column(
        "spending_reservations", sa.Column("document_decision_id", sa.Uuid(), nullable=True)
    )
    op.create_index(
        "ix_spending_reservations_document_decision_id",
        "spending_reservations",
        ["document_decision_id"],
    )
    op.create_foreign_key(
        "fk_spending_document_decision_owner",
        "spending_reservations",
        "document_decisions",
        ["document_decision_id", "owner_id"],
        ["id", "owner_id"],
    )
    op.drop_constraint(
        op.f("ck_spending_reservations_model_run_lease"), "spending_reservations", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_spending_reservations_model_run_lease"),
        "spending_reservations",
        "kind != 'model' OR (num_nonnulls(agent_run_id, document_decision_id) = 1 "
        "AND original_lease_id IS NOT NULL)",
    )
    op.execute(
        "INSERT INTO document_types (id,slug,name,description) "
        "VALUES ('f48455bc-6ded-5a3c-aac6-c1328c4da59f','unclassified','Unclassified',"
        "'Document purpose has not been accepted by the owner.') ON CONFLICT (slug) DO NOTHING"
    )
    op.execute("""
    CREATE FUNCTION preserve_document_decision_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE mutable text[] := ARRAY['state','lease_id','lease_expires_at','proposed_type_id',
        'reason_codes','returned_model','resolved_model','answers','usage','cost_status',
        'provenance','latency_ms','error','completed_at'];
    BEGIN
        IF (to_jsonb(NEW) - mutable) IS DISTINCT FROM (to_jsonb(OLD) - mutable) THEN
            RAISE EXCEPTION 'Document decision inputs are immutable';
        END IF;
        IF OLD.completed_at IS NOT NULL AND
            (to_jsonb(NEW) - ARRAY['state','error']) IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['state','error']) THEN
            RAISE EXCEPTION 'Completed document decision evidence is immutable';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER preserve_document_decision_evidence BEFORE UPDATE ON document_decisions
        FOR EACH ROW EXECUTE FUNCTION preserve_document_decision_evidence();
    CREATE FUNCTION preserve_document_review_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'Document classification reviews are immutable';
    END $$;
    CREATE TRIGGER preserve_document_review_evidence
        BEFORE UPDATE ON document_classification_reviews
        FOR EACH ROW EXECUTE FUNCTION preserve_document_review_evidence();
    """)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM spending_reservations WHERE document_decision_id IS NOT NULL")
    ):
        raise RuntimeError("Retain document spending evidence before downgrading")
    op.drop_constraint(
        op.f("ck_spending_reservations_model_run_lease"), "spending_reservations", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_spending_reservations_model_run_lease"),
        "spending_reservations",
        "kind != 'model' OR (agent_run_id IS NOT NULL AND original_lease_id IS NOT NULL)",
    )
    op.drop_constraint(
        "fk_spending_document_decision_owner",
        "spending_reservations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_spending_reservations_document_decision_id", table_name="spending_reservations"
    )
    op.drop_column("spending_reservations", "document_decision_id")
    op.drop_table("document_renames")
    op.drop_table("document_classification_reviews")
    op.drop_table("document_decisions")
    op.drop_table("document_policies")
    op.execute("DROP FUNCTION IF EXISTS preserve_document_decision_evidence()")
    op.execute("DROP FUNCTION IF EXISTS preserve_document_review_evidence()")
    op.execute(
        "DELETE FROM document_types WHERE slug='unclassified' AND NOT EXISTS "
        "(SELECT 1 FROM documents WHERE document_type_id=document_types.id)"
    )
