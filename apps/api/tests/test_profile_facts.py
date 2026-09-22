"""Synthetic regressions for reviewed candidate profile facts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.idempotency import RequestReceipt
from command_center.db.models import Actor
from command_center.db.profile_facts import ProfileFact, ProfileFactReview, ProfileFactRevision
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic candidate"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic-candidate")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def post(client, path, body, *, key=None):
    return client.post(
        "/api/v1/" + path,
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def create_fact(client, **overrides):
    body = {"field": "headline", "value": "Synthetic systems engineer"} | overrides
    response = post(client, "profile/facts", body)
    assert response.status_code == 201, response.text
    return response.json()


def source_version(engine, owner_id, *, text="Built synthetic distributed systems."):
    artifact_id = uuid4()
    version_id = uuid4()
    with Session(engine) as db, db.begin():
        artifact = Artifact(
            id=artifact_id,
            owner_id=owner_id,
            created_by_id=owner_id,
            title="Synthetic extraction",
            kind="source",
            sensitivity="private",
        )
        db.add(artifact)
        db.flush()
        version = ArtifactVersion.from_payload(
            artifact_id=artifact_id,
            version=1,
            payload={"text": text, "document": {"synthetic": True}},
            schema_key="docling.document.v1",
            created_by_id=owner_id,
        )
        version.id = version_id
        db.add(version)
    return version_id


def approve(client, fact, *, revision_id=None, decision="approved", reason=None):
    return post(
        client,
        f"profile/facts/{fact['id']}/reviews",
        {
            "expected_version": fact["row_version"],
            "revision_id": revision_id or fact["current"]["id"],
            "decision": decision,
            "reason": reason,
        },
    )


def test_manual_proposal_is_pending_idempotent_and_actor_owned(client, engine):
    key = uuid4()
    body = {"field": "full_name", "value": "Synthetic Person"}

    first = post(client, "profile/facts", body, key=key)
    assert first.status_code == 201, first.text
    fact = first.json()
    assert fact["field"] == "full_name"
    assert fact["row_version"] == 1
    assert fact["active"] is None
    assert fact["current"] | {"created_at": None} == {
        "id": fact["current"]["id"],
        "version": 1,
        "value": "Synthetic Person",
        "context": None,
        "source_version_id": None,
        "source_artifact_id": None,
        "source_excerpt": None,
        "valid_until": None,
        "review_state": "proposed",
        "created_at": None,
    }
    replay = post(client, "profile/facts", body, key=key)
    assert replay.status_code == 201
    assert replay.json() == fact
    assert post(client, "profile/facts", body | {"value": "Changed"}, key=key).status_code == 409

    stranger_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=stranger_id, kind="human", display_name="Synthetic stranger"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(stranger_id, "stranger")
    listing = client.get("/api/v1/profile/facts").json()
    assert listing["items"] == []
    assert client.get(f"/api/v1/profile/facts/{fact['id']}/versions").status_code == 404


def test_agent_proposals_require_owned_verbatim_text_evidence(client, engine):
    version_id = source_version(engine, client.actor_id)
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "agent:synthetic", run_id=uuid4()
    )

    assert create_fact(
        client,
        field="skill",
        value="Distributed systems",
        source_version_id=str(version_id),
        source_excerpt="synthetic distributed systems",
    )["current"]["source_version_id"] == str(version_id)
    assert (
        post(
            client,
            "profile/facts",
            {"field": "skill", "value": "Missing evidence"},
        ).status_code
        == 422
    )
    assert (
        post(
            client,
            "profile/facts",
            {
                "field": "skill",
                "value": "Invented evidence",
                "source_version_id": str(version_id),
                "source_excerpt": "This excerpt is absent.",
            },
        ).status_code
        == 422
    )

    stranger_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=stranger_id, kind="human", display_name="Synthetic source owner"))
    foreign_version_id = source_version(engine, stranger_id)
    assert (
        post(
            client,
            "profile/facts",
            {
                "field": "skill",
                "value": "Foreign evidence",
                "source_version_id": str(foreign_version_id),
                "source_excerpt": "synthetic distributed systems",
            },
        ).status_code
        == 422
    )


def test_pending_edits_and_rejections_preserve_active_revision_then_revoke_clears_it(
    client, engine
):
    fact = create_fact(client)
    approved_response = approve(client, fact)
    assert approved_response.status_code == 200, approved_response.text
    approved = approved_response.json()
    first_revision_id = approved["active"]["id"]

    edited_response = post(
        client,
        f"profile/facts/{fact['id']}/versions",
        {"expected_version": approved["row_version"], "value": "Synthetic staff engineer"},
    )
    assert edited_response.status_code == 201, edited_response.text
    edited = edited_response.json()
    assert edited["current"]["review_state"] == "proposed"
    assert edited["active"]["id"] == first_revision_id

    rejected_response = approve(
        client,
        edited,
        revision_id=edited["current"]["id"],
        decision="rejected",
        reason="Needs a narrower claim",
    )
    assert rejected_response.status_code == 200, rejected_response.text
    rejected = rejected_response.json()
    assert rejected["current"]["review_state"] == "rejected"
    assert rejected["active"]["id"] == first_revision_id

    revoked_response = approve(
        client,
        rejected,
        revision_id=first_revision_id,
        decision="revoked",
        reason="No longer current",
    )
    assert revoked_response.status_code == 200, revoked_response.text
    revoked = revoked_response.json()
    assert revoked["active"] is None
    assert revoked["current"]["review_state"] == "rejected"
    assert client.get("/api/v1/profile/facts/approved").json()["items"] == []

    with Session(engine) as db:
        fact_ids = select(ProfileFact.id).where(ProfileFact.owner_id == client.actor_id)
        assert db.scalar(select(func.count()).select_from(fact_ids.subquery())) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProfileFactRevision)
                .where(ProfileFactRevision.fact_id.in_(fact_ids))
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProfileFactReview)
                .where(ProfileFactReview.fact_id.in_(fact_ids))
            )
            == 3
        )


def test_only_humans_can_review_and_approved_list_excludes_expired_or_pending(client):
    pending = create_fact(client, field="skill", value="Pending skill")
    approved = approve(
        client,
        create_fact(client, field="skill", value="Approved skill"),
    ).json()
    expired = create_fact(
        client,
        field="experience",
        value="Expired experience",
        valid_until=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    assert approve(client, expired).status_code == 200

    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "agent:synthetic", run_id=uuid4()
    )
    assert approve(client, pending).status_code == 403

    items = client.get("/api/v1/profile/facts/approved").json()["items"]
    assert [(item["fact_id"], item["value"]) for item in items] == [
        (approved["id"], "Approved skill")
    ]


def test_scalar_approval_conflicts_and_contextual_answers_require_context(client):
    assert (
        post(
            client,
            "profile/facts",
            {"field": "answer", "value": "Yes"},
        ).status_code
        == 422
    )
    contextual = create_fact(
        client,
        field="answer",
        value="Authorized for this role",
        context="Are you authorized to work in the role's country?",
    )
    assert approve(client, contextual).status_code == 200

    first = create_fact(client, field="email", value="first@example.test")
    assert approve(client, first).status_code == 200
    second = create_fact(client, field="email", value="second@example.test")
    conflict = approve(client, second)
    assert conflict.status_code == 409


def test_stale_edit_and_review_are_rejected_without_extra_history(client, engine):
    fact = create_fact(client)
    first_edit = post(
        client,
        f"profile/facts/{fact['id']}/versions",
        {"expected_version": fact["row_version"], "value": "Current proposal"},
    )
    assert first_edit.status_code == 201
    assert (
        post(
            client,
            f"profile/facts/{fact['id']}/versions",
            {"expected_version": fact["row_version"], "value": "Stale proposal"},
        ).status_code
        == 409
    )
    assert approve(client, fact).status_code == 409

    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProfileFactRevision)
                .where(ProfileFactRevision.fact_id == UUID(fact["id"]))
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(RequestReceipt)
                .where(RequestReceipt.actor_id == client.actor_id)
            )
            == 2
        )
