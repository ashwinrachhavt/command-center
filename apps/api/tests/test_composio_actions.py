"""Offline adapter checks for exact Composio schemas and dispatch accounting."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from command_center.db.reviewed_actions import (
    TOOLKIT_VERSIONS,
    CalendarEventsQuery,
    LinkedInPostPayload,
    LinkedInPostQuery,
    LinkedInProfileQuery,
    NotionPageQuery,
)
from command_center.integrations.composio_actions import (
    CONNECTED_ACCOUNTS_LIST_OPERATION,
    AccountMetadata,
    ChargeContext,
    ComposioActionClient,
    ProviderFailure,
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


def context_account(toolkit: str) -> AccountMetadata:
    return AccountMetadata(
        connected_account_id=f"ca_{toolkit}",
        toolkit=toolkit,
        auth_config_id=f"ac_{toolkit}",
        status="ACTIVE",
        is_disabled=False,
        provider_updated_at=None,
        provider_identity={"id": f"{toolkit}-user"},
    )


def budget_recorder():
    calls: list[tuple[str, UUID, Reservation]] = []

    def reserve(slug: str, operation_id: UUID) -> Reservation:
        handle = Reservation()
        calls.append((slug, operation_id, handle))
        return handle

    return reserve, calls


def test_linkedin_oidc_identity_and_basic_profile_use_managed_scopes():
    response = {
        "successful": True,
        "data": {
            "data": {"sub": "member-123", "name": "Alex Synthetic", "email": "alex@example.test"},
            "display_name": "Alex Synthetic",
        },
    }
    client, tools = client_with(response, response)
    reserve, charges = budget_recorder()
    account = context_account("linkedin")
    identity = client.verify_identity(
        account,
        user_id="owner",
        charge=ChargeContext(uuid4()),
        reserve_budget=reserve,
    )
    assert identity.identity == {"sub": "member-123"}
    assert identity.display_name == "Alex Synthetic"
    result = client.read_context(
        LinkedInProfileQuery(kind="linkedin_profile"),
        account=account,
        user_id="owner",
        charge=ChargeContext(uuid4()),
        reserve_budget=reserve,
    )
    assert result.context["profile"]["name"] == "Alex Synthetic"
    assert all(call[0] == "LINKEDIN_WHO_AM_I" for call in tools.calls)
    assert all(item[2].settled == 1 for item in charges)


def test_linkedin_post_read_is_bounded_and_surfaces_missing_permissions():
    client, tools = client_with(
        {"successful": True, "data": {"id": "urn:li:share:123", "commentary": "x" * 20_000}},
        {"successful": False, "error": "Insufficient scope", "data": {}},
    )
    reserve, _ = budget_recorder()
    args = dict(account=context_account("linkedin"), user_id="owner", reserve_budget=reserve)
    query = LinkedInPostQuery(kind="linkedin_post", post_id="urn:li:share:123")
    result = client.read_context(query, charge=ChargeContext(uuid4()), **args)
    assert result.truncated
    assert len(json.dumps(result.context)) < 13_000
    with pytest.raises(ProviderFailure):
        client.read_context(query, charge=ChargeContext(uuid4()), **args)
    assert tools.calls[0][1]["arguments"] == {"post_id": "urn:li:share:123"}


@pytest.mark.parametrize("result_id", ["urn:li:share:123", None])
def test_linkedin_publish_pins_member_account_audience_and_receipt(result_id):
    client, tools = client_with({"successful": True, "data": {"id": result_id}})
    reserve, charges = budget_recorder()
    payload = {"kind": "linkedin_post", "commentary": "Synthetic post", "visibility": "CONNECTIONS"}
    receipt = client.execute_write(
        revision_id=uuid4(),
        payload=payload,
        account=replace(context_account("linkedin"), provider_identity={"sub": "member-123"}),
        user_id="owner",
        tool_slug="LINKEDIN_CREATE_LINKED_IN_POST",
        toolkit_version=TOOLKIT_VERSIONS["linkedin"],
        source_text=None,
        attachments=[],
        reserve_budget=reserve,
        operation_id=uuid4(),
    )
    assert tools.calls[0][1]["arguments"] == {
        "author": "urn:li:person:member-123",
        "commentary": "Synthetic post",
        "visibility": "CONNECTIONS",
        "lifecycleState": "PUBLISHED",
    }
    assert tools.calls[0][1]["connected_account_id"] == "ca_linkedin"
    assert tools.calls[0][1]["version"] == "20260915_00"
    assert receipt.state == ("succeeded" if result_id else "outcome_unknown")
    assert receipt.external_id == result_id
    assert len(charges) == 1
    assert charges[0][2].settled == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"author": "urn:li:person:someone-else"},
        {"commentary": "x" * 3001},
        {"visibility": "CONTAINER"},
    ],
)
def test_linkedin_publication_rejects_spoofed_author_and_invalid_content(extra):
    with pytest.raises(ValueError):
        LinkedInPostPayload.model_validate({"kind": "linkedin_post", "commentary": "Hello"} | extra)


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


def test_calendar_context_uses_pinned_camel_case_list_schema_and_exact_window():
    client, tools = client_with(
        {
            "successful": True,
            "log_id": "log_calendar",
            "data": {
                "etag": "revision-calendar",
                "timeZone": "America/Los_Angeles",
                "nextPageToken": "next-synthetic",
                "items": [
                    {
                        "id": "event-synthetic",
                        "summary": "Synthetic interview",
                        "start": {"dateTime": "2026-10-01T10:00:00-07:00"},
                        "end": {"dateTime": "2026-10-01T11:00:00-07:00"},
                        "etag": "event-revision",
                    }
                ],
            },
        }
    )
    reserve, charges = budget_recorder()
    query = CalendarEventsQuery(
        kind="calendar_events",
        time_min=datetime(2026, 10, 1, tzinfo=UTC),
        time_max=datetime(2026, 10, 8, tzinfo=UTC),
        max_results=20,
        page_token="page-synthetic",
    )
    result = client.read_context(
        query,
        account=context_account("googlecalendar"),
        user_id="owner-synthetic",
        charge=ChargeContext(uuid4()),
        reserve_budget=reserve,
    )
    assert result.context["events"][0]["summary"] == "Synthetic interview"
    assert result.external_revision == "revision-calendar"
    assert result.provider_log_ids == ["log_calendar"]
    assert tools.calls[0][0] == "GOOGLECALENDAR_EVENTS_LIST"
    assert tools.calls[0][1]["arguments"] == {
        "calendarId": "primary",
        "timeMin": "2026-10-01T00:00:00+00:00",
        "timeMax": "2026-10-08T00:00:00+00:00",
        "maxResults": 20,
        "pageToken": "page-synthetic",
        "singleEvents": True,
        "orderBy": "startTime",
    }
    assert charges[0][0] == "GOOGLECALENDAR_EVENTS_LIST"
    assert charges[0][2].settled == 1


def test_notion_context_returns_bounded_markdown_and_distinct_log_ids():
    client, _ = client_with(
        {
            "successful": True,
            "log_id": "log_page",
            "data": {
                "id": "page-synthetic",
                "url": "https://notion.example.test/page",
                "last_edited_time": "2026-10-01T12:00:00Z",
            },
        },
        {
            "successful": True,
            "log_id": "log_markdown",
            "data": {"markdown": "Readable synthetic context. " * 1000},
        },
    )
    reserve, charges = budget_recorder()
    result = client.read_context(
        NotionPageQuery(kind="notion_page", page_id="page-synthetic"),
        account=context_account("notion"),
        user_id="owner-synthetic",
        charge=ChargeContext(uuid4()),
        reserve_budget=reserve,
    )
    assert result.context["markdown"].startswith("Readable synthetic context.")
    assert result.truncated is True
    assert result.content_sha256 is not None
    assert result.provider_log_ids == ["log_page", "log_markdown"]
    assert len(str(result.context)) < 12_500
    assert charges[0][1] != charges[1][1]


def test_calendar_context_rejects_malformed_success_and_preserves_local_pagination():
    query = CalendarEventsQuery(
        kind="calendar_events",
        time_min=datetime(2026, 10, 1, tzinfo=UTC),
        time_max=datetime(2026, 10, 2, tzinfo=UTC),
    )
    malformed, _ = client_with({"successful": True, "data": {"events": []}})
    reserve, _ = budget_recorder()
    with pytest.raises(ProviderFailure, match="event list"):
        malformed.read_context(
            query,
            account=context_account("googlecalendar"),
            user_id="owner-synthetic",
            charge=ChargeContext(uuid4()),
            reserve_budget=reserve,
        )

    large_text = 'Readable "unicode" context 🗓 ' * 300
    bounded, _ = client_with(
        {
            "successful": True,
            "data": {
                "nextPageToken": "remote-next-page",
                "items": [
                    {"id": f"event-{index}", "summary": f"Event {index}", "description": large_text}
                    for index in range(20)
                ],
            },
        }
    )
    reserve, _ = budget_recorder()
    result = bounded.read_context(
        query,
        account=context_account("googlecalendar"),
        user_id="owner-synthetic",
        charge=ChargeContext(uuid4()),
        reserve_budget=reserve,
    )
    assert result.truncated is True
    assert result.content_sha256 is not None
    assert result.context["next_page_token"] is None
    assert result.context["local_omitted_count"] > 0
    assert "smaller time window" in result.context["continuation_note"]
    assert len(json.dumps(result.context, ensure_ascii=False).encode()) <= 12_000


def test_gmail_session_pins_one_account_and_executes_without_bulk_tools(mocker):
    from composio_client.types.tool_router.session_execute_response import SessionExecuteResponse

    client = ComposioActionClient(api_key="synthetic", timeout_seconds=17)
    create = mocker.patch.object(
        client.client.tool_router.session,
        "create",
        autospec=True,
        return_value=SimpleNamespace(session_id="session-synthetic"),
    )

    def execute_single_account(**kwargs):
        if "account" in kwargs:
            raise ValueError("Multi-account selection is not enabled")
        return SessionExecuteResponse(
            data={
                "messages": [
                    {
                        "messageId": "synthetic-mail",
                        "sender": "lead@example.test",
                        "messageText": "Synthetic lead context",
                        "private_extra": "omit",
                    }
                ]
            },
            error=None,
            log_id="log-synthetic",
        )

    execute = mocker.patch.object(
        client.client.tool_router.session,
        "execute",
        autospec=True,
        side_effect=execute_single_account,
    )
    legacy = mocker.patch.object(client.client.tools, "execute", autospec=True)
    reserve, charges = budget_recorder()
    session_id = client.create_gmail_session(
        gmail_account(),
        user_id="owner",
        operation_id=uuid4(),
        reserve_budget=reserve,
    )
    options = create.call_args.kwargs
    assert options["connected_accounts"] == {"gmail": ["ca_synthetic"]}
    assert options["auth_configs"] == {"gmail": "ac_synthetic"}
    assert options["toolkits"] == {"enable": ["gmail"]}
    assert options["tools"] == {"gmail": {"enable": ["GMAIL_FETCH_EMAILS"]}}
    assert options["manage_connections"] == {"enable": False}
    assert options["workbench"] == {"enable": False, "enable_proxy_execution": False}
    assert options["execute"] == {"enable_multi_execute": False}
    for _ in range(2):
        result = client.gmail_search(
            gmail_account(),
            user_id="owner",
            query="from:lead@example.test",
            max_results=2,
            charge=ChargeContext(uuid4()),
            reserve_budget=reserve,
            session_id=session_id,
        )
        assert result["messages"][0]["messageText"] == "Synthetic lead context"
        assert "private_extra" not in result["messages"][0]
    assert create.call_count == 1
    assert execute.call_count == 2
    assert execute.call_args.kwargs["session_id"] == session_id
    assert "account" not in execute.call_args.kwargs
    legacy.assert_not_called()
    assert [entry[0] for entry in charges] == [
        "COMPOSIO_SESSION_CREATE",
        "GMAIL_FETCH_EMAILS",
        "GMAIL_FETCH_EMAILS",
    ]
    assert all(entry[2].settled == 1 for entry in charges)
    client.close()


@pytest.mark.parametrize("response", [RuntimeError("timeout"), {"data": {}, "error": "failed"}])
def test_session_failure_never_falls_back_to_unrestricted_execution(response):
    client, legacy = client_with()
    sessions = ToolExecutor([response])
    client.client.tool_router = SimpleNamespace(
        session=SimpleNamespace(
            execute=lambda **kwargs: sessions.execute(kwargs.pop("tool_slug"), **kwargs)
        )
    )
    reserve, charges = budget_recorder()
    with pytest.raises((ProviderFailure, ProviderOutcomeUnknown)):
        client.gmail_search(
            gmail_account(),
            user_id="owner",
            query="synthetic",
            max_results=1,
            charge=ChargeContext(uuid4()),
            reserve_budget=reserve,
            session_id="session-synthetic",
        )
    assert not legacy.calls
    assert len(sessions.calls) == 1
    assert len(charges) == 1


def test_mail_results_keep_ids_and_explicit_truncation_with_large_bodies():
    client, _ = client_with(
        {
            "successful": True,
            "data": {
                "messages": [
                    {
                        "messageId": f"mail-{index}",
                        "sender": "lead@example.test",
                        "messageText": "x" * 100_000,
                    }
                    for index in range(20)
                ]
            },
        }
    )
    reserve, _ = budget_recorder()
    result = client.gmail_search(
        gmail_account(),
        user_id="owner",
        query="synthetic",
        max_results=20,
        charge=ChargeContext(uuid4()),
        reserve_budget=reserve,
    )
    assert len(result["messages"]) == 20
    assert result["truncated"] is True
    assert all(item["messageId"] and item["content_truncated"] for item in result["messages"])
    assert len(json.dumps(result)) < 25_000
