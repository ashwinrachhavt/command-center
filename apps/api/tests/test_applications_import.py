"""CSV intake normalizes rows, flags formula triggers, and rejects bad input."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from command_center.core.identity import Identity, authenticate
from command_center.db.models import Actor
from command_center.main import create_app


@pytest.fixture
def client(settings, engine, tmp_path, mocker):
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic intake owner"))
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    with TestClient(app) as http:
        http.actor_id = actor_id
        yield http


def upload(client, csv: str, key: str | None = None):
    return client.post(
        "/api/v1/applications-automation/csv",
        files={"file": ("applications.csv", csv.encode(), "text/csv")},
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def test_upload_creates_normalized_rows(client):
    response = upload(
        client,
        "company,job_title,job_url,job_location\n"
        "Acme, Engineer, https://boards.greenhouse.io/acme/jobs/123, Remote\n"
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 0
    rows = client.get("/api/v1/applications-automation/applications").json()["items"]
    assert len(rows) == 1
    row = rows[0]
    assert row["company"] == "Acme"
    assert row["job_title"] == "Engineer"  # trimmed
    assert row["status"] == "ready_to_run"
    assert row["adapter_platform"] == "greenhouse"


def test_upload_flags_formula_triggers(client):
    response = upload(
        client,
        "company,job_title,job_url\n"
        "=SUM(A1), Engineer, https://boards.greenhouse.io/acme/jobs/123\n"
        "Acme, +CMD, https://boards.greenhouse.io/acme/jobs/124\n",
    )
    assert response.status_code == 201, response.text
    items = client.get("/api/v1/applications-automation/applications").json()["items"]
    rows = {row["source_row"]: row for row in items}
    assert rows[1]["company"].startswith("'=")
    assert rows[2]["job_title"].startswith("'+")
    # The neutralized prefix keeps formula content inert, and rows are accepted.


def test_upload_rejects_missing_fields_row(client):
    response = upload(
        client,
        "company,job_title,job_url\n"
        "Acme, Engineer, https://boards.greenhouse.io/acme/jobs/123\n"
        ", Alone,\n",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 1
    assert "2" in body["reject_reasons"]


def test_upload_rejects_headerless_or_missing_columns(client):
    assert upload(client, "company,job_title\nAcme,Engineer\n").status_code == 422


def test_upload_rejects_control_bytes(client):
    csv = "company,job_title,job_url\nAcme,Engineer\x01,https://boards.greenhouse.io/a/j/1\n"
    assert upload(client, csv).status_code == 422


def test_upload_rejects_oversize(client):
    csv = "company,job_title,job_url\n" + "Acme,Engineer,https://x.test/a\n" * 10
    big = csv + "x" * (5 * 1024 * 1024)
    assert upload(client, big).status_code == 413


def test_upload_is_idempotent_on_same_key(client):
    key = str(uuid4())
    csv = "company,job_title,job_url\nAcme,Engineer,https://boards.greenhouse.io/acme/jobs/123\n"
    first = upload(client, csv, key=key)
    assert first.status_code == 201
    replay = upload(client, csv, key=key)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    rows = client.get("/api/v1/applications-automation/applications").json()["items"]
    assert len(rows) == 1


def test_upload_rejects_more_than_200_rows(client):
    csv = "company,job_title,job_url\n"
    csv += "".join(
        f"Acme,Engineer {index},https://boards.greenhouse.io/acme/jobs/{index}\n"
        for index in range(201)
    )
    assert upload(client, csv).status_code == 422


def test_unknown_platform_rows_still_import_without_adapter(client):
    response = upload(
        client,
        "company,job_title,job_url\nAcme,Engineer,https://careers.acme.example/roles/1\n",
    )
    assert response.status_code == 201, response.text
    row = client.get("/api/v1/applications-automation/applications").json()["items"][0]
    assert row["adapter_platform"] is None
