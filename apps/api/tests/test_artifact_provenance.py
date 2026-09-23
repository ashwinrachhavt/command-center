"""Exact source-version lineage for generic agent and human drafts."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import Artifact, ArtifactDerivation, ArtifactVersion
from command_center.db.models import Actor, AuditEvent
from command_center.main import create_app


@pytest.fixture
def client(settings, engine):
    owner_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner_id, kind="human", display_name="Synthetic draft owner"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(owner_id, "synthetic-draft-owner")
    with TestClient(app) as http:
        http.owner_id = owner_id
        yield http


def create_artifact(client, *, title: str, text: str, source_version_ids=None, key=None):
    payload = {
        "title": title,
        "kind": "research",
        "sensitivity": "private",
        "text": text,
    }
    if source_version_ids is not None:
        payload["source_version_ids"] = [str(item) for item in source_version_ids]
    response = client.post(
        "/api/v1/artifacts",
        headers={"Idempotency-Key": str(key or uuid4())},
        json=payload,
    )
    return response, payload


def latest_version(client, artifact_id):
    response = client.get(f"/api/v1/artifacts/{artifact_id}/versions")
    assert response.status_code == 200, response.text
    return response.json()[0]


def test_draft_pins_owned_sources_replays_and_survives_later_revisions(client, engine):
    source_response, _ = create_artifact(client, title="Saved source", text="Original source")
    assert source_response.status_code == 201, source_response.text
    source = source_response.json()
    source_v1 = latest_version(client, source["id"])

    key = uuid4()
    draft_response, payload = create_artifact(
        client,
        title="Grounded draft",
        text="Draft grounded in the original source.",
        source_version_ids=[source_v1["id"]],
        key=key,
    )
    assert draft_response.status_code == 201, draft_response.text
    replay = client.post(
        "/api/v1/artifacts",
        headers={"Idempotency-Key": str(key)},
        json=payload,
    )
    assert replay.status_code == 201 and replay.json() == draft_response.json()
    draft = draft_response.json()
    draft_v1 = latest_version(client, draft["id"])
    assert draft_v1["input_version_ids"] == [source_v1["id"]]

    source_revision = client.post(
        f"/api/v1/artifacts/{source['id']}/versions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "text": "Later source revision",
            "based_on_version_id": source_v1["id"],
            "expected_version": source["row_version"],
        },
    )
    assert source_revision.status_code == 201, source_revision.text
    source_v2 = source_revision.json()

    draft_revision = client.post(
        f"/api/v1/artifacts/{draft['id']}/versions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "text": "Human-edited grounded draft.",
            "based_on_version_id": draft_v1["id"],
            "expected_version": draft["row_version"],
        },
    )
    assert draft_revision.status_code == 201, draft_revision.text
    draft_v2 = draft_revision.json()
    assert draft_v2["input_version_ids"] == [draft_v1["id"]]

    lineage = client.get(f"/api/v1/versions/{draft_v2['id']}/lineage").json()
    lineage_by_id = {item["version_id"]: item for item in lineage}
    assert lineage_by_id[draft_v1["id"]]["method"] == "human.edit"
    assert lineage_by_id[source_v1["id"]]["method"] == "agent.draft"
    assert source_v2["id"] not in lineage_by_id
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ArtifactDerivation)
                .where(
                    ArtifactDerivation.output_version_id == draft_v1["id"],
                    ArtifactDerivation.method == "agent.draft",
                )
            )
            == 1
        )


def test_draft_rejects_missing_foreign_and_repeated_source_versions(client, engine):
    owned_response, _ = create_artifact(client, title="Owned source", text="Owned")
    owned_version = latest_version(client, owned_response.json()["id"])
    foreign_owner_id = uuid4()
    with Session(engine, expire_on_commit=False) as db, db.begin():
        db.add(Actor(id=foreign_owner_id, kind="human", display_name="Foreign draft owner"))
        db.flush()
        foreign = Artifact.draft(
            db,
            record_id=uuid4(),
            owner_id=foreign_owner_id,
            title="Foreign source",
            kind="source",
            sensitivity="private",
            text="Foreign",
            document_type_id=None,
            request_id=uuid4(),
        )
        foreign_version_id = db.scalar(
            select(ArtifactVersion.id).where(ArtifactVersion.artifact_id == foreign.id)
        )
        assert foreign_version_id is not None

    invalid_sources = [
        [uuid4()],
        [foreign_version_id],
        [owned_version["id"], owned_version["id"]],
        [uuid4() for _ in range(21)],
    ]
    for index, version_ids in enumerate(invalid_sources):
        response, _ = create_artifact(
            client,
            title=f"Invalid grounded draft {index}",
            text="Must not persist",
            source_version_ids=version_ids,
        )
        assert response.status_code == 422
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(
                    Artifact.owner_id == client.owner_id,
                    Artifact.title.like("Invalid grounded draft%"),
                )
            )
            == 0
        )


def test_ungrounded_draft_has_no_source_lineage(client):
    response, _ = create_artifact(client, title="Ungrounded draft", text="No saved source")
    assert response.status_code == 201, response.text
    version = latest_version(client, response.json()["id"])
    assert version["input_version_ids"] == []
    lineage = client.get(f"/api/v1/versions/{version['id']}/lineage")
    assert lineage.status_code == 200 and lineage.json() == []


def test_library_review_queue_tracks_only_the_latest_version(client):
    response, _ = create_artifact(client, title="Review this brief", text="First draft")
    artifact = response.json()
    version = latest_version(client, artifact["id"])
    reviewed = client.post(
        f"/api/v1/versions/{version['id']}/reviews",
        headers={"Idempotency-Key": str(uuid4())},
        json={"decision": "approved", "reason": "Checked the saved evidence."},
    )
    assert reviewed.status_code == 201, reviewed.text
    approved = client.get(
        "/api/v1/artifacts", params={"collection": "library", "review": "approved"}
    )
    assert approved.status_code == 200, approved.text
    assert [item["id"] for item in approved.json()["items"]] == [artifact["id"]]
    assert approved.json()["items"][0]["review_status"] == "approved"
    assert client.get(f"/api/v1/artifacts/{artifact['id']}").json()["review_status"] == "approved"
    revision = client.post(
        f"/api/v1/artifacts/{artifact['id']}/versions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "text": "Changed claims need another review.",
            "based_on_version_id": version["id"],
            "expected_version": artifact["row_version"],
        },
    )
    assert revision.status_code == 201, revision.text
    assert (
        client.get(
            "/api/v1/artifacts", params={"collection": "library", "review": "approved"}
        ).json()["total"]
        == 0
    )
    pending = client.get(
        "/api/v1/artifacts", params={"collection": "library", "review": "unreviewed"}
    ).json()
    assert pending["total"] == 1
    assert pending["items"][0]["review_status"] == "unreviewed"


def test_library_includes_message_outputs_and_generated_filter_uses_audit(client, engine):
    response = client.post(
        "/api/v1/artifacts",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "kind": "message",
            "title": "Synthetic agent draft",
            "sensitivity": "private",
            "text": "An introduction to review.",
        },
    )
    assert response.status_code == 201, response.text
    artifact = response.json()
    create_artifact(client, title="My own notes", text="Human-authored text")
    with Session(engine) as db, db.begin():
        db.add(
            AuditEvent(
                actor_id=client.owner_id,
                action="artifact.version_created",
                subject_type="artifacts",
                subject_id=artifact["id"],
                request_id=uuid4(),
                details={"version": 1, "agent_run_id": str(uuid4())},
            )
        )
    library = client.get("/api/v1/artifacts", params={"collection": "library"}).json()
    assert library["total"] == 2
    assert artifact["id"] in [item["id"] for item in library["items"]]
    generated = client.get("/api/v1/artifacts", params={"collection": "generated"})
    assert generated.status_code == 200, generated.text
    assert [item["id"] for item in generated.json()["items"]] == [artifact["id"]]
    assert client.get("/api/v1/artifacts", params={"collection": "vault"}).json()["total"] == 0
