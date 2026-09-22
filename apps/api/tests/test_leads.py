"""Synthetic regressions for the public job-lead vertical slice."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from command_center.core.capabilities import issue_run_token
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.crm import Company, Job, Opportunity
from command_center.db.evidence import SourceRecord
from command_center.db.idempotency import RequestReceipt
from command_center.db.models import Actor
from command_center.integrations.clients import ConnectionState, ProviderError
from command_center.integrations.public_research import PublicPage
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic lead tester"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic-lead")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def capture(client, body, key=None):
    return client.post(
        "/api/v1/leads/capture",
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def enrich(client, opportunity_id, key=None):
    return client.post(
        f"/api/v1/opportunities/{opportunity_id}/enrich",
        json={},
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def synthetic_lead(**overrides):
    return {
        "url": "https://jobs.example.com/roles/engineering-lead#description",
        "title": "Engineering Lead",
        "company_name": "Synthetic Orbit",
        "snippet": "Build a synthetic platform with a small engineering team.",
    } | overrides


def test_capture_replays_and_deduplicates_the_canonical_url(client, engine):
    company = client.post(
        "/api/v1/companies",
        json={"name": "Synthetic Orbit"},
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    key = uuid4()

    first_response = capture(client, synthetic_lead(), key)
    assert first_response.status_code == 201, first_response.text
    first = first_response.json()
    assert first["created"] is True
    assert first["company_id"] == company["id"]
    assert first["source"]["url"] == "https://jobs.example.com/roles/engineering-lead"
    assert first["source"]["excerpt"] == synthetic_lead()["snippet"]
    assert set(first["source"]) == {
        "id",
        "artifact_id",
        "version_id",
        "version",
        "url",
        "title",
        "provider",
        "retrieved_at",
        "excerpt",
    }

    replay = capture(client, synthetic_lead(), key)
    assert replay.status_code == 201
    assert replay.json() == first
    assert capture(client, synthetic_lead(title="Conflicting title"), key).status_code == 409

    duplicate = capture(
        client,
        synthetic_lead(
            url="https://jobs.example.com/roles/engineering-lead",
            title="A later search title",
            snippet="A later search snippet.",
        ),
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json() == first | {"created": False}

    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Company).where(Company.owner_id == client.actor_id)
            )
            == 1
        )
        assert (
            db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == client.actor_id))
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.owner_id == client.actor_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(SourceRecord)
                .where(SourceRecord.opportunity_id == UUID(first["opportunity_id"]))
            )
            == 1
        )
        job = db.get(Job, UUID(first["job_id"]))
        assert job is not None
        assert job.status == "unknown"
        assert job.description is None


def test_concurrent_capture_creates_one_lead_and_one_source(client, engine):
    body = synthetic_lead(
        url="https://careers.example.com/jobs/concurrent",
        title="Concurrent Systems Engineer",
        company_name="Synthetic Concurrency Labs",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: capture(client, body), range(2)))

    assert [response.status_code for response in responses] == [201, 201]
    payloads = [response.json() for response in responses]
    assert sorted(payload["created"] for payload in payloads) == [False, True]
    assert len({payload["company_id"] for payload in payloads}) == 1
    assert len({payload["job_id"] for payload in payloads}) == 1
    assert len({payload["opportunity_id"] for payload in payloads}) == 1
    assert len({payload["source"]["id"] for payload in payloads}) == 1

    opportunity_id = UUID(payloads[0]["opportunity_id"])
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(SourceRecord)
                .where(SourceRecord.opportunity_id == opportunity_id)
            )
            == 1
        )


def test_research_and_enrichment_are_owned_and_preserve_crm_facts(client, engine, mocker):
    captured = capture(
        client,
        synthetic_lead(
            url="https://jobs.example.com/roles/source-lineage",
            title="Source Lineage Engineer",
            company_name="Synthetic Evidence Works",
        ),
    ).json()
    opportunity_id = UUID(captured["opportunity_id"])
    job_id = UUID(captured["job_id"])
    with Session(engine) as db, db.begin():
        job = db.get(Job, job_id)
        assert job is not None
        job.status = "open"
        job.description = "User-entered CRM description."

    page = type(
        "PublicPage",
        (),
        {
            "url": "https://jobs.example.com/roles/source-lineage",
            "title": "Fetched Source Lineage Engineer",
            "markdown": "# Full fetched role\n\nPublic source detail that must remain immutable.",
            "provider": "public_http",
            "extraction_method": "html_text",
        },
    )()
    mocker.patch("command_center.api.leads.scrape_public", return_value=page)

    response = enrich(client, opportunity_id)
    assert response.status_code == 201, response.text
    enriched = response.json()
    assert enriched["provider"] == "public_http"
    assert enriched["title"] == page.title
    assert enriched["excerpt"] == page.markdown

    research = client.get(f"/api/v1/opportunities/{opportunity_id}/research")
    assert research.status_code == 200, research.text
    result = research.json()
    assert result["total"] == 2
    assert result["items"][0] == enriched

    with Session(engine) as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "open"
        assert job.description == "User-entered CRM description."
        source = db.get(SourceRecord, UUID(enriched["id"]))
        version = db.get(ArtifactVersion, UUID(enriched["version_id"]))
        artifact = db.get(Artifact, UUID(enriched["artifact_id"]))
        assert source is not None and version is not None and artifact is not None
        assert source.opportunity_id == opportunity_id
        assert source.artifact_version_id == version.id
        assert version.artifact_id == artifact.id
        assert artifact.owner_id == client.actor_id
        assert version.payload == {"text": page.markdown}

    with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
        db.execute(
            update(SourceRecord)
            .where(SourceRecord.id == UUID(enriched["id"]))
            .values(locator="https://tampered.example.com")
        )

    stranger_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=stranger_id, kind="human", display_name="Synthetic stranger"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(stranger_id, "stranger")
    assert client.get(f"/api/v1/opportunities/{opportunity_id}/research").status_code == 404
    assert enrich(client, opportunity_id).status_code == 404


def test_failed_enrichment_leaves_facts_sources_and_receipts_unchanged(client, engine, mocker):
    captured = capture(
        client,
        synthetic_lead(
            url="https://jobs.example.com/roles/unavailable",
            title="Unavailable Source Engineer",
            company_name="Synthetic Failure Co",
        ),
    ).json()
    opportunity_id = UUID(captured["opportunity_id"])
    job_id = UUID(captured["job_id"])
    key = uuid4()
    mocker.patch(
        "command_center.api.leads.scrape_public",
        side_effect=ProviderError("public_http", ConnectionState.UNAVAILABLE),
    )

    response = enrich(client, opportunity_id, key)
    assert response.status_code == 503

    with Session(engine) as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "unknown"
        assert job.description is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(SourceRecord)
                .where(SourceRecord.opportunity_id == opportunity_id)
            )
            == 1
        )
        assert db.get(RequestReceipt, (client.actor_id, key)) is None


@pytest.mark.parametrize("lease_change", ["cancelled", "replaced"])
def test_enrichment_fences_the_original_agent_lease_after_fetch(
    client, settings, engine, mocker, lease_change
):
    captured = capture(
        client,
        synthetic_lead(
            url=f"https://jobs.example.com/roles/lease-{lease_change}",
            title="Lease Fence Engineer",
            company_name="Synthetic Lease Safety",
        ),
    ).json()
    opportunity_id = UUID(captured["opportunity_id"])
    with Session(engine, expire_on_commit=False) as db, db.begin():
        run = AgentRun.enqueue(
            db,
            record_id=uuid4(),
            owner_id=client.actor_id,
            prompt="Enrich the synthetic lead.",
            profile="research",
            configuration={"tools": ["enrich_lead"]},
            revision="synthetic",
            request_id=uuid4(),
        )
        db.flush()
        assert AgentRun.claim(db, run.id) is not None
        db.flush()
        assert run.lease_id is not None
        run_id, original_lease = run.id, run.lease_id

    async def cancel_during_fetch(_client, url):
        with Session(engine) as db, db.begin():
            current = db.get(AgentRun, run_id)
            assert current is not None
            if lease_change == "cancelled":
                current.finish("cancelled")
            else:
                current.lease_id = uuid4()
        return PublicPage(
            url=url,
            title="Fetched Lease Fence Engineer",
            markdown="This content must not be attached after the original lease is lost.",
        )

    mocker.patch("command_center.api.leads.scrape_public", side_effect=cancel_during_fetch)
    key = uuid4()
    headers = {
        "Authorization": "Bearer " + issue_run_token(settings, run_id, original_lease),
        "Idempotency-Key": str(key),
    }
    with TestClient(create_app(settings)) as agent_client:
        response = agent_client.post(
            f"/api/v1/opportunities/{opportunity_id}/enrich", json={}, headers=headers
        )

    assert response.status_code == 401, response.text
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(SourceRecord)
                .where(SourceRecord.opportunity_id == opportunity_id)
            )
            == 1
        )
        assert db.get(RequestReceipt, (client.actor_id, key)) is None
