from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.db.models import Actor, AuditEvent, Task
from command_center.db.reviewed_actions import ExternalAccount, ProviderObservation
from command_center.db.session import database_is_ready


def clear_question_fixtures(engine: Engine) -> None:
    """The shared synthetic suite may leave durable waiting runs before round-trip tests."""
    with engine.begin() as connection:
        # Only synthetic state is normalized for the full schema round-trip.
        tables = set(inspect(connection).get_table_names())
        if "document_decisions" in tables:
            connection.execute(
                text("DELETE FROM spending_reservations WHERE document_decision_id IS NOT NULL")
            )
        if "spaces" in tables:
            connection.execute(text("DELETE FROM space_links"))
            connection.execute(text("DELETE FROM spaces"))
        connection.execute(text("UPDATE tasks SET state='open' WHERE state='waiting'"))
        columns = {
            table: {column["name"] for column in inspect(connection).get_columns(table)}
            for table in ("agent_sessions", "agent_messages")
        }
        if "context_summary" in columns["agent_sessions"]:
            connection.execute(text("UPDATE agent_sessions SET context_summary=NULL"))
        if "answer_cache" in columns["agent_messages"]:
            connection.execute(text("UPDATE agent_messages SET answer_cache=NULL"))
        connection.execute(text("DELETE FROM application_materials"))
        connection.execute(text("DELETE FROM application_tracks"))
        connection.execute(text("DELETE FROM application_preparations"))
        # Normalize only synthetic connector fixtures for older-schema checks.
        connection.execute(
            text("UPDATE external_accounts SET toolkit='linear' WHERE toolkit='linkedin'")
        )
        connection.execute(
            text("UPDATE reviewed_actions SET kind='linear_create' WHERE kind='linkedin_post'")
        )
        connection.execute(text("ALTER TABLE provider_observations DISABLE TRIGGER immutable_rows"))
        connection.execute(
            text(
                "DELETE FROM provider_observations "
                "WHERE kind IN ('linkedin_profile','linkedin_post')"
            )
        )
        connection.execute(text("ALTER TABLE provider_observations ENABLE TRIGGER immutable_rows"))
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
        # Clear only synthetic timing metadata so older migration guards are reachable.
        connection.execute(
            text("ALTER TABLE reviewed_action_revisions DISABLE TRIGGER immutable_rows")
        )
        connection.execute(
            text("UPDATE reviewed_action_revisions SET delivery=NULL, scheduled_for=NULL")
        )
        connection.execute(
            text("ALTER TABLE reviewed_action_revisions ENABLE TRIGGER immutable_rows")
        )
        connection.execute(text("DELETE FROM writing_drafts"))
        # This function operates only on the dedicated synthetic test database.
        connection.execute(text("ALTER TABLE contact_observations DISABLE TRIGGER immutable_rows"))
        connection.execute(text("DELETE FROM contact_observations"))
        connection.execute(text("ALTER TABLE contact_observations ENABLE TRIGGER immutable_rows"))
        connection.execute(text("DELETE FROM agent_resume_intents"))
        connection.execute(text("DELETE FROM agent_questions"))
        standalone = (
            "SELECT id FROM agent_sessions WHERE task_id IS NULL AND opportunity_id IS NULL"
        )
        connection.execute(text(f"DELETE FROM agent_messages WHERE session_id IN ({standalone})"))
        connection.execute(
            text(f"UPDATE agent_runs SET session_id=NULL WHERE session_id IN ({standalone})")
        )
        connection.execute(text(f"DELETE FROM agent_sessions WHERE id IN ({standalone})"))
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


def test_waiting_task_downgrade_preserves_explicit_state(engine, migration_config):
    clear_question_fixtures(engine)
    with Session(engine) as db, db.begin():
        actor = Actor(kind="human", display_name="Synthetic waiting migration owner")
        db.add(actor)
        db.flush()
        task = Task(owner_id=actor.id, title="Synthetic external dependency", state="waiting")
        db.add(task)
        db.flush()
        task_id, actor_id = task.id, actor.id
    try:
        with pytest.raises(RuntimeError, match="Resolve waiting tasks"):
            command.downgrade(migration_config, "0036_email_delivery")
        with Session(engine) as db:
            assert db.get(Task, task_id).state == "waiting"
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": task_id})
            connection.execute(text("DELETE FROM actors WHERE id=:id"), {"id": actor_id})
    command.downgrade(migration_config, "0036_email_delivery")
    command.upgrade(migration_config, "head")
    command.check(migration_config)


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


