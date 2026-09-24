"""Scheduled mail uses exact reviews and confirmed send receipts, never inferred silence."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_reviewed_actions import action_client, request  # noqa: F401

from command_center.actions.worker import claim
from command_center.db.reviewed_actions import ExternalAccount, ReviewedAction


@pytest.fixture
def email_client(action_client, engine):  # noqa: F811 -- fixture imported from the shared action tests
    with Session(engine) as db, db.begin():
        account = db.get(ExternalAccount, action_client.account_id)
        account.toolkit = "gmail"
        account.selected_purpose = "outreach"
        account.provider_identity = {"email": "sender@example.com"}
    return action_client


def proposal(client, **changes):
    return {
        "account_id": str(client.account_id),
        "payload": {
            "kind": "gmail_send",
            "to": ["recipient@example.com"],
            "subject": "Synthetic engineering follow-up",
            "body": "Could we discuss the infrastructure role?",
        },
        "reason": "Requested synthetic outreach",
        **changes,
    }


def approve(client, action, decision="approved"):
    response = request(
        client,
        "POST",
        f"reviewed-actions/{action['id']}/reviews",
        {
            "expected_version": action["row_version"],
            "revision_id": action["current"]["id"],
            "decision": decision,
            "reason": "Reviewed exact synthetic content and delivery time",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_scheduled_email_requires_review_and_cannot_be_claimed_early(email_client, engine, mocker):
    now = datetime(2030, 1, 5, 12, tzinfo=UTC)
    clock = mocker.patch("command_center.db.reviewed_actions.utc_now", return_value=now)
    due = now + timedelta(days=2)
    body = proposal(email_client, delivery={"mode": "at", "send_at": due.isoformat()})
    response = request(email_client, "POST", "reviewed-actions", body)
    assert response.status_code == 201, response.text
    action = response.json()
    identifier = UUID(action["id"])
    with Session(engine) as db, db.begin():
        assert ReviewedAction.claim(db, identifier) is None
    approved = approve(email_client, action)
    assert approved["current"]["scheduled_for"] == due.isoformat().replace("+00:00", "Z")
    with Session(engine) as db, db.begin():
        assert identifier not in {row.id for row in db.scalars(ReviewedAction.dispatchable())}
        assert ReviewedAction.claim(db, identifier) is None
    clock.return_value = due
    with Session(engine) as db, db.begin():
        attempt = ReviewedAction.claim(db, identifier)
        assert attempt is not None
        assert ReviewedAction.claim(db, identifier) is None


def test_rescheduling_invalidates_approval_and_revocation_blocks_delivery(
    email_client, engine, mocker
):
    now = datetime(2030, 1, 5, 12, tzinfo=UTC)
    clock = mocker.patch("command_center.db.reviewed_actions.utc_now", return_value=now)
    body = proposal(
        email_client, delivery={"mode": "at", "send_at": (now + timedelta(days=1)).isoformat()}
    )
    action = request(email_client, "POST", "reviewed-actions", body).json()
    approved = approve(email_client, action)
    changed = {k: v for k, v in body.items() if k != "account_id"}
    changed.update(
        expected_version=approved["row_version"],
        delivery={"mode": "at", "send_at": (now + timedelta(days=2)).isoformat()},
    )
    response = request(email_client, "PATCH", f"reviewed-actions/{action['id']}", changed)
    assert response.status_code == 200, response.text
    revised = response.json()
    assert revised["state"] == "proposed"
    assert revised["approved_revision_id"] is None
    assert revised["current"]["id"] != action["current"]["id"]
    approved = approve(email_client, revised)
    approve(email_client, approved, "revoked")
    clock.return_value = now + timedelta(days=3)
    with Session(engine) as db, db.begin():
        assert ReviewedAction.claim(db, UUID(action["id"])) is None


def test_cadence_is_anchored_to_successful_same_recipient_send(email_client, engine, mocker):
    now = datetime(2030, 1, 5, 12, tzinfo=UTC)
    mocker.patch("command_center.db.reviewed_actions.utc_now", return_value=now)
    original = request(email_client, "POST", "reviewed-actions", proposal(email_client)).json()
    delivery = {"mode": "after_send", "after_action_id": original["id"], "delay_days": 3}
    assert (
        request(
            email_client, "POST", "reviewed-actions", proposal(email_client, delivery=delivery)
        ).status_code
        == 422
    )
    approved = approve(email_client, original)
    with Session(engine) as db, db.begin():
        attempt = ReviewedAction.claim(db, UUID(approved["id"]))
        attempt.finish("succeeded", provider_external_id="synthetic-message-id")
        db.get(ReviewedAction, UUID(approved["id"])).state = "succeeded"
    response = request(
        email_client, "POST", "reviewed-actions", proposal(email_client, delivery=delivery)
    )
    assert response.status_code == 201, response.text
    assert response.json()["current"]["scheduled_for"] == (
        now + timedelta(days=3)
    ).isoformat().replace("+00:00", "Z")
    wrong_recipient = proposal(email_client, delivery=delivery)
    wrong_recipient["payload"]["to"] = ["someone-else@example.com"]
    assert request(email_client, "POST", "reviewed-actions", wrong_recipient).status_code == 422


@pytest.mark.parametrize(
    "delivery",
    [
        {"mode": "at", "send_at": "2020-01-01T00:00:00Z"},
        {"mode": "at", "send_at": "2035-01-01T00:00:00"},
        {"mode": "after_send", "delay_days": 3},
        {"mode": "at", "send_at": "2035-01-01T00:00:00Z", "delay_days": 3},
    ],
)
def test_invalid_schedule_is_rejected(email_client, delivery):
    response = request(
        email_client, "POST", "reviewed-actions", proposal(email_client, delivery=delivery)
    )
    assert response.status_code == 422, response.text


def test_saved_follow_up_is_a_valid_email_source_and_keeps_provenance(email_client, engine):
    contact = request(
        email_client,
        "POST",
        "contacts",
        {"name": "Synthetic recipient", "email": "recipient@example.com"},
    ).json()
    saved = request(
        email_client,
        "POST",
        f"contacts/{contact['id']}/follow-ups",
        {
            "channel": "email",
            "text": "An evidence-backed synthetic draft.",
            "format": "text",
            "subject": "Synthetic role",
            "recipient_email": "recipient@example.com",
        },
    )
    assert saved.status_code == 201, saved.text
    version = saved.json()["version"]
    response = request(
        email_client,
        "POST",
        "reviewed-actions",
        proposal(email_client, source_version_id=version["id"]),
    )
    assert response.status_code == 201, response.text
    assert response.json()["current"]["source_content_sha256"] == version["content_sha256"]
    assert response.json()["state"] == "proposed"
    approved = approve(email_client, response.json())
    claimed = claim(engine, UUID(approved["id"]))
    assert claimed is not None
    assert claimed.source_text == "An evidence-backed synthetic draft."


def test_downgrade_cannot_discard_a_reviewed_schedule(email_client, engine, migration_config):
    from alembic import command

    # The dedicated synthetic suite may retain newer document/Space fixtures.
    # Remove only those prerequisites so this test reaches the email guard.
    assert engine.url.database == "command_center_test"
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM spending_reservations WHERE document_decision_id IS NOT NULL")
        )
        connection.execute(text("DELETE FROM space_links"))
        connection.execute(text("DELETE FROM spaces"))
        connection.execute(text("UPDATE tasks SET state='open' WHERE state='waiting'"))
    response = request(
        email_client,
        "POST",
        "reviewed-actions",
        proposal(email_client, delivery={"mode": "at", "send_at": "2035-01-01T00:00:00Z"}),
    )
    assert response.status_code == 201, response.text
    with pytest.raises(RuntimeError, match="Retain email schedules"):
        command.downgrade(migration_config, "0035_jev_gateways")
    saved = email_client.get(f"/api/v1/reviewed-actions/{response.json()['id']}").json()
    assert saved["current"]["scheduled_for"] == "2035-01-01T00:00:00Z"


def test_account_change_blocks_approved_email_before_provider_access(email_client, engine):
    action = request(email_client, "POST", "reviewed-actions", proposal(email_client)).json()
    approve(email_client, action)
    with Session(engine) as db, db.begin():
        db.get(ExternalAccount, email_client.account_id).selected_purpose = None
    assert claim(engine, UUID(action["id"])) is None
    with Session(engine) as db:
        assert db.get(ReviewedAction, UUID(action["id"])).state == "failed"


def test_elapsed_proposal_and_expiry_before_delivery_need_a_new_time(email_client, mocker):
    now = datetime(2030, 1, 5, 12, tzinfo=UTC)
    clock = mocker.patch("command_center.db.reviewed_actions.utc_now", return_value=now)
    due = now + timedelta(hours=1)
    body = proposal(email_client, delivery={"mode": "at", "send_at": due.isoformat()})
    assert (
        request(
            email_client, "POST", "reviewed-actions", body | {"expires_at": due.isoformat()}
        ).status_code
        == 422
    )
    action = request(email_client, "POST", "reviewed-actions", body).json()
    clock.return_value = due
    response = request(
        email_client,
        "POST",
        f"reviewed-actions/{action['id']}/reviews",
        {
            "expected_version": action["row_version"],
            "revision_id": action["current"]["id"],
            "decision": "approved",
            "reason": "An elapsed review must not send immediately",
        },
    )
    assert response.status_code == 409, response.text
    assert "scheduled time has passed" in response.json()["detail"]


def test_email_history_filters_exact_recipients_without_leaking_other_mail(email_client):
    expected = request(email_client, "POST", "reviewed-actions", proposal(email_client)).json()
    other = proposal(email_client)
    other["payload"]["to"] = ["different@example.com"]
    assert request(email_client, "POST", "reviewed-actions", other).status_code == 201
    response = email_client.get(
        "/api/v1/reviewed-actions?recipient=RECIPIENT@example.com&kind=gmail_send"
    )
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["items"]] == [expected["id"]]
    assert (
        email_client.get(
            "/api/v1/reviewed-actions?recipient=recipient@example.com&state=succeeded"
        ).json()["items"]
        == []
    )


def test_scheduling_requires_a_confirmed_predecessor(email_client, mocker):
    from uuid import uuid4

    mocker.patch(
        "command_center.db.reviewed_actions.utc_now", return_value=datetime(2030, 1, 5, tzinfo=UTC)
    )
    delivery = {"mode": "after_send", "after_action_id": str(uuid4()), "delay_days": 3}
    assert (
        request(
            email_client, "POST", "reviewed-actions", proposal(email_client, delivery=delivery)
        ).status_code
        == 422
    )


def test_other_connected_actions_cannot_be_scheduled(action_client):  # noqa: F811
    from test_reviewed_actions import proposal_body

    response = request(
        action_client,
        "POST",
        "reviewed-actions",
        proposal_body(action_client, delivery={"mode": "at", "send_at": "2035-01-01T00:00:00Z"}),
    )
    assert response.status_code == 422, response.text


def test_email_agent_context_distinguishes_sent_receipts_from_drafts(email_client, engine, mocker):
    from command_center.agents.config import AgentProfile

    mocker.patch(
        "command_center.api.record_work.available_profile",
        return_value=(
            AgentProfile(
                name="Synthetic writer",
                description="Synthetic",
                model="synthetic",
                instructions="Use synthetic context",
                tools=["record_work_context", "save_record_work"],
            ),
            "synthetic",
        ),
    )
    person = request(
        email_client,
        "POST",
        "contacts",
        {"name": "Synthetic recipient", "email": "recipient@example.com"},
    ).json()
    sent_body = proposal(email_client)
    sent_body["payload"]["body"] = "x" * 2000
    sent = request(email_client, "POST", "reviewed-actions", sent_body).json()
    approve(email_client, sent)
    with Session(engine) as db, db.begin():
        attempt = ReviewedAction.claim(db, UUID(sent["id"]))
        attempt.finish("succeeded", provider_external_id="synthetic-context-receipt")
        db.get(ReviewedAction, UUID(sent["id"])).state = "succeeded"
    draft = request(email_client, "POST", "reviewed-actions", proposal(email_client)).json()
    unrelated = proposal(email_client)
    unrelated["payload"]["to"] = ["unrelated@example.com"]
    request(email_client, "POST", "reviewed-actions", unrelated)
    response = request(
        email_client, "POST", f"record-work/contacts/{person['id']}", {"channel": "email"}
    )
    assert response.status_code == 201, response.text
    context = email_client.get(
        f"/api/v1/tasks/{response.json()['task_id']}/record-work/context"
    ).json()
    rows = {row["action_id"]: row for row in context["email_history"]}
    assert set(rows) == {sent["id"], draft["id"]}
    assert rows[sent["id"]]["sent_at"] is not None
    assert len(rows[sent["id"]]["body"]) == 1500
    assert rows[draft["id"]]["sent_at"] is None
    assert "not a reply" in context["email_history_policy"]
