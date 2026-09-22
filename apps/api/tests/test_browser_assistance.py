"""Browser protocol v2 preserves local values and pins exact resume bytes."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.base import utc_now
from command_center.db.browser import BrowserCommand, BrowserSnapshot, validate_numeric_answer
from command_center.db.models import Actor
from command_center.main import create_app


@pytest.fixture
def client(settings, engine, tmp_path: Path, mocker):
    from command_center.api import documents as document_api

    configured = settings.model_copy(update={"blob_store_path": tmp_path / "browser-blobs"})
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic browser owner"))
    app = create_app(configured)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    mocker.patch.object(document_api, "dispatch_import")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def human_post(client, path: str, body: dict, key=None):
    return client.post(
        "/api/v1/" + path,
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def pair(client, name: str = "Synthetic browser") -> dict[str, str]:
    pairing = human_post(client, "browser/pairings", {"name": name}).json()
    exchange = client.post("/api/v1/browser/pairings/exchange", json={"code": pairing["code"]})
    assert exchange.status_code == 200, exchange.text
    return {
        "device_id": exchange.json()["device_id"],
        "Authorization": "Bearer " + exchange.json()["token"],
    }


def share(
    client,
    headers: dict[str, str],
    *,
    file_accept: str = "text/plain",
    fields: list[dict] | None = None,
) -> dict:
    snapshot = {
        "id": str(uuid4()),
        "protocol_version": 2,
        "page_url": "https://jobs.example.test/apply",
        "title": "Synthetic application",
        "fields": fields
        or [
            {
                "id": "f0",
                "label": "Name",
                "type": "text",
                "value_state": "present",
            },
            {
                "id": "f1",
                "label": "Resume",
                "type": "file",
                "value_state": "empty",
                "accept": file_accept,
            },
        ],
    }
    response = client.post("/api/v1/browser/snapshots", json=snapshot, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_numeric_validation_rejects_out_of_browser_range() -> None:
    field = {
        "type": "number",
        "numeric_constraints": {
            "minimum": None,
            "maximum": None,
            "step": "1",
            "step_base": "0",
        },
    }
    with pytest.raises(ValueError, match="finite"):
        validate_numeric_answer(field, "1e999999")


def test_number_answers_use_exact_bounds_and_step_before_command_creation(client) -> None:
    device = pair(client)
    snapshot = share(
        client,
        device,
        fields=[
            {
                "id": "f0",
                "label": "Years of experience",
                "type": "number",
                "value_state": "empty",
                "numeric_constraints": {
                    "minimum": "0.1",
                    "maximum": "1.1",
                    "step": "0.2",
                    "step_base": "0.1",
                },
            }
        ],
    )
    path = "/api/v1/browser/device/commands"
    for value in ["NaN", "+1", "1.", "1e999", "0.0", "1.2", "0.2"]:
        rejected = client.post(
            path,
            json={"snapshot_id": snapshot["id"], "fields": {"f0": value}},
            headers={
                "Authorization": device["Authorization"],
                "Idempotency-Key": str(uuid4()),
            },
        )
        assert rejected.status_code == 422, rejected.text
    assert client.get(path, headers={"Authorization": device["Authorization"]}).json() == []

    accepted = client.post(
        path,
        json={"snapshot_id": snapshot["id"], "fields": {"f0": "3e-1"}},
        headers={
            "Authorization": device["Authorization"],
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["fields"] == {"f0": "3e-1"}


def upload_resume(client, content: bytes, title: str) -> dict:
    resume_type = next(
        item for item in client.get("/api/v1/document-types").json() if item["slug"] == "resume"
    )
    response = client.post(
        "/api/v1/documents/imports",
        data={"title": title, "document_type_id": resume_type["id"]},
        files={"file": ("resume.txt", content, "text/plain")},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_device_command_pins_exact_resume_bytes_and_terminal_results(client, engine) -> None:
    first_device = pair(client)
    second_device = pair(client, "Other synthetic browser")
    snapshot = share(client, first_device)
    first_content = b"first exact synthetic resume"
    first = upload_resume(client, first_content, "First synthetic resume")
    second = upload_resume(client, b"new default synthetic resume", "New synthetic resume")
    selected = human_post(
        client,
        "profile/default-resume",
        {"version_id": first["source_version_id"], "expected_version": 1},
    )
    assert selected.status_code == 200, selected.text

    first_device_headers = {
        "Authorization": first_device["Authorization"],
        "Idempotency-Key": str(uuid4()),
    }
    command = client.post(
        "/api/v1/browser/device/commands",
        json={
            "snapshot_id": snapshot["id"],
            "fields": {"f0": "Synthetic Person"},
            "uploads": {"f1": first["source_version_id"]},
            "replace_fields": ["f0"],
        },
        headers=first_device_headers,
    )
    assert command.status_code == 201, command.text
    command = command.json()
    assert command["upload_files"]["f1"]["version_id"] == first["source_version_id"]

    changed_default = human_post(
        client,
        "profile/default-resume",
        {
            "version_id": second["source_version_id"],
            "expected_version": selected.json()["row_version"],
        },
    )
    assert changed_default.status_code == 200, changed_default.text
    pending = client.get(
        "/api/v1/browser/device/commands",
        headers={"Authorization": first_device["Authorization"]},
    ).json()
    assert pending[0]["upload_files"]["f1"]["version_id"] == first["source_version_id"]

    other_headers = {"Authorization": second_device["Authorization"]}
    assert (
        client.post(
            f"/api/v1/browser/device/commands/{command['id']}/claim", headers=other_headers
        ).status_code
        == 404
    )
    path = f"/api/v1/browser/device/commands/{command['id']}"
    assert client.post(path + "/claim", headers=first_device_headers).status_code == 200
    assert client.get(path + "/files/f1", headers=other_headers).status_code == 404
    downloaded = client.get(path + "/files/f1", headers=first_device_headers)
    assert downloaded.status_code == 200
    assert downloaded.content == first_content

    result = {
        "state": "applied",
        "field_results": {
            "f0": {"status": "filled"},
            "f1": {"status": "uploaded"},
        },
    }
    response = client.post(path + "/result", json=result, headers=first_device_headers)
    assert response.status_code == 200
    response = client.post(path + "/result", json=result, headers=first_device_headers)
    assert response.status_code == 200
    changed = {**result, "state": "partial"}
    response = client.post(path + "/result", json=changed, headers=first_device_headers)
    assert response.status_code == 409
    assert client.get(path + "/files/f1", headers=first_device_headers).status_code == 404

    with Session(engine) as db:
        stored = db.get(BrowserCommand, UUID(command["id"]))
        assert stored is not None
        assert stored.upload_files["f1"]["sha256"] == command["upload_files"]["f1"]["sha256"]
        assert set(stored.field_results) == {"f0", "f1"}


def test_preserved_results_are_terminal_without_claiming_a_fill(client, engine) -> None:
    device = pair(client)
    snapshot = share(client, device)
    resume = upload_resume(client, b"synthetic preserved result resume", "Preserved result resume")

    def queue(body: dict) -> tuple[str, dict[str, str]]:
        headers = {
            "Authorization": device["Authorization"],
            "Idempotency-Key": str(uuid4()),
        }
        response = client.post(
            "/api/v1/browser/device/commands",
            json={"snapshot_id": snapshot["id"], **body},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        command_id = response.json()["id"]
        claim = client.post(
            f"/api/v1/browser/device/commands/{command_id}/claim",
            headers={"Authorization": device["Authorization"]},
        )
        assert claim.status_code == 200, claim.text
        return command_id, {"Authorization": device["Authorization"]}

    mixed_id, headers = queue(
        {
            "fields": {"f0": "Reviewed replacement"},
            "uploads": {"f1": resume["source_version_id"]},
            "replace_fields": ["f0"],
        }
    )
    mixed = {
        "state": "partial",
        "field_results": {
            "f0": {"status": "preserved", "detail": "Local edit preserved."},
            "f1": {"status": "uploaded", "detail": "Reviewed file attached."},
        },
    }
    path = f"/api/v1/browser/device/commands/{mixed_id}/result"
    response = client.post(path, json=mixed, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == mixed
    assert client.post(path, json=mixed, headers=headers).status_code == 200
    conflicting = {
        **mixed,
        "field_results": {
            **mixed["field_results"],
            "f0": {"status": "filled", "detail": "Must not replace preserved."},
        },
    }
    assert client.post(path, json=conflicting, headers=headers).status_code == 409

    preserved_id, headers = queue(
        {"fields": {"f0": "Reviewed replacement"}, "replace_fields": ["f0"]}
    )
    preserved = {
        "state": "rejected",
        "field_results": {
            "f0": {"status": "preserved", "detail": "Local edit preserved."},
        },
    }
    path = f"/api/v1/browser/device/commands/{preserved_id}/result"
    response = client.post(path, json=preserved, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == preserved
    assert client.post(path, json=preserved, headers=headers).status_code == 200
    assert (
        client.post(path, json={**preserved, "state": "applied"}, headers=headers).status_code
        == 409
    )

    with Session(engine) as db:
        mixed_record = db.get(BrowserCommand, UUID(mixed_id))
        preserved_record = db.get(BrowserCommand, UUID(preserved_id))
        assert mixed_record is not None and mixed_record.state == "partial"
        assert mixed_record.field_results["f0"]["status"] == "preserved"
        assert preserved_record is not None and preserved_record.state == "rejected"
        assert preserved_record.field_results["f0"]["status"] == "preserved"


def test_existing_values_accept_types_device_scope_and_owner_are_enforced(client, engine) -> None:
    device = pair(client)
    other_device = pair(client, "Second device")
    snapshot = share(client, device, file_accept="application/pdf")
    resume = upload_resume(client, b"synthetic plain resume", "Plain resume")
    headers = {
        "Authorization": device["Authorization"],
        "Idempotency-Key": str(uuid4()),
    }
    missing_replace = client.post(
        "/api/v1/browser/device/commands",
        json={"snapshot_id": snapshot["id"], "fields": {"f0": "Replacement"}},
        headers=headers,
    )
    assert missing_replace.status_code == 409
    incompatible = client.post(
        "/api/v1/browser/device/commands",
        json={"snapshot_id": snapshot["id"], "uploads": {"f1": resume["source_version_id"]}},
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert incompatible.status_code == 422
    wrong_device = client.post(
        "/api/v1/browser/device/commands",
        json={
            "snapshot_id": snapshot["id"],
            "fields": {"f0": "Replacement"},
            "replace_fields": ["f0"],
        },
        headers={
            "Authorization": other_device["Authorization"],
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert wrong_device.status_code == 404

    stranger_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=stranger_id, kind="human", display_name="Other synthetic owner"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(stranger_id, "other")
    assert client.get("/api/v1/browser/resumes").json() == {
        "default_version_id": None,
        "items": [],
    }
    assert (
        human_post(
            client,
            "browser/commands",
            {
                "snapshot_id": snapshot["id"],
                "fields": {"f0": "Cross-owner"},
                "replace_fields": ["f0"],
            },
        ).status_code
        == 404
    )


def test_legacy_snapshot_and_expired_claim_are_never_applied(client, engine) -> None:
    device = pair(client)
    snapshot = share(client, device)
    headers = {
        "Authorization": device["Authorization"],
        "Idempotency-Key": str(uuid4()),
    }
    command = client.post(
        "/api/v1/browser/device/commands",
        json={
            "snapshot_id": snapshot["id"],
            "fields": {"f0": "Synthetic replacement"},
            "replace_fields": ["f0"],
        },
        headers=headers,
    ).json()
    with Session(engine) as db, db.begin():
        stored = db.get(BrowserCommand, UUID(command["id"]))
        assert stored is not None
        stored.expires_at = utc_now() - timedelta(seconds=1)
    assert (
        client.post(
            f"/api/v1/browser/device/commands/{command['id']}/claim", headers=headers
        ).status_code
        == 409
    )
    assert (
        client.get(
            "/api/v1/browser/device/commands",
            headers={"Authorization": device["Authorization"]},
        ).json()
        == []
    )

    with Session(engine) as db, db.begin():
        stored_snapshot = db.get(BrowserSnapshot, UUID(snapshot["id"]))
        assert stored_snapshot is not None
        stored_snapshot.protocol_version = 1
    legacy = client.post(
        "/api/v1/browser/device/commands",
        json={
            "snapshot_id": snapshot["id"],
            "fields": {"f0": "Legacy replacement"},
            "replace_fields": ["f0"],
        },
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert legacy.status_code == 409
    assert "Reshare" in legacy.json()["detail"]

    with Session(engine) as db:
        expired = db.get(BrowserCommand, UUID(command["id"]))
        assert expired is not None and expired.state == "rejected"
        assert expired.field_results == {
            "f0": {"status": "rejected", "detail": "Command expired before confirmation"}
        }