def test_linkedin_upgrade_preserves_limits_and_immutable_default_rates(engine, migration_config):
    from command_center.db.spending import SpendingPolicy, SpendingRateCard

    clear_question_fixtures(engine)
    command.downgrade(migration_config, "0031_chat_context")
    owners = []
    with Session(engine) as db, db.begin():
        for default in (True, False):
            owner_id = uuid4()
            db.add(Actor(id=owner_id, kind="human", display_name="Synthetic plan owner"))
            db.flush()
            card = SpendingRateCard.create(
                db,
                owner_id=owner_id,
                name="Standard Developer Rates" if default else "Custom rates",
                source_label="Default Plan" if default else "Synthetic custom plan",
                rates={"models": [], "tools": [{"slug": "GMAIL_GET_PROFILE", "fixed_micros": 17}]},
                request_id=uuid4(),
            )
            SpendingPolicy.configure(
                db,
                owner_id=owner_id,
                rate_card_id=card.id,
                monthly_limit_micros=0,
                default_work_limit_micros=23,
                active=False,
                request_id=uuid4(),
                expected_version=None,
            )
            owners.append((owner_id, card.id, default))
    command.upgrade(migration_config, "head")
    with Session(engine) as db:
        for owner_id, original_id, default in owners:
            policy = db.get(SpendingPolicy, owner_id)
            assert not policy.active
            assert policy.monthly_limit_micros == 0
            assert policy.default_work_limit_micros == 23
            old = db.get(SpendingRateCard, original_id)
            assert old.rates["tools"] == [{"slug": "GMAIL_GET_PROFILE", "fixed_micros": 17}]
            assert (policy.active_rate_card_id != original_id) == default
            current = db.get(SpendingRateCard, policy.active_rate_card_id)
            assert current.tool_rate("GMAIL_GET_PROFILE") == 17
            if default:
                assert current.tool_rate("LINKEDIN_WHO_AM_I") == 10_000
                assert current.tool_rate("LINKEDIN_CREATE_LINKED_IN_POST") == 10_000
                assert current.tool_rate("COMPOSIO_SESSION_CREATE") == 10_000
                assert current.tool_rate("GMAIL_FETCH_EMAILS") == 10_000
                assert (
                    current.model_rate("openai", "gpt-6-sol")["output_per_million_micros"]
                    == 10_000_000
                )
                assert (
                    current.model_rate("typesafe", "jev-1.13.0")["input_per_million_micros"]
                    == 42_000
                )
                assert old.rates["models"] == []
                for provider, model in (("gateway", "typesafe-ai/jev"), ("venice", "jev-latest")):
                    assert current.model_rate(provider, model)["input_per_million_micros"] == 42_000
                    assert current.model_rate(provider, model)["output_per_million_micros"] == 0


def test_connection_note_downgrade_keeps_the_character_limit_contract(engine, migration_config):
    from command_center.db.crm import Contact
    from command_center.db.models import Task
    from command_center.db.record_work import RecordWork

    with Session(engine) as db, db.begin():
        owner = Actor(id=uuid4(), kind="human", display_name="Synthetic quick note owner")
        db.add(owner)
        db.flush()
        person = Contact(owner_id=owner.id, name="Synthetic Casey")
        task = Task(owner_id=owner.id, title="Draft connection note", state="open")
        db.add_all([person, task])
        db.flush()
        work = RecordWork(
            task_id=task.id,
            owner_id=owner.id,
            contact_id=person.id,
            channel="linkedin",
            connection_note=True,
        )
        db.add(work)
        task_id = task.id
    try:
        with pytest.raises(RuntimeError, match="preserve the request contract"):
            command.downgrade(migration_config, "0028_standalone_conversations")
        with Session(engine) as db:
            assert db.get(RecordWork, task_id).connection_note is True
    finally:
        with Session(engine) as db, db.begin():
            db.delete(db.get(RecordWork, task_id))
