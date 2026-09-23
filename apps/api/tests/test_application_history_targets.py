"""History row counts are owned snapshots of currently approved structured facts."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_application_preparations import client as client
from test_application_preparations import fact, post, prepare, review_fact, revise, shared_page

from command_center.api.application_preparations import preparation_read
from command_center.core.identity import Identity, authenticate
from command_center.db.application_preparations import ApplicationPreparation
from command_center.db.artifacts import ArtifactVersion
from command_center.db.base import utc_now
from command_center.db.career import CareerEntry
from command_center.db.models import Actor


@pytest.mark.parametrize("targets", [None, {"experience": 2, "education": 1}])
def test_preparation_read_uses_saved_targets_or_zero_for_older_packages(targets):
    preparation = ApplicationPreparation(
        id=uuid4(),
        snapshot_id=uuid4(),
        task_id=uuid4(),
        artifact_id=uuid4(),
        created_at=utc_now(),
    )
    payload = {"resume": None, "replace_fields": [], "upload_fields": [], "fields": []}
    if targets is not None:
        payload["history_targets"] = targets
    version = ArtifactVersion(id=uuid4(), version=1, payload=payload)
    result = preparation_read(preparation, version).model_dump()
    assert result.get("history_targets") == (targets or {"experience": 0, "education": 0})
    assert ("history_targets" in payload) == (targets is not None)


def career_fact(
    client, kind="experience", *, organization="Synthetic Employer", start_date="2020-09", **extra
):
    return fact(
        client,
        kind,
        CareerEntry(kind=kind, organization=organization, start_date=start_date).encode(),
        **extra,
    )


def test_preparation_persists_targets_from_active_revisions_through_review_and_autofill(
    client, engine
):
    employment = review_fact(client, career_fact(client))
    review_fact(client, career_fact(client, "education", organization="Synthetic University"))
    pending = post(
        client,
        f"profile/facts/{employment['id']}/versions",
        {
            "expected_version": employment["row_version"],
            "value": "Synthetic unreviewed free-text employment history",
        },
    )
    assert pending.status_code == 201, pending.text
    snapshot, headers = shared_page(client)
    preparation = prepare(client, snapshot)
    assert preparation["history_targets"] == {"experience": 1, "education": 1}

    review_fact(
        client,
        fact(
            client,
            "experience",
            CareerEntry(
                kind="experience", organization="Synthetic Earlier Employer", start_date="2015"
            ).encode(),
        ),
    )
    reviewed = revise(client, preparation, fields={})
    assert reviewed["history_targets"] == {"experience": 1, "education": 1}
    automatic = post(
        client,
        f"browser/device/preparations/{preparation['id']}/autofill",
        {"expected_version_id": reviewed["version_id"], "attach_resume": False},
        headers=headers,
    )
    assert automatic.status_code == 201, automatic.text
    assert automatic.json()["history_targets"] == {"experience": 1, "education": 1}
    with Session(engine) as db:
        for result in (preparation, reviewed, automatic.json()):
            version = db.get(ArtifactVersion, UUID(result["version_id"]))
            assert version.payload["history_targets"] == {"experience": 1, "education": 1}
    assert prepare(client, snapshot)["history_targets"] == {"experience": 2, "education": 1}


def test_history_targets_exclude_unapproved_rejected_revoked_expired_and_foreign_facts(
    client, engine
):
    career_fact(client, organization="Synthetic Pending", start_date="2001")
    review_fact(
        client,
        career_fact(client, organization="Synthetic Rejected", start_date="2002"),
        "rejected",
    )
    revoked = review_fact(
        client, career_fact(client, organization="Synthetic Revoked", start_date="2003")
    )
    review_fact(client, revoked, "revoked")
    review_fact(
        client,
        career_fact(
            client,
            organization="Synthetic Expired",
            start_date="2004",
            valid_until=(utc_now() - timedelta(seconds=1)).isoformat(),
        ),
    )
    review_fact(
        client,
        fact(client, "experience", "Synthetic scoped description", context="One application"),
    )
    other_owner = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other_owner, kind="human", display_name="Synthetic Other Applicant"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other_owner, "synthetic")
    review_fact(
        client, career_fact(client, organization="Synthetic Foreign Employer", start_date="1990")
    )
    review_fact(client, career_fact(client, "education", organization="Synthetic Foreign School"))
    client.app.dependency_overrides[authenticate] = client.human_identity

    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot)
    assert preparation["history_targets"] == {"experience": 0, "education": 0}
    client.app.dependency_overrides[authenticate] = lambda: Identity(other_owner, "synthetic")
    denied = client.get(f"/api/v1/browser/preparations/{preparation['id']}")
    assert denied.status_code == 404
