"""Application CSV intake and browser automation runs."""

from alembic import op

revision = "0041_application_automation"
down_revision = "0040_session_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE application_imports (
            id UUID PRIMARY KEY,
            owner_id UUID NOT NULL,
            filename VARCHAR(255) NOT NULL,
            byte_size BIGINT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            state VARCHAR(20) NOT NULL DEFAULT 'queued',
            error TEXT,
            reject_reasons JSONB NOT NULL DEFAULT '{}',
            lease_id UUID,
            lease_expires_at TIMESTAMP WITH TIME ZONE,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT fk_application_imports_owner_id_actors
                FOREIGN KEY (owner_id) REFERENCES actors (id),
            CONSTRAINT uq_application_imports_id_owner UNIQUE (id, owner_id),
            CONSTRAINT ck_application_imports_state
                CHECK (state IN ('queued', 'running', 'parse_error', 'completed')),
            CONSTRAINT ck_application_imports_byte_size CHECK (byte_size BETWEEN 1 AND 5242880),
            CONSTRAINT ck_application_imports_row_version CHECK (row_version >= 1),
            CONSTRAINT ck_application_imports_error_state
                CHECK ((state = 'parse_error') = (error IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_application_imports_owner_id ON application_imports (owner_id)")
    op.execute("""
        CREATE TABLE applications (
            id UUID PRIMARY KEY,
            owner_id UUID NOT NULL,
            import_id UUID NOT NULL,
            source_row INTEGER NOT NULL,
            source_hash VARCHAR(64) NOT NULL,
            company VARCHAR(2048) NOT NULL,
            job_title VARCHAR(2048) NOT NULL,
            job_url TEXT NOT NULL,
            job_location VARCHAR(2048),
            job_id UUID,
            status VARCHAR(20) NOT NULL DEFAULT 'ready_to_run',
            submit_authorized_at TIMESTAMP WITH TIME ZONE,
            submit_authorized_by UUID,
            adapter_platform VARCHAR(20),
            last_run_id UUID,
            profile_version_id UUID,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT fk_applications_owner_id_actors
                FOREIGN KEY (owner_id) REFERENCES actors (id),
            CONSTRAINT fk_applications_import_id_owner
                FOREIGN KEY (import_id, owner_id)
                REFERENCES application_imports (id, owner_id),
            CONSTRAINT fk_applications_job_id_owner
                FOREIGN KEY (job_id, owner_id) REFERENCES jobs (id, owner_id),
            CONSTRAINT fk_applications_submit_authorized_by
                FOREIGN KEY (submit_authorized_by) REFERENCES actors (id),
            CONSTRAINT ck_applications_status
                CHECK (status IN ('intake', 'ready_to_run', 'running', 'ready_for_review',
                                  'skipped', 'failed', 'submitted')),
            CONSTRAINT ck_applications_source_row CHECK (source_row >= 1),
            CONSTRAINT ck_applications_authorization_state
                CHECK ((submit_authorized_at IS NULL) = (submit_authorized_by IS NULL)),
            CONSTRAINT ck_applications_row_version CHECK (row_version >= 1),
            CONSTRAINT uq_applications_id_owner UNIQUE (id, owner_id)
        )
    """)
    op.execute("CREATE INDEX ix_applications_owner_id ON applications (owner_id)")
    op.execute("CREATE INDEX ix_applications_import_id ON applications (import_id)")
    op.execute("CREATE INDEX ix_applications_status ON applications (status)")
    op.execute("CREATE INDEX ix_applications_job_id ON applications (job_id)")
    op.execute("""
        CREATE TABLE automation_runs (
            id UUID PRIMARY KEY,
            owner_id UUID NOT NULL,
            application_id UUID NOT NULL,
            device_id UUID,
            state VARCHAR(20) NOT NULL DEFAULT 'queued',
            attempt INTEGER NOT NULL DEFAULT 1,
            adapter_platform VARCHAR(20) NOT NULL,
            adapter_revision VARCHAR(64) NOT NULL,
            mode VARCHAR(20) NOT NULL DEFAULT 'fill_only',
            run_token UUID,
            run_token_expires_at TIMESTAMP WITH TIME ZONE,
            field_evidence JSONB NOT NULL DEFAULT '{}',
            page_evidence JSONB,
            simplify_step JSONB,
            error TEXT,
            started_at TIMESTAMP WITH TIME ZONE,
            finished_at TIMESTAMP WITH TIME ZONE,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT fk_automation_runs_owner_id_actors
                FOREIGN KEY (owner_id) REFERENCES actors (id),
            CONSTRAINT fk_automation_runs_application_id_owner
                FOREIGN KEY (application_id, owner_id)
                REFERENCES applications (id, owner_id),
            CONSTRAINT fk_automation_runs_device_id
                FOREIGN KEY (device_id) REFERENCES browser_devices (id),
            CONSTRAINT ck_automation_runs_state
                CHECK (state IN ('queued', 'running', 'completed', 'failed',
                                 'outcome_unknown', 'cancelled')),
            CONSTRAINT ck_automation_runs_attempt CHECK (attempt >= 1),
            CONSTRAINT ck_automation_runs_mode CHECK (mode IN ('fill_only', 'submit')),
            CONSTRAINT ck_automation_runs_token_state
                CHECK ((state = 'running')
                       = (run_token IS NOT NULL AND run_token_expires_at IS NOT NULL)),
            CONSTRAINT ck_automation_runs_row_version CHECK (row_version >= 1),
            CONSTRAINT uq_automation_runs_id_owner UNIQUE (id, owner_id)
        )
    """)
    op.execute("CREATE INDEX ix_automation_runs_owner_id ON automation_runs (owner_id)")
    op.execute("CREATE INDEX ix_automation_runs_application_id ON automation_runs (application_id)")
    op.execute("CREATE INDEX ix_automation_runs_state ON automation_runs (state)")
    op.execute("CREATE INDEX ix_automation_runs_device_id ON automation_runs (device_id)")


def downgrade() -> None:
    op.execute("DROP TABLE automation_runs")
    op.execute("DROP TABLE applications")
    op.execute("DROP TABLE application_imports")
