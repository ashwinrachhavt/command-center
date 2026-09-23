"""Synthetic provider responses: no live discovery, credits, or contact data."""

from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.contact_discovery import ContactDiscoveryEvidence
from command_center.db.models import Actor
from command_center.integrations.contact_discovery import (
    ContactDiscoveryClient,
    ContactProviderError,
    professional_domain,
)
from command_center.main import create_app


@pytest.fixture
def discovery(settings, engine):
    owner = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner, kind="human", display_name="Synthetic discovery owner"))
    config = settings.model_copy(
        update={
            "apollo_api_key": SecretStr("synthetic-apollo"),
            "hunter_api_key": SecretStr("synthetic-hunter"),
        }
    )
    app = create_app(config)
    app.dependency_overrides[authenticate] = lambda: Identity(owner, "synthetic")
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path.endswith("api_search"):
            return httpx.Response(
                200,
                json={
                    "total_entries": 1,
                    "people": [
                        {
                            "id": "apollo-synthetic",
                            "first_name": "Taylor",
                            "last_name_obfuscated": "S***",
                            "title": "Engineering lead",
                            "has_email": True,
                            "email": "should-not-expose@example.com",
                            "organization": {"name": "Example"},
                        }
                    ],
                },
            )
        if request.url.path.endswith("people/match"):
            return httpx.Response(
                200,
                json={
                    "person": {
                        "id": "apollo-synthetic",
                        "name": "Taylor Synthetic",
                        "title": "Engineering lead",
                        "email": "taylor@example.com",
                        "email_status": "verified",
                        "linkedin_url": "https://linkedin.com/in/synthetic/",
                        "organization": {"name": "Example", "primary_domain": "example.com"},
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "domain": "example.com",
                    "organization": "Example",
                    "emails": [
                        {
                            "value": "taylor@example.com",
                            "first_name": "Taylor",
                            "last_name": "Synthetic",
                            "position": "Engineering lead",
                            "confidence": 91,
                            "verification": {"status": "accept_all"},
                            "sources": [{"uri": "https://example.com/team"}],
                        }
                    ],
                },
                "meta": {"results": 1},
            },
        )

    with TestClient(app) as client:
        client.actor_id = owner
        client.calls = calls
        client.app.state.contact_discovery = ContactDiscoveryClient(
            httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            apollo_key="synthetic-apollo",
            hunter_key="synthetic-hunter",
        )
        yield client
        client.portal.call(client.app.state.contact_discovery.http.aclose)


def post(client, route, body, key=None):
    return client.post(
        f"/api/v1/contact-discovery/{route}",
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def test_search_preview_reveal_import_and_cross_provider_dedup(discovery, engine):
    body = {
        "provider": "apollo",
        "domain": "https://www.example.com/careers",
        "title": "Engineering lead",
    }
    key = uuid4()
    response = post(discovery, "search", body, key)
    assert response.status_code == 200, response.text
    found = response.json()
    assert found["result"]["items"][0]["email"] is None
    assert found["query"]["domain"] == "example.com"
    assert post(discovery, "search", body, key).json() == found
    cached = post(discovery, "search", body).json()
    assert cached["cached"] and cached["source_version_id"] == found["source_version_id"]
    assert len(discovery.calls) == 1
    selection = {"source_version_id": found["source_version_id"], "external_id": "apollo-synthetic"}
    assert post(discovery, "import", selection).status_code == 422
    revealed = post(discovery, "reveal", selection).json()
    assert revealed["result"]["items"][0]["email"] == "taylor@example.com"
    assert discovery.calls[-1].url.params["reveal_personal_emails"] == "false"
    assert discovery.calls[-1].url.params["reveal_phone_number"] == "false"
    selection["source_version_id"] = revealed["source_version_id"]
    key = uuid4()
    imported = post(discovery, "import", selection, key).json()
    assert imported["created"] and imported["contact"]["name"] == "Taylor Synthetic"
    assert post(discovery, "import", selection, key).json() == imported
    assert post(discovery, "import", selection).json()["created"] is False
    hunter = post(discovery, "search", {"provider": "hunter", "domain": "example.com"}).json()
    person = hunter["result"]["items"][0]
    assert person["email_status"] == "accept_all" and person["sources"] == [
        "https://example.com/team"
    ]
    matched = post(
        discovery,
        "import",
        {"source_version_id": hunter["source_version_id"], "external_id": person["external_id"]},
    ).json()
    assert matched["created"] is False and matched["contact"] == imported["contact"]
    assert len(discovery.get("/api/v1/contact-discovery/recent").json()) == 3
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ContactDiscoveryEvidence)
                .where(ContactDiscoveryEvidence.owner_id == discovery.actor_id)
            )
            == 2
        )


