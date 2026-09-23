"""Synthetic domain, HTTP review, and worker fencing regressions."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.actions.worker import perform_reviewed_action
from command_center.core.identity import Identity, authenticate
from command_center.db.artifacts import Artifact, ArtifactVersion, Blob
from command_center.db.models import Actor
from command_center.db.reviewed_actions import (
    ActionAttempt,
    ExternalAccount,
    GmailSendPayload,
    ReviewedAction,
    ReviewedActionRevision,
)
from command_center.db.spending import SpendingDenied
from command_center.integrations.composio_actions import (
    AccountMetadata,
    ComposioActionClient,
    ExecutionReceipt,
    VerifiedIdentity,
)
from command_center.main import create_app


def test_email_checkpoint_preserves_written_whitespace():
    message = "  Hello,\n\nKeep the final blank line.\n\n"
    payload = GmailSendPayload(
        kind="gmail_send", to=["synthetic@example.com"], subject="Synthetic draft", body=message
    )
    assert payload.model_dump()["body"] == message


@pytest.fixture
def action_client(settings, engine):
    actor_id = uuid4()
    account_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic action owner"))
        db.add(
            ExternalAccount(
                id=account_id,
                owner_id=actor_id,
                toolkit="linear",
                composio_connected_account_id="ca_synthetic_linear",
                composio_auth_config_id="ac_synthetic_linear",
                display_name="Synthetic Linear workspace",
                provider_identity={"id": "linear-user", "organization_id": "linear-org"},
                connection_status="ACTIVE",
                identity_verified_at=datetime(2026, 9, 21, tzinfo=UTC),
            )
        )
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic-actions")
    with TestClient(app) as client:
        client.actor_id = actor_id
        client.account_id = account_id
        yield client


def request(client, method, path, body=None, *, key=None):
    return client.request(
        method,
        "/api/v1/" + path,
        json=body,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def test_manual_mail_pull_rejects_a_changed_selected_account_before_provider_access(
    action_client, engine
):
    with Session(engine) as db, db.begin():
        db.add(
            ExternalAccount(
                id=uuid4(),
                owner_id=action_client.actor_id,
                toolkit="gmail",
                composio_connected_account_id="ca_synthetic_mail_pull",
                composio_auth_config_id="ac_synthetic_mail_pull",
                display_name="Synthetic selected Gmail",
                provider_identity={"email": "synthetic@example.com"},
                connection_status="ACTIVE",
                selected_purpose="outreach",
                identity_verified_at=datetime(2026, 9, 22, tzinfo=UTC),
            )
        )
    result = request(
        action_client,
        "POST",
        "gmail/search",
        {
            "account_id": str(uuid4()),
            "query": "from:synthetic@example.com",
            "max_results": 1,
        },
    )
    assert result.status_code == 422, result.text
    assert "selected Gmail account changed" in result.json()["detail"]


def proposal_body(client, **overrides):
    return {
        "account_id": str(client.account_id),
        "payload": {
            "kind": "linear_create",
            "team_id": "team-synthetic",
            "title": "Review synthetic follow-up",
            "priority": 1,
            "label_ids": [],
        },
        "attachment_version_ids": [],
        "reason": "The human requested a synthetic tracked follow-up.",
    } | overrides


def test_proposal_is_idempotent_and_exact_human_review_queues_only_current_revision(
    action_client,
):
    key = uuid4()
    body = proposal_body(action_client)
    first = request(action_client, "POST", "reviewed-actions", body, key=key)
    assert first.status_code == 201, first.text
    action = first.json()
    assert action["state"] == "proposed"
    assert action["current"]["tool_slug"] == "LINEAR_CREATE_LINEAR_ISSUE"
    assert action["approved_revision_id"] is None
    assert request(action_client, "POST", "reviewed-actions", body, key=key).json() == action
    assert (
        request(
            action_client,
            "POST",
            "reviewed-actions",
            body | {"reason": "A different reason."},
            key=key,
        ).status_code
        == 409
    )

    approval = request(
        action_client,
        "POST",
        f"reviewed-actions/{action['id']}/reviews",
        {
            "expected_version": action["row_version"],
            "revision_id": action["current"]["id"],
            "decision": "approved",
            "reason": "The exact synthetic Linear issue is correct.",
        },
    )
    assert approval.status_code == 200, approval.text
    approved = approval.json()
    assert approved["state"] == "queued"
    assert approved["approved_revision_id"] == action["current"]["id"]

    revocation = request(
        action_client,
        "POST",
        f"reviewed-actions/{action['id']}/reviews",
        {
            "expected_version": approved["row_version"],
            "revision_id": approved["current"]["id"],
            "decision": "revoked",
            "reason": "Do not create this synthetic issue.",
        },
    )
    assert revocation.status_code == 200, revocation.text
    assert revocation.json()["state"] == "revoked"
    assert revocation.json()["approved_revision_id"] is None


def test_revision_does_not_inherit_prior_approval(action_client):
    created = request(
        action_client, "POST", "reviewed-actions", proposal_body(action_client)
    ).json()
    approved_response = request(
        action_client,
        "POST",
        f"reviewed-actions/{created['id']}/reviews",
        {
            "expected_version": created["row_version"],
            "revision_id": created["current"]["id"],
            "decision": "approved",
            "reason": "Approve the first exact revision.",
        },
    )
    approved = approved_response.json()
    revised = request(
        action_client,
        "PATCH",
        f"reviewed-actions/{created['id']}",
        {
            "expected_version": approved["row_version"],
            "payload": proposal_body(action_client)["payload"]
            | {"title": "Revised synthetic follow-up"},
            "attachment_version_ids": [],
            "reason": "The title changed after review.",
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["state"] == "proposed"
    assert revised.json()["approved_revision_id"] is None
    assert revised.json()["current"]["version"] == 2


def test_review_projection_links_exact_attachment_and_notion_source_versions(action_client, engine):
    attachment_bytes = f"synthetic reviewed attachment {uuid4()}".encode()
    attachment_sha = hashlib.sha256(attachment_bytes).hexdigest()
    gmail_account_id = uuid4()
    notion_account_id = uuid4()
    attachment_artifact_id = uuid4()
    attachment_version_id = uuid4()
    source_artifact_id = uuid4()
    source_version_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                ExternalAccount(
                    id=gmail_account_id,
                    owner_id=action_client.actor_id,
                    toolkit="gmail",
                    composio_connected_account_id="ca_synthetic_gmail",
                    composio_auth_config_id="ac_synthetic_gmail",
                    display_name="sender@example.com",
                    provider_identity={"email": "sender@example.com"},
                    connection_status="ACTIVE",
                    identity_verified_at=datetime(2026, 9, 21, tzinfo=UTC),
                    selected_purpose="outreach",
                ),
                ExternalAccount(
                    id=notion_account_id,
                    owner_id=action_client.actor_id,
                    toolkit="notion",
                    composio_connected_account_id="ca_synthetic_notion",
                    composio_auth_config_id="ac_synthetic_notion",
                    display_name="Synthetic Notion",
                    provider_identity={"id": "notion-user"},
                    connection_status="ACTIVE",
                    identity_verified_at=datetime(2026, 9, 21, tzinfo=UTC),
                ),
            ]
        )
        attachment_artifact = Artifact(
            id=attachment_artifact_id,
            owner_id=action_client.actor_id,
            created_by_id=action_client.actor_id,
            title="synthetic-evidence.txt",
            kind="source",
            sensitivity="private",
        )
        blob = Blob(
            id=uuid4(),
            sha256=attachment_sha,
            storage_key=f"sha256/{attachment_sha}",
            byte_size=len(attachment_bytes),
        )
        db.add_all([attachment_artifact, blob])
        db.flush()
        attachment = ArtifactVersion.from_blob(
            artifact_id=attachment_artifact.id,
            version=1,
            blob=blob,
            media_type="text/plain",
            created_by_id=action_client.actor_id,
        )
        attachment.id = attachment_version_id
        source_artifact = Artifact(
            id=source_artifact_id,
            owner_id=action_client.actor_id,
            created_by_id=action_client.actor_id,
            title="Synthetic publication",
            kind="source",
            sensitivity="private",
        )
        source = ArtifactVersion.from_payload(
            artifact_id=source_artifact.id,
            version=1,
            payload={"text": "Synthetic reviewed publication."},
            schema_key="text.v1",
            created_by_id=action_client.actor_id,
        )
        source.id = source_version_id
        source_sha = source.content_sha256
        db.add_all([attachment, source_artifact, source])

    gmail = request(
        action_client,
        "POST",
        "reviewed-actions",
        {
            "account_id": str(gmail_account_id),
            "payload": {
                "kind": "gmail_send",
                "to": ["recipient@example.com"],
                "cc": [],
                "bcc": [],
                "subject": "Synthetic attachment",
                "body": "See the exact reviewed attachment.",
                "is_html": False,
            },
            "attachment_version_ids": [str(attachment_version_id)],
            "reason": "Send the exact synthetic attachment.",
        },
    )
    assert gmail.status_code == 201, gmail.text
    attachment_read = gmail.json()["current"]["attachments"][0]
    assert attachment_read == {
        "artifact_id": str(attachment_artifact_id),
        "artifact_version_id": str(attachment_version_id),
        "filename": "synthetic-evidence.txt",
        "position": 0,
        "content_sha256": attachment_sha,
        "media_type": "text/plain",
    }

    notion = request(
        action_client,
        "POST",
        "reviewed-actions",
        {
            "account_id": str(notion_account_id),
            "payload": {
                "kind": "notion_publish",
                "parent_id": "parent_synthetic",
                "title": "Synthetic publication",
            },
            "source_version_id": str(source_version_id),
            "attachment_version_ids": [],
            "reason": "Publish this exact synthetic document version.",
        },
    )
    assert notion.status_code == 201, notion.text
    assert notion.json()["current"]["source_version_id"] == str(source_version_id)
    assert notion.json()["current"]["source_content_sha256"] == source_sha


class SettledReservation:
    def settle(self, provider_billed_micros=None):
        return None

    def unknown(self, reason):
        raise AssertionError(reason)


class SyntheticActionAdapter:
    def __init__(self):
        self.writes = 0

    def account_metadata(self, **kwargs):
        return AccountMetadata(
            connected_account_id=kwargs["connected_account_id"],
            toolkit="linear",
            auth_config_id=kwargs["expected_auth_config_id"],
            status="ACTIVE",
            is_disabled=False,
            provider_updated_at=None,
            provider_identity={"id": "linear-user", "organization_id": "linear-org"},
        )

    def verify_identity(self, account, **kwargs):
        kwargs["reserve_budget"]("LINEAR_WHO_AM_I", kwargs["charge"].operation_id).settle()
        return VerifiedIdentity(
            "Synthetic Linear workspace",
            {"id": "linear-user", "organization_id": "linear-org"},
        )

    def execute_write(self, **kwargs):
        kwargs["reserve_budget"](kwargs["tool_slug"], kwargs["operation_id"]).settle()
        self.writes += 1
        return ExecutionReceipt(
            state="succeeded",
            log_id="log_synthetic",
            external_id="issue_synthetic",
            url="https://linear.example.com/issue/SYN-1",
            remote_revision=None,
            data={"id": "issue_synthetic", "ticket_url": "https://linear.example.com/SYN-1"},
        )


def test_worker_dispatches_approved_revision_once(action_client, engine, settings):
    created = request(
        action_client, "POST", "reviewed-actions", proposal_body(action_client)
    ).json()
    approved = request(
        action_client,
        "POST",
        f"reviewed-actions/{created['id']}/reviews",
        {
            "expected_version": created["row_version"],
            "revision_id": created["current"]["id"],
            "decision": "approved",
            "reason": "Dispatch this exact synthetic issue.",
        },
    ).json()
    adapter = SyntheticActionAdapter()

    def reserve(slug, operation_id):
        return SettledReservation()

    assert perform_reviewed_action(
        engine,
        settings,
        approved["id"],
        reserve_budget=reserve,
        adapter=adapter,
    )
    assert not perform_reviewed_action(
        engine,
        settings,
        approved["id"],
        reserve_budget=reserve,
        adapter=adapter,
    )
    assert adapter.writes == 1
    with Session(engine) as db:
        action = db.get(ReviewedAction, approved["id"])
        attempt = db.scalar(select(ActionAttempt).where(ActionAttempt.action_id == approved["id"]))
        revision = db.get(ReviewedActionRevision, action.approved_revision_id if action else None)
        assert action is not None and action.state == "succeeded"
        assert attempt is not None and attempt.state == "succeeded"
        assert attempt.provider_external_id == "issue_synthetic"
        assert revision is not None and revision.payload["title"] == "Review synthetic follow-up"


def test_budget_denial_before_dispatch_is_definitive_failure(action_client, engine, settings):
    created = request(
        action_client, "POST", "reviewed-actions", proposal_body(action_client)
    ).json()
    approved = request(
        action_client,
        "POST",
        f"reviewed-actions/{created['id']}/reviews",
        {
            "expected_version": created["row_version"],
            "revision_id": created["current"]["id"],
            "decision": "approved",
            "reason": "Approve this exact synthetic issue.",
        },
    ).json()
    adapter = SyntheticActionAdapter()

    def reserve(slug, operation_id):
        if slug == "LINEAR_CREATE_LINEAR_ISSUE":
            raise SpendingDenied("work_budget_exceeded")
        return SettledReservation()

    assert perform_reviewed_action(
        engine,
        settings,
        approved["id"],
        reserve_budget=reserve,
        adapter=adapter,
    )
    assert adapter.writes == 0
    with Session(engine) as db:
        action = db.get(ReviewedAction, approved["id"])
        attempt = db.scalar(select(ActionAttempt).where(ActionAttempt.action_id == approved["id"]))
        assert action is not None and action.state == "failed"
        assert attempt is not None and attempt.state == "failed"
        assert attempt.error_code == "work_budget_exceeded"


def test_provider_io_runs_after_durable_claim_transaction_is_released(
    action_client, engine, mocker
):
    calls = 0

    def list_accounts(self, **kwargs):
        nonlocal calls
        calls += 1
        assert engine.pool.checkedout() == 0
        return []

    mocker.patch.object(ComposioActionClient, "list_accounts", list_accounts)
    action_client.app.state.composio_actions = object.__new__(ComposioActionClient)
    action_client.app.state.settings.composio_auth_configs = {"linear": "ac_synthetic_linear"}
    action_client.app.state.reviewed_action_budget = (
        lambda owner_id, task_id, opportunity_id, **kwargs: (
            lambda slug, operation_id: SettledReservation()
        )
    )
    key = uuid4()
    first = request(
        action_client,
        "POST",
        "integrations/composio/accounts/sync",
        key=key,
    )
    assert first.status_code == 200, first.text
    assert first.json() == []
    replay = request(
        action_client,
        "POST",
        "integrations/composio/accounts/sync",
        key=key,
    )
    assert replay.status_code == 200
    assert replay.json() == []
    assert calls == 1
