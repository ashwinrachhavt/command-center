"""Offline adapter checks for exact Composio schemas and dispatch accounting."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from command_center.db.reviewed_actions import TOOLKIT_VERSIONS
from command_center.integrations.composio_actions import (
    CONNECTED_ACCOUNTS_LIST_OPERATION,
    AccountMetadata,
    ChargeContext,
    ComposioActionClient,
    ProviderOutcomeUnknown,
)


class Reservation:
    def __init__(self) -> None:
        self.settled = 0
        self.unknown_reason = None

    def settle(self, provider_billed_micros=None) -> None:
        self.settled += 1

    def unknown(self, reason: str) -> None:
        self.unknown_reason = reason


class ToolExecutor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def execute(self, slug, **kwargs):
        self.calls.append((slug, kwargs))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def client_with(*responses):
    client = object.__new__(ComposioActionClient)
    client.timeout_seconds = 19
    tools = ToolExecutor(responses)
    client.client = SimpleNamespace(tools=tools)
    return client, tools


def gmail_account() -> AccountMetadata:
    return AccountMetadata(
        connected_account_id="ca_synthetic",
        toolkit="gmail",
        auth_config_id="ac_synthetic",
        status="ACTIVE",
        is_disabled=False,
        provider_updated_at=datetime(2026, 9, 21, tzinfo=UTC),
        provider_identity={"email": "sender@example.com"},
    )


def budget_recorder():
    calls: list[tuple[str, UUID, Reservation]] = []

    def reserve(slug: str, operation_id: UUID) -> Reservation:
        handle = Reservation()
        calls.append((slug, operation_id, handle))
        return handle

    return reserve, calls


def test_client_disables_sdk_retries_and_bounds_timeout(monkeypatch):
    captured = {}

    class FakeComposio:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("composio_client.Composio", FakeComposio)
    client = ComposioActionClient(api_key="synthetic", timeout_seconds=17)
    assert client.timeout_seconds == 17
    assert captured == {"api_key": "synthetic", "timeout": 17.0, "max_retries": 0}
    with pytest.raises(ValueError, match="between 1 and 60"):
        ComposioActionClient(api_key="synthetic", timeout_seconds=61)


def test_connected_account_discovery_is_metered_as_one_provider_call():
    client = object.__new__(ComposioActionClient)
    client.timeout_seconds = 11
    client.client = SimpleNamespace(
        connected_accounts=SimpleNamespace(list=lambda **kwargs: SimpleNamespace(items=[]))
    )
    reserve, charges = budget_recorder()
    operation_id = uuid4()
    assert (
        client.list_accounts(
            user_id="owner-synthetic",
            auth_config_ids=["ac_synthetic"],
            operation_id=operation_id,
            reserve_budget=reserve,
        )
        == []
    )
    assert charges[0][:2] == (CONNECTED_ACCOUNTS_LIST_OPERATION, operation_id)
    assert charges[0][2].settled == 1


def test_gmail_write_uses_only_reviewed_fields_exact_account_pin_and_one_reservation():
    client, tools = client_with(
        {
            "successful": True,
            "error": None,
            "log_id": "log_synthetic",
            "data": {"id": "msg_synthetic", "historyId": "42"},
        }
    )
    reserve, charges = budget_recorder()
    operation_id = uuid4()
    outcome = client.execute_write(
        operation_id=operation_id,
        revision_id=uuid4(),
        tool_slug="GMAIL_SEND_EMAIL",
        toolkit_version=TOOLKIT_VERSIONS["gmail"],
        payload={
            "kind": "gmail_send",
            "to": ["recipient@example.com"],
            "cc": [],
            "bcc": [],
            "subject": "Synthetic subject",
            "body": "Synthetic body",
            "is_html": False,
        },
        account=gmail_account(),
        user_id="owner-synthetic",
        source_text=None,
        attachments=[],
        reserve_budget=reserve,
    )
    assert outcome.external_id == "msg_synthetic"
    assert outcome.log_id == "log_synthetic"
    assert charges[0][:2] == ("GMAIL_SEND_EMAIL", operation_id)
    assert charges[0][2].settled == 1
    slug, call = tools.calls[0]
    assert slug == "GMAIL_SEND_EMAIL"
    assert call["connected_account_id"] == "ca_synthetic"
    assert call["version"] == "20260915_00"
    assert call["timeout"] == 19.0
    assert call["arguments"] == {
        "recipient_email": "recipient@example.com",
        "extra_recipients": [],
        "cc": [],
        "bcc": [],
        "subject": "Synthetic subject",
        "body": "Synthetic body",
        "is_html": False,
        "user_id": "me",
        "from_email": "sender@example.com",
    }


def test_ambiguous_write_is_never_retried_and_marks_budget_unknown():
    client, tools = client_with(TimeoutError("synthetic timeout"))
    reserve, charges = budget_recorder()
    with pytest.raises(ProviderOutcomeUnknown):
        client.execute_write(
            operation_id=uuid4(),
            revision_id=uuid4(),
            tool_slug="GMAIL_SEND_EMAIL",
            toolkit_version=TOOLKIT_VERSIONS["gmail"],
            payload={
                "kind": "gmail_send",
                "to": ["recipient@example.com"],
                "cc": [],
                "bcc": [],
                "subject": "Synthetic subject",
                "body": "Synthetic body",
                "is_html": False,
            },
            account=gmail_account(),
            user_id="owner-synthetic",
            source_text=None,
            attachments=[],
            reserve_budget=reserve,
        )
    assert len(tools.calls) == 1
    assert charges[0][2].settled == 0
    assert charges[0][2].unknown_reason == "provider_dispatch_ambiguous"


def test_notion_observation_allocates_distinct_durable_budget_operations():
    account = AccountMetadata(
        connected_account_id="ca_notion",
        toolkit="notion",
        auth_config_id="ac_notion",
        status="ACTIVE",
        is_disabled=False,
        provider_updated_at=None,
        provider_identity={"id": "notion-user"},
    )
    client, tools = client_with(
        {
            "successful": True,
            "data": {
                "id": "page_synthetic",
                "url": "https://notion.example.test/page",
                "parent": {"page_id": "parent"},
                "last_edited_time": "2026-09-21T12:00:00Z",
            },
        },
        {"successful": True, "data": {"markdown": "Synthetic publication"}},
    )
    reserve, charges = budget_recorder()
    observation = client.observe_target(
        kind="notion_update",
        payload={"kind": "notion_update", "page_id": "page_synthetic"},
        account=account,
        user_id="owner-synthetic",
        charge=ChargeContext(uuid4()),
        reserve_budget=reserve,
    )
    assert observation.safe_snapshot["markdown_sha256"]
    assert [call[0] for call in tools.calls] == ["NOTION_RETRIEVE_PAGE", "NOTION_GET_PAGE_MARKDOWN"]
    assert charges[0][1] != charges[1][1]
    assert all(charge[2].settled == 1 for charge in charges)
