from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.db.models import Actor, AuditEvent
from command_center.db.reviewed_actions import ExternalAccount, ProviderObservation
from command_center.db.session import database_is_ready


def clear_question_fixtures(engine: Engine) -> None:
    """The shared synthetic suite may leave durable waiting runs before round-trip tests."""
    with engine.begin() as connection:
        # Only synthetic state is normalized for the full schema round-trip.
        connection.execute(text("DELETE FROM application_materials"))
        connection.execute(text("DELETE FROM application_tracks"))
        connection.execute(text("DELETE FROM application_preparations"))
        connection.execute(
            text(
                "UPDATE profile_facts SET field='answer' WHERE field IN "
                "('first_name', 'last_name', 'address_line1', 'address_line2', 'city', "
                "'region', 'postal_code', 'country', 'github')"
            )
        )
        connection.execute(text("DELETE FROM writing_recovery_copies"))
        connection.execute(text("DELETE FROM record_work"))
        connection.execute(text("DELETE FROM contact_discovery_evidence"))
        connection.execute(text("DELETE FROM follow_ups"))
        connection.execute(text("DELETE FROM writing_drafts"))
        # This function operates only on the dedicated synthetic test database.
        connection.execute(text("ALTER TABLE contact_observations DISABLE TRIGGER immutable_rows"))
        connection.execute(text("DELETE FROM contact_observations"))
        connection.execute(text("ALTER TABLE contact_observations ENABLE TRIGGER immutable_rows"))
        connection.execute(text("DELETE FROM agent_resume_intents"))
        connection.execute(text("DELETE FROM agent_questions"))
        connection.execute(
            text(
                "UPDATE agent_runs SET state='cancelled', lease_id=NULL, lease_expires_at=NULL, "
                "completed_at=now() WHERE state='waiting_for_user'"
            )
        )


def test_linkedin_downgrade_refuses_to_discard_contact_evidence(engine, migration_config):
    from uuid import uuid5

    from command_center.db.artifacts import Artifact
    from command_center.db.crm import Contact, ContactObservation

    clear_question_fixtures(engine)
    with Session(engine) as db, db.begin():
        actor = Actor(id=uuid4(), kind="human", display_name="Synthetic mapping owner")
        db.add(actor)
        db.flush()
        contact = Contact(owner_id=actor.id, name="Synthetic source person")
        db.add(contact)
        db.flush()
        source = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=actor.id,
            title="Synthetic export",
            kind="source",
            sensitivity="private",
            text="Synthetic source row",
            document_type_id=None,
            request_id=uuid4(),
        )
        observation = ContactObservation.capture_linkedin(
            db,
            contact=contact,
            source_version_id=uuid5(source.id, "version:1"),
            source_row=1,
            row={"First Name": "Synthetic"},
            request_id=uuid4(),
        )
        observation_id = observation.id
    try:
        with pytest.raises(RuntimeError, match="preserve provenance"):
            command.downgrade(migration_config, "0016_agent_questions")
        with Session(engine) as db:
            assert db.get(ContactObservation, observation_id).first_name == "Synthetic"
    finally:
        clear_question_fixtures(engine)


def test_connected_context_downgrade_refuses_to_delete_provenance(
    engine: Engine, migration_config: Config
) -> None:
    clear_question_fixtures(engine)
    actor_id, account_id, observation_id, request_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Migration provenance owner"))
        db.flush()
        db.add(
            ExternalAccount(
                id=account_id,
                owner_id=actor_id,
                toolkit="googlecalendar",
                composio_connected_account_id=f"ca_{account_id}",
                composio_auth_config_id="ac_calendar",
                display_name="Migration calendar",
                provider_identity={"email": "migration@example.test"},
                connection_status="ACTIVE",
                identity_verified_at=datetime(2026, 9, 22, tzinfo=UTC),
            )
        )
        ProviderObservation.capture_context(
            db,
            request_id=request_id,
            record_id=observation_id,
            owner_id=actor_id,
            account_id=account_id,
            task_id=None,
            opportunity_id=None,
            kind="calendar_events",
            request={"kind": "calendar_events"},
            result={"context": {"events": [{"id": "event-synthetic"}]}},
            external_revision="revision-synthetic",
        )
    try:
        with pytest.raises(RuntimeError, match="preserve provenance"):
            command.downgrade(migration_config, "0014_spending_controls")
        with Session(engine) as db:
            observation = db.get(ProviderObservation, observation_id)
            assert observation is not None
            assert observation.result["context"]["events"][0]["id"] == "event-synthetic"
            assert db.scalar(
                select(AuditEvent).where(
                    AuditEvent.subject_id == observation_id,
                    AuditEvent.action == "connected_context.observed",
                )
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE provider_observations DISABLE TRIGGER immutable_rows")
            )
            connection.execute(text("ALTER TABLE audit_events DISABLE TRIGGER immutable_rows"))
            connection.execute(
                text("DELETE FROM audit_events WHERE subject_id = :id"), {"id": observation_id}
            )
            connection.execute(
                text("DELETE FROM provider_observations WHERE id = :id"), {"id": observation_id}
            )
            connection.execute(
                text("ALTER TABLE provider_observations ENABLE TRIGGER immutable_rows")
            )
            connection.execute(text("ALTER TABLE audit_events ENABLE TRIGGER immutable_rows"))
            connection.execute(
                text("DELETE FROM external_accounts WHERE id = :id"), {"id": account_id}
            )
            connection.execute(text("DELETE FROM actors WHERE id = :id"), {"id": actor_id})


def test_upgrade_downgrade_upgrade_and_no_schema_drift(
    engine: Engine, migration_config: Config
) -> None:
    clear_question_fixtures(engine)
    assert database_is_ready(engine)
    command.check(migration_config)
    command.downgrade(migration_config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    assert not database_is_ready(engine)
    command.upgrade(migration_config, "head")
    assert database_is_ready(engine)
    command.check(migration_config)
