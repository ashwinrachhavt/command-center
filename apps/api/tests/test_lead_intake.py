"""Private conversational intake: linked records, exact sources and safe retries."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.conversations import AgentMessage, AgentSession
from command_center.db.crm import Company, Contact, Job, Opportunity
from command_center.db.evidence import SourceRecord
from command_center.db.models import Actor, AuditEvent
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic intake tester"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic-intake")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def intake(client, body, key=None):
    return client.post(
        "/api/v1/leads/intake",
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def lead(**changes):
    return {
        "title": "Fractional product engagement",
        "company_name": "Northstar Studio",
        "company_domain": "northstar.example",
        "contact": {"name": "Jamie Rivera", "email": "jamie@northstar.example"},
        "source_text": "  Jamie Rivera at Northstar Studio is seeking fractional product help.\n",
    } | changes


def count(db, model, actor_id):
    return db.scalar(select(func.count()).select_from(model).where(model.owner_id == actor_id))


def test_pasted_lead_is_private_linked_and_replays_without_a_fake_job(client, engine):
    body = lead()
    key = uuid4()
    response = intake(client, body, key)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["created"] == {
        "company": True,
        "contact": True,
        "job": False,
        "opportunity": True,
        "source": True,
    }
    assert result["job_id"] is None
    assert result["links"]["opportunity"].endswith(
        f"inspect=opportunities:{result['opportunity_id']}"
    )
    assert intake(client, body, key).json() == result
    assert intake(client, lead(title="Different intent"), key).status_code == 409
    duplicate = intake(client, body)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["opportunity_id"] == result["opportunity_id"]
    assert not any(duplicate.json()["created"].values())
    with Session(engine) as db:
        opportunity = db.get(Opportunity, UUID(result["opportunity_id"]))
        assert opportunity.contact_id == UUID(result["contact_id"])
        assert opportunity.company_id == UUID(result["company_id"])
        version = db.get(ArtifactVersion, UUID(result["source"]["version_id"]))
        artifact = db.get(Artifact, version.artifact_id)
        assert version.payload["text"] == body["source_text"]
        assert artifact.sensitivity == "private"
        source = db.get(SourceRecord, UUID(result["source"]["id"]))
        assert source.account_scope == "private"
        assert count(db, Company, client.actor_id) == 1
        assert count(db, Contact, client.actor_id) == 1
        assert count(db, Opportunity, client.actor_id) == 1
        assert count(db, Job, client.actor_id) == 0


def test_strong_contact_identity_reuses_without_overwriting_human_fields(client, engine):
    first = intake(client, lead()).json()
    with Session(engine) as db, db.begin():
        contact = db.get(Contact, UUID(first["contact_id"]))
        contact.notes = "Human-owned notes"
        contact.name = "Jamie — preferred name"
    second = intake(
        client,
        lead(
            contact={
                "name": "A source spelling",
                "email": "JAMIE@northstar.example",
                "notes": "Unverified",
            }
        ),
    )
    assert second.status_code == 201, second.text
    assert second.json()["contact_id"] == first["contact_id"]
    with Session(engine) as db:
        contact = db.get(Contact, UUID(first["contact_id"]))
        assert contact.notes == "Human-owned notes"
        assert contact.name == "Jamie — preferred name"


def test_same_named_people_in_one_source_keep_distinct_strong_identities(client):
    first = intake(client, lead())
    second = intake(
        client,
        lead(contact={"name": "Jamie Rivera", "email": "other-jamie@northstar.example"}),
    )
    assert first.status_code == second.status_code == 201, second.text
    assert first.json()["contact_id"] != second.json()["contact_id"]


@pytest.mark.parametrize("domain", ["-", "unknown", "bad..example", "-bad.example"])
def test_placeholder_domains_do_not_become_company_identity(client, domain):
    response = intake(client, lead(company_domain=domain))
    assert response.status_code == 422, response.text


def test_empty_linkedin_profile_is_not_a_person_identity(client):
    response = intake(
        client, lead(contact={"name": "Jamie", "linkedin_url": "https://linkedin.com/in/"})
    )
    assert response.status_code == 422, response.text


def test_owned_saved_source_is_read_exactly_and_other_actor_is_rejected(client, engine):
    artifact = client.post(
        "/api/v1/artifacts",
        json={
            "kind": "source",
            "title": "Saved page",
            "text": "Exact saved page text",
            "sensitivity": "private",
        },
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    with Session(engine) as db:
        version_id = db.scalar(
            select(ArtifactVersion.id).where(ArtifactVersion.artifact_id == UUID(artifact["id"]))
        )
    body = lead(source_text=None, source_version_id=str(version_id))
    response = intake(client, body)
    assert response.status_code == 201, response.text
    with Session(engine) as db:
        source_version = db.get(ArtifactVersion, UUID(response.json()["source"]["version_id"]))
        assert source_version.payload["text"] == "Exact saved page text"
    with Session(engine) as db, db.begin():
        other = Actor(id=uuid4(), kind="human", display_name="Other synthetic owner")
        db.add(other)
        db.flush()
        foreign = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=other.id,
            title="Other owner's text",
            kind="source",
            sensitivity="private",
            text="Private other data",
            document_type_id=None,
            request_id=uuid4(),
        )
        foreign_version_id = db.scalar(
            select(ArtifactVersion.id).where(ArtifactVersion.artifact_id == foreign.id)
        )
    assert (
        intake(
            client, lead(source_text=None, source_version_id=str(foreign_version_id))
        ).status_code
        == 404
    )


def test_conflicting_identifiers_roll_back_the_whole_intake(client, engine):
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                Contact(owner_id=client.actor_id, name="First", email="jamie@northstar.example"),
                Contact(
                    owner_id=client.actor_id,
                    name="Second",
                    linkedin_url="https://www.linkedin.com/in/jamie-example",
                ),
            ]
        )
    response = intake(
        client,
        lead(
            contact={
                "name": "Jamie Rivera",
                "email": "jamie@northstar.example",
                "linkedin_url": "https://www.linkedin.com/in/jamie-example/",
            }
        ),
    )
    assert response.status_code == 409, response.text
    with Session(engine) as db:
        assert count(db, Company, client.actor_id) == 0
        assert count(db, Opportunity, client.actor_id) == 0
        assert count(db, Artifact, client.actor_id) == 0


def test_missing_company_returns_actionable_error_without_creating_placeholder(client, engine):
    response = intake(client, lead(company_name=None, company_domain=None))
    assert response.status_code == 422
    assert "company" in response.text.lower()
    with Session(engine) as db:
        assert count(db, Company, client.actor_id) == 0


def test_concurrent_requests_reuse_one_aggregate(client, engine):
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: intake(client, lead()), range(2)))
    assert all(response.status_code == 201 for response in responses), [r.text for r in responses]
    assert responses[0].json()["opportunity_id"] == responses[1].json()["opportunity_id"]
    with Session(engine) as db:
        assert count(db, Company, client.actor_id) == 1
        assert count(db, Contact, client.actor_id) == 1
        assert count(db, Opportunity, client.actor_id) == 1


def test_name_only_match_does_not_merge_people(client, engine):
    with Session(engine) as db, db.begin():
        db.add(Contact(owner_id=client.actor_id, name="Jamie Rivera"))
    response = intake(client, lead(contact={"name": "Jamie Rivera"}))
    assert response.status_code == 409, response.text
    assert "contact_id" in response.text


def test_existing_job_lead_gets_requested_contact_without_losing_notes(client, engine):
    url = "https://jobs.example.com/product"
    original = client.post(
        "/api/v1/leads/capture",
        json={"url": url, "title": "Product Lead", "company_name": "Northstar Studio"},
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    with Session(engine) as db, db.begin():
        db.get(Opportunity, UUID(original["opportunity_id"])).notes = "Keep my assessment"
    response = intake(client, lead(job={"title": "Product Lead", "url": url}))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["opportunity_id"] == original["opportunity_id"]
    assert result["job_id"] == original["job_id"]
    with Session(engine) as db:
        opportunity = db.get(Opportunity, UUID(result["opportunity_id"]))
        assert opportunity.contact_id == UUID(result["contact_id"])
        assert opportunity.notes == "Keep my assessment"


def test_explicit_existing_job_needs_no_invented_url(client, engine):
    first = intake(client, lead()).json()
    with Session(engine) as db, db.begin():
        job = Job(
            owner_id=client.actor_id,
            company_id=UUID(first["company_id"]),
            title="Privately discussed role",
            source_url=None,
            status="unknown",
        )
        db.add(job)
        db.flush()
        opportunity = db.get(Opportunity, UUID(first["opportunity_id"]))
        opportunity.job_id = job.id
        job_id = job.id
    response = intake(
        client,
        lead(job_id=str(job_id), opportunity_id=first["opportunity_id"]),
    )
    assert response.status_code == 201, response.text
    assert response.json()["job_id"] == str(job_id)
    assert not response.json()["created"]["job"]


def test_intake_does_not_reuse_other_owners_matching_identifiers(client, engine):
    with Session(engine) as db, db.begin():
        other = Actor(id=uuid4(), kind="human", display_name="Other synthetic workspace")
        db.add(other)
        db.flush()
        company = Company(owner_id=other.id, name="Northstar Studio", domain="northstar.example")
        db.add(company)
        db.flush()
        person = Contact(
            owner_id=other.id,
            name="Jamie Rivera",
            email="jamie@northstar.example",
            company_id=company.id,
        )
        db.add(person)
        db.flush()
        company_id, contact_id = company.id, person.id
    response = intake(client, lead())
    assert response.status_code == 201, response.text
    assert response.json()["company_id"] != str(company_id)
    assert response.json()["contact_id"] != str(contact_id)
    assert intake(client, lead(company_id=str(company_id))).status_code == 404


def test_saved_user_message_is_an_exact_source_without_echoing_the_paste(client, engine):
    original = "Please save this lead.\n  Jamie at Northstar needs fractional product help.\n"
    with Session(engine) as db, db.begin():
        conversation = AgentSession.open_chat(
            db,
            record_id=uuid4(),
            owner_id=client.actor_id,
            title="Synthetic lead intake",
            request_id=uuid4(),
        )
        message = AgentMessage(
            id=uuid4(),
            owner_id=client.actor_id,
            session_id=conversation.id,
            run_id=None,
            sequence=1,
            author="user",
            profile="lead",
            content=original,
        )
        db.add(message)
        message_id = message.id
    response = intake(client, lead(source_text=None, source_message_id=str(message_id)))
    assert response.status_code == 201, response.text
    with Session(engine) as db:
        source = db.get(ArtifactVersion, UUID(response.json()["source"]["version_id"]))
        assert source.payload["text"] == original
    assert response.json()["source"]["url"] == f"urn:command-center:message:{message_id}"
    with_url = intake(
        client,
        lead(
            source_text=None,
            source_message_id=str(message_id),
            source_url="https://northstar.example/team",
        ),
    )
    assert with_url.status_code == 201, with_url.text
    with Session(engine) as db:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.actor_id == client.actor_id,
                AuditEvent.action == "opportunity.source_captured",
                AuditEvent.details["source_record_id"].astext == with_url.json()["source"]["id"],
            )
        )
        assert event.details["source_message_id"] == str(message_id)