def test_foreign_sources_unknown_outcomes_and_key_conflicts_are_not_replayed(
    discovery, engine, mocker
):
    body = {"provider": "hunter", "domain": "example.com"}
    key = uuid4()
    found = post(discovery, "search", body, key).json()
    assert (
        post(discovery, "search", {**body, "domain": "different.example.com"}, key).status_code
        == 409
    )
    assert (
        post(
            discovery, "import", {"source_version_id": str(uuid4()), "external_id": "fake"}
        ).status_code
        == 404
    )
    other = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other, kind="human", display_name="Other synthetic owner"))
    discovery.app.dependency_overrides[authenticate] = lambda: Identity(other, "other")
    assert discovery.get("/api/v1/contact-discovery/recent").json() == []
    assert (
        post(
            discovery,
            "import",
            {"source_version_id": found["source_version_id"], "external_id": "taylor@example.com"},
        ).status_code
        == 404
    )
    failing = mocker.patch.object(
        discovery.app.state.contact_discovery,
        "search",
        side_effect=ContactProviderError("outcome_unknown", "Synthetic timeout", uncertain=True),
    )
    key = uuid4()
    assert post(discovery, "search", body, key).status_code == 502
    retry = post(discovery, "search", body, key)
    assert retry.status_code == 409 and "unknown" in retry.text
    assert failing.call_count == 1


def test_discovery_requires_config_and_human_intent(discovery):
    discovery.app.state.settings.hunter_api_key = SecretStr("")
    providers = discovery.get("/api/v1/contact-discovery/providers").json()
    assert providers[1]["configured"] is False
    assert "synthetic-apollo" not in str(providers)
    assert (
        post(discovery, "search", {"provider": "hunter", "domain": "example.com"}).status_code
        == 409
    )
    assert (
        post(
            discovery,
            "search",
            {"provider": "apollo", "domain": "https://user:password@example.com"},
        ).status_code
        == 422
    )
    assert not discovery.calls
    discovery.app.dependency_overrides[authenticate] = lambda: Identity(
        discovery.actor_id, "agent", run_id=uuid4()
    )
    assert discovery.get("/api/v1/contact-discovery/providers").status_code == 403
    assert (
        post(discovery, "search", {"provider": "apollo", "domain": "example.com"}).status_code
        == 403
    )


def test_provider_claims_do_not_overwrite_manual_fields(discovery):
    existing = discovery.post(
        "/api/v1/contacts",
        json={
            "name": "My chosen name",
            "email": "taylor@example.com",
            "notes": "Private context",
            "relationship": "warm",
        },
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    found = post(discovery, "search", {"provider": "hunter", "domain": "example.com"}).json()
    result = post(
        discovery,
        "import",
        {"source_version_id": found["source_version_id"], "external_id": "taylor@example.com"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["contact"] == existing
    assert result.json()["created"] is False


@pytest.mark.anyio
async def test_adapter_redacts_errors_and_rejects_bad_provider_shapes():
    for status, payload in [
        (429, {"error": "credential=private"}),
        (302, {}),
        (200, {"total_entries": "invalid", "people": []}),
    ]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request, status=status, payload=payload: httpx.Response(status, json=payload)
            )
        ) as http:
            adapter = ContactDiscoveryClient(http, apollo_key="never-in-errors")
            with pytest.raises(ContactProviderError) as caught:
                await adapter.search("apollo", domain="example.com")
            assert "private" not in str(caught.value) and "never-in-errors" not in str(caught.value)
    assert professional_domain("HTTPS://www.Example.com/path") == "example.com"
    person = ContactDiscoveryClient.hunter_person(
        {"value": "not-an-email", "verification": "bad", "sources": "bad"},
        domain="example.com",
        company=None,
    )
    assert person.email is None and person.sources == [] and person.email_status == "unknown"


def test_fill_missing_is_explicit_versioned_and_keeps_existing_values(discovery):
    existing = discovery.post(
        "/api/v1/contacts",
        json={
            "name": "My chosen name",
            "linkedin_url": "https://www.linkedin.com/in/synthetic",
            "notes": "My own context",
        },
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    found = post(discovery, "search", {"provider": "apollo", "domain": "example.com"}).json()
    revealed = post(
        discovery,
        "reveal",
        {"source_version_id": found["source_version_id"], "external_id": "apollo-synthetic"},
    ).json()
    selection = {
        "source_version_id": revealed["source_version_id"],
        "external_id": "apollo-synthetic",
    }
    body = {
        **selection,
        "contact_id": existing["id"],
        "expected_version": existing["row_version"],
        "fields": ["email"],
    }
    assert post(discovery, "fill-missing", body).status_code == 404
    matched = post(discovery, "import", selection).json()
    assert matched["contact"]["email"] is None and matched["created"] is False
    key = uuid4()
    filled = post(discovery, "fill-missing", body, key)
    assert filled.status_code == 200, filled.text
    assert filled.json()["email"] == "taylor@example.com"
    assert filled.json()["name"] == existing["name"] and filled.json()["notes"] == existing["notes"]
    assert post(discovery, "fill-missing", body, key).json() == filled.json()
    assert post(discovery, "fill-missing", body).status_code == 409
    assert (
        post(
            discovery, "fill-missing", {**body, "expected_version": filled.json()["row_version"]}
        ).status_code
        == 409
    )
    evidence = discovery.get(f"/api/v1/contact-discovery/contacts/{existing['id']}/evidence").json()
    assert evidence[0]["source_version_id"] == selection["source_version_id"]
    assert evidence[0]["prospect"]["name"] == "Taylor Synthetic"
