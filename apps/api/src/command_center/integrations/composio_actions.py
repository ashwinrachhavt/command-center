"""Pinned Composio adapter for reviewed reads and writes; never owns domain state."""

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import httpx

from command_center.db.reviewed_actions import (
    ACTION_PAYLOAD,
    TOOLKIT_VERSIONS,
    CalendarCreatePayload,
    CalendarUpdatePayload,
    GmailSendPayload,
    LinearCreatePayload,
    LinearUpdatePayload,
    NotionPublishPayload,
    NotionUpdatePayload,
)

MAX_SAFE_RESULT_CHARS = 100_000
IDENTITY_TOOLS = {
    "gmail": "GMAIL_GET_PROFILE",
    "googlecalendar": "GOOGLECALENDAR_GET_CURRENT_USER",
    "linear": "LINEAR_WHO_AM_I",
    "notion": "NOTION_GET_ABOUT_ME",
}
CONNECTED_ACCOUNTS_LIST_OPERATION = "COMPOSIO_CONNECTED_ACCOUNTS_LIST"
PRESIGNED_FILE_UPLOAD_OPERATION = "COMPOSIO_FILES_CREATE_PRESIGNED_URL"
CONNECTED_OPERATION_LABELS = {
    CONNECTED_ACCOUNTS_LIST_OPERATION: "List connected accounts",
    PRESIGNED_FILE_UPLOAD_OPERATION: "Prepare connected attachment upload",
    "GMAIL_GET_PROFILE": "Verify Gmail identity",
    "GOOGLECALENDAR_GET_CURRENT_USER": "Verify Google Calendar identity",
    "LINEAR_WHO_AM_I": "Verify Linear identity",
    "NOTION_GET_ABOUT_ME": "Verify Notion identity",
    "GMAIL_FETCH_EMAILS": "Search Gmail messages",
    "GOOGLECALENDAR_EVENTS_GET": "Read Google Calendar event",
    "GOOGLECALENDAR_EVENTS_LIST": "Check Google Calendar event result",
    "LINEAR_GET_LINEAR_ISSUE": "Read Linear issue",
    "NOTION_RETRIEVE_PAGE": "Read Notion page metadata",
    "NOTION_GET_PAGE_MARKDOWN": "Read Notion page content",
}


class FixedCostReservation(Protocol):
    def settle(self, provider_billed_micros: int | None = None) -> None: ...

    def unknown(self, reason: str) -> None: ...


ReserveBudget = Callable[[str, UUID], FixedCostReservation]


class ProviderFailure(RuntimeError):
    """Definitive provider response; it is safe to record failure without replay."""


class ProviderOutcomeUnknown(RuntimeError):
    """Dispatch may have reached the provider; never retry the write automatically."""


class ProviderConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountMetadata:
    connected_account_id: str
    toolkit: str
    auth_config_id: str
    status: str
    is_disabled: bool
    provider_updated_at: datetime | None
    provider_identity: dict[str, Any] | None = None


@dataclass(frozen=True)
class ChargeContext:
    operation_id: UUID


@dataclass(frozen=True)
class VerifiedIdentity:
    display_name: str
    identity: dict[str, Any]


@dataclass(frozen=True)
class AttachmentBytes:
    name: str
    media_type: str
    content_sha256: str
    content: bytes


@dataclass(frozen=True)
class TargetObservation:
    revision: str
    safe_snapshot: dict[str, Any]


@dataclass(frozen=True)
class ExecutionReceipt:
    state: str
    log_id: str | None
    external_id: str | None
    url: str | None
    remote_revision: str | None
    data: dict[str, Any]


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _bounded(value: Any, limit: int = MAX_SAFE_RESULT_CHARS) -> dict[str, Any]:
    plain = _plain(value)
    if not isinstance(plain, dict):
        return {"value": str(plain)[:limit]}
    encoded = json.dumps(plain, default=str, ensure_ascii=False)
    if len(encoded) <= limit:
        return plain
    return {"truncated": True, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}


def _revision_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sub_operation(operation_id: UUID, label: str) -> UUID:
    """Allocate one durable budget identity per provider invocation."""
    return uuid5(operation_id, label)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ComposioActionClient:
    def __init__(self, *, api_key: str, timeout_seconds: int = 30) -> None:
        if not api_key:
            raise ValueError("Composio API key is not configured")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("Composio action timeout must be between 1 and 60 seconds")
        from composio_client import Composio

        self.timeout_seconds = timeout_seconds
        self.client = Composio(
            api_key=api_key,
            timeout=float(timeout_seconds),
            max_retries=0,
        )

    def close(self) -> None:
        self.client.close()

    def list_accounts(
        self,
        *,
        user_id: str,
        auth_config_ids: list[str],
        operation_id: UUID,
        reserve_budget: ReserveBudget,
    ) -> list[AccountMetadata]:
        response = self._connected_call(
            CONNECTED_ACCOUNTS_LIST_OPERATION,
            operation_id,
            reserve_budget,
            lambda: self.client.connected_accounts.list(
                user_ids=[user_id],
                auth_config_ids=auth_config_ids,
                statuses=["ACTIVE"],
                limit=100,
                timeout=float(self.timeout_seconds),
            ),
        )
        accounts: list[AccountMetadata] = []
        for item in response.items:
            toolkit = str(item.toolkit.slug).casefold()
            auth_config_id = str(item.auth_config.id)
            if toolkit not in TOOLKIT_VERSIONS or auth_config_id not in auth_config_ids:
                continue
            accounts.append(
                AccountMetadata(
                    connected_account_id=str(item.id),
                    toolkit=toolkit,
                    auth_config_id=auth_config_id,
                    status=str(getattr(item.status, "value", item.status)),
                    is_disabled=bool(item.is_disabled),
                    provider_updated_at=_parse_time(item.updated_at),
                )
            )
        return accounts

    def account_metadata(
        self,
        *,
        connected_account_id: str,
        expected_toolkit: str,
        expected_auth_config_id: str,
        user_id: str,
        operation_id: UUID,
        reserve_budget: ReserveBudget,
    ) -> AccountMetadata:
        response = self._connected_call(
            CONNECTED_ACCOUNTS_LIST_OPERATION,
            operation_id,
            reserve_budget,
            lambda: self.client.connected_accounts.list(
                user_ids=[user_id],
                auth_config_ids=[expected_auth_config_id],
                connected_account_ids=[connected_account_id],
                statuses=["ACTIVE"],
                limit=2,
                timeout=float(self.timeout_seconds),
            ),
        )
        matches = response.items
        if len(matches) != 1:
            raise ProviderFailure("Connected account is no longer active for this workspace")
        item = matches[0]
        toolkit = str(item.toolkit.slug).casefold()
        if toolkit != expected_toolkit or item.is_disabled:
            raise ProviderFailure("Connected account identity or status changed")
        return AccountMetadata(
            connected_account_id=str(item.id),
            toolkit=toolkit,
            auth_config_id=str(item.auth_config.id),
            status=str(getattr(item.status, "value", item.status)),
            is_disabled=bool(item.is_disabled),
            provider_updated_at=_parse_time(item.updated_at),
        )

    def verify_identity(
        self,
        account: AccountMetadata,
        *,
        user_id: str,
        charge: ChargeContext,
        reserve_budget: ReserveBudget,
    ) -> VerifiedIdentity:
        slug = IDENTITY_TOOLS[account.toolkit]
        result = self._execute(
            slug,
            {},
            account=account,
            user_id=user_id,
            charge=charge,
            reserve_budget=reserve_budget,
            write=False,
        )
        data = result["data"]
        if account.toolkit == "gmail":
            email = str(data.get("emailAddress", "")).strip().casefold()
            identity = {"email": email}
            display = email
        elif account.toolkit == "googlecalendar":
            email = str(data.get("email", "")).strip().casefold()
            identity = {
                "account_id": str(data.get("account_id", "")),
                "email": email,
                "primary_calendar_id": str(data.get("primary_calendar_id", "")),
                "time_zone": str(data.get("time_zone", "")),
            }
            display = email or identity["primary_calendar_id"]
        elif account.toolkit == "linear":
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            identity = {
                key: str(inner.get(key, ""))
                for key in ("id", "name", "email", "organization_id")
                if inner.get(key) is not None
            }
            display = identity.get("email") or identity.get("name") or identity.get("id", "")
        else:
            identity = {
                key: str(data.get(key, ""))
                for key in ("id", "name", "type")
                if data.get(key) is not None
            }
            display = identity.get("name") or identity.get("id", "")
        if not display or not identity:
            raise ProviderFailure("Provider did not return a stable account identity")
        return VerifiedIdentity(display_name=display[:300], identity=identity)

    def gmail_search(
        self,
        account: AccountMetadata,
        *,
        user_id: str,
        query: str,
        max_results: int,
        charge: ChargeContext,
        reserve_budget: ReserveBudget,
    ) -> dict[str, Any]:
        if not query.strip() or not 1 <= max_results <= 20:
            raise ValueError("Gmail search needs a query and 1 to 20 results")
        result = self._execute(
            "GMAIL_FETCH_EMAILS",
            {
                "query": query.strip(),
                "user_id": "me",
                "verbose": True,
                "ids_only": False,
                "max_results": max_results,
                "include_payload": True,
                "include_spam_trash": False,
            },
            account=account,
            user_id=user_id,
            charge=charge,
            reserve_budget=reserve_budget,
            write=False,
        )
        data = result["data"]
        messages = data.get("messages", [])
        safe_messages = []
        if isinstance(messages, list):
            for message in messages[:max_results]:
                if not isinstance(message, dict):
                    continue
                safe_messages.append(
                    {
                        key: message.get(key)
                        for key in (
                            "messageId",
                            "threadId",
                            "sender",
                            "to",
                            "subject",
                            "messageTimestamp",
                            "messageText",
                            "display_url",
                        )
                    }
                )
        bounded_messages = _bounded({"items": safe_messages}, 80_000)
        return {
            "messages": bounded_messages.get("items", []),
            "messages_digest": bounded_messages.get("sha256"),
            "next_page_token": data.get("nextPageToken") or None,
            "result_size_estimate": data.get("resultSizeEstimate"),
            "log_id": result.get("log_id"),
        }

    def observe_target(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        account: AccountMetadata,
        user_id: str,
        charge: ChargeContext,
        reserve_budget: ReserveBudget,
    ) -> TargetObservation:
        parsed = ACTION_PAYLOAD.validate_python(payload)
        if isinstance(parsed, CalendarUpdatePayload):
            result = self._execute(
                "GOOGLECALENDAR_EVENTS_GET",
                {"calendar_id": parsed.calendar_id, "event_id": parsed.event_id},
                account=account,
                user_id=user_id,
                charge=charge,
                reserve_budget=reserve_budget,
                write=False,
            )["data"]
            revision = str(result.get("etag") or result.get("updated") or "")
            safe = {
                key: result.get(key)
                for key in (
                    "id",
                    "etag",
                    "updated",
                    "summary",
                    "description",
                    "start",
                    "end",
                    "attendees",
                    "htmlLink",
                )
            }
        elif isinstance(parsed, LinearUpdatePayload):
            result = self._execute(
                "LINEAR_GET_LINEAR_ISSUE",
                {"issue_id": parsed.issue_id},
                account=account,
                user_id=user_id,
                charge=charge,
                reserve_budget=reserve_budget,
                write=False,
            )["data"]
            issue = result.get("issue") if isinstance(result.get("issue"), dict) else result
            safe = {
                key: issue.get(key)
                for key in (
                    "id",
                    "identifier",
                    "url",
                    "title",
                    "description",
                    "priority",
                    "dueDate",
                    "updatedAt",
                    "state",
                    "assignee",
                    "labels",
                )
            }
            revision = str(issue.get("updatedAt") or _revision_hash(safe))
        elif isinstance(parsed, NotionUpdatePayload):
            page = self._execute(
                "NOTION_RETRIEVE_PAGE",
                {"page_id": parsed.page_id},
                account=account,
                user_id=user_id,
                charge=charge,
                reserve_budget=reserve_budget,
                write=False,
            )["data"]
            markdown_charge = ChargeContext(_sub_operation(charge.operation_id, "notion-markdown"))
            content = self._execute(
                "NOTION_GET_PAGE_MARKDOWN",
                {"page_id": parsed.page_id, "include_transcript": False},
                account=account,
                user_id=user_id,
                charge=markdown_charge,
                reserve_budget=reserve_budget,
                write=False,
            )["data"]
            markdown = str(content.get("markdown", ""))
            safe = {
                "id": page.get("id"),
                "url": page.get("url"),
                "parent": page.get("parent"),
                "last_edited_time": page.get("last_edited_time"),
                "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
            }
            revision = _revision_hash(safe)
        else:
            raise ValueError(f"{kind} is not an update action")
        if not revision:
            raise ProviderFailure("Provider target did not include a stable revision")
        return TargetObservation(revision=revision[:500], safe_snapshot=_bounded(safe, 50_000))

    def execute_write(
        self,
        *,
        operation_id: UUID,
        revision_id: UUID,
        tool_slug: str,
        toolkit_version: str,
        payload: dict[str, Any],
        account: AccountMetadata,
        user_id: str,
        source_text: str | None,
        attachments: list[AttachmentBytes],
        reserve_budget: ReserveBudget,
    ) -> ExecutionReceipt:
        parsed = ACTION_PAYLOAD.validate_python(payload)
        arguments: dict[str, Any]
        if isinstance(parsed, GmailSendPayload):
            uploaded = [
                self._upload_attachment(
                    item,
                    tool_slug,
                    operation_id=_sub_operation(operation_id, f"attachment:{position}"),
                    reserve_budget=reserve_budget,
                )
                for position, item in enumerate(attachments)
            ]
            arguments = {
                "recipient_email": str(parsed.to[0]),
                "extra_recipients": [str(value) for value in parsed.to[1:]],
                "cc": [str(value) for value in parsed.cc],
                "bcc": [str(value) for value in parsed.bcc],
                "subject": parsed.subject,
                "body": parsed.body,
                "is_html": parsed.is_html,
                "user_id": "me",
            }
            sender = account_identity_email(account)
            if sender:
                arguments["from_email"] = sender
            if uploaded:
                arguments["attachment"] = uploaded
        elif isinstance(parsed, CalendarCreatePayload):
            arguments = {
                "calendar_id": parsed.calendar_id,
                "summary": parsed.summary,
                "description": parsed.description,
                "start_datetime": _local_datetime(parsed.start_at, parsed.timezone),
                "end_datetime": _local_datetime(parsed.end_at, parsed.timezone),
                "timezone": parsed.timezone,
                "attendees": [str(value) for value in parsed.attendees],
                "send_updates": parsed.send_updates,
                "create_meeting_room": parsed.create_meeting_room,
                "extended_properties": {"private": {"command_center_action": str(revision_id)}},
            }
        elif isinstance(parsed, CalendarUpdatePayload):
            arguments = {
                "calendar_id": parsed.calendar_id,
                "event_id": parsed.event_id,
                "send_updates": parsed.send_updates,
            }
            for name in ("summary", "description", "attendees"):
                value = getattr(parsed, name)
                if value is not None:
                    arguments[name] = [str(v) for v in value] if name == "attendees" else value
            if parsed.start_at and parsed.end_at:
                timezone = parsed.timezone or "UTC"
                arguments.update(
                    start_time=_local_datetime(parsed.start_at, timezone),
                    end_time=_local_datetime(parsed.end_at, timezone),
                    timezone=timezone,
                )
        elif isinstance(parsed, LinearCreatePayload):
            arguments = parsed.model_dump(mode="json", exclude={"kind"}, exclude_none=True)
        elif isinstance(parsed, LinearUpdatePayload):
            raw = parsed.model_dump(mode="json", exclude={"kind"}, exclude_none=True)
            mapping = {
                "issue_id": "issueId",
                "due_date": "dueDate",
                "state_id": "stateId",
                "assignee_id": "assigneeId",
                "label_ids": "labelIds",
            }
            arguments = {mapping.get(key, key): value for key, value in raw.items()}
        elif isinstance(parsed, NotionPublishPayload):
            if source_text is None:
                raise ValueError("Notion publication needs source document text")
            arguments = {
                "parent_id": parsed.parent_id,
                "title": parsed.title,
                "markdown": source_text,
            }
        elif isinstance(parsed, NotionUpdatePayload):
            if source_text is None:
                raise ValueError("Notion update needs source document text")
            arguments = {
                "page_id": parsed.page_id,
                "new_children": markdown_blocks(source_text),
                "create_backup": True,
                "archive_existing_children": True,
                "dry_run": False,
            }
        else:  # pragma: no cover - discriminated union is exhaustive
            raise ValueError("Unknown reviewed action payload")
        if toolkit_version != TOOLKIT_VERSIONS[account.toolkit]:
            raise ValueError("Reviewed toolkit version does not match the adapter pin")
        result = self._execute(
            tool_slug,
            arguments,
            account=account,
            user_id=user_id,
            charge=ChargeContext(operation_id),
            reserve_budget=reserve_budget,
            write=True,
            toolkit_version=toolkit_version,
        )
        receipt = receipt_for(tool_slug, result)
        if isinstance(parsed, NotionUpdatePayload) and receipt.external_id is None:
            receipt = replace(receipt, external_id=parsed.page_id)
        return receipt

    def reconcile(
        self,
        *,
        revision_id: UUID,
        payload: dict[str, Any],
        account: AccountMetadata,
        user_id: str,
        source_text: str | None,
        reserve_budget: ReserveBudget,
        operation_id: UUID,
    ) -> ExecutionReceipt:
        parsed = ACTION_PAYLOAD.validate_python(payload)
        if isinstance(parsed, CalendarCreatePayload):
            result = self._execute(
                "GOOGLECALENDAR_EVENTS_LIST",
                {
                    "calendarId": parsed.calendar_id,
                    "privateExtendedProperty": f"command_center_action={revision_id}",
                    "maxResults": 2,
                    "showDeleted": True,
                },
                account=account,
                user_id=user_id,
                charge=ChargeContext(_sub_operation(operation_id, "calendar-list")),
                reserve_budget=reserve_budget,
                write=False,
            )
            items = result["data"].get("items", [])
            if isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict):
                event = items[0]
                return ExecutionReceipt(
                    "succeeded",
                    result.get("log_id"),
                    str(event.get("id") or "") or None,
                    str(event.get("htmlLink") or event.get("display_url") or "") or None,
                    str(event.get("etag") or event.get("updated") or "") or None,
                    _bounded(event),
                )
        elif isinstance(parsed, (CalendarUpdatePayload, LinearUpdatePayload, NotionUpdatePayload)):
            observation = self.observe_target(
                kind=parsed.kind,
                payload=payload,
                account=account,
                user_id=user_id,
                charge=ChargeContext(_sub_operation(operation_id, "target-observation")),
                reserve_budget=reserve_budget,
            )
            if update_matches(parsed, observation.safe_snapshot, source_text):
                return ExecutionReceipt(
                    "succeeded",
                    None,
                    target_id(parsed),
                    target_url(observation.safe_snapshot),
                    observation.revision,
                    observation.safe_snapshot,
                )
        elif isinstance(parsed, GmailSendPayload):
            query = f'in:sent to:{parsed.to[0]} subject:"{parsed.subject}"'
            result = self.gmail_search(
                account,
                user_id=user_id,
                query=query,
                max_results=5,
                charge=ChargeContext(_sub_operation(operation_id, "gmail-search")),
                reserve_budget=reserve_budget,
            )
            return ExecutionReceipt(
                "outcome_unknown", result.get("log_id"), None, None, None, _bounded(result)
            )
        else:
            # Linear/Notion create searches can surface candidates but cannot prove uniqueness.
            return ExecutionReceipt(
                "outcome_unknown",
                None,
                None,
                None,
                None,
                {
                    "reason": (
                        "Provider create has no idempotency key; inspect the provider before retry."
                    )
                },
            )
        return ExecutionReceipt(
            "outcome_unknown",
            None,
            None,
            None,
            None,
            {"reason": "No unique provider result matched the exact reviewed action."},
        )

    def _execute(
        self,
        tool_slug: str,
        arguments: dict[str, Any],
        *,
        account: AccountMetadata,
        user_id: str,
        charge: ChargeContext,
        reserve_budget: ReserveBudget,
        write: bool,
        toolkit_version: str | None = None,
    ) -> dict[str, Any]:
        reservation = reserve_budget(tool_slug, charge.operation_id)
        try:
            response = self.client.tools.execute(
                tool_slug,
                arguments=arguments,
                connected_account_id=account.connected_account_id,
                user_id=user_id,
                version=toolkit_version or TOOLKIT_VERSIONS[account.toolkit],
                timeout=float(self.timeout_seconds),
            )
        except Exception as exc:
            if definitive_client_failure(exc):
                reservation.settle()
                raise ProviderFailure("Provider rejected the tool request") from exc
            reservation.unknown(
                "provider_dispatch_ambiguous" if write else "provider_read_ambiguous"
            )
            raise ProviderOutcomeUnknown("Provider outcome is unknown") from exc
        reservation.settle()
        result = _plain(response)
        if not isinstance(result, dict):
            raise ProviderFailure("Provider returned an invalid tool response")
        if result.get("successful") is not True or result.get("error"):
            raise ProviderFailure("Provider did not complete the tool request")
        data = result.get("data")
        if not isinstance(data, dict):
            raise ProviderFailure("Provider tool response did not include data")
        return {
            "data": data,
            "log_id": str(result.get("log_id")) if result.get("log_id") else None,
        }

    def _connected_call(
        self,
        operation_slug: str,
        operation_id: UUID,
        reserve_budget: ReserveBudget,
        call: Callable[[], Any],
    ) -> Any:
        reservation = reserve_budget(operation_slug, operation_id)
        try:
            value = call()
        except Exception as exc:
            if definitive_client_failure(exc):
                reservation.settle()
                raise ProviderFailure("Connected provider request was rejected") from exc
            reservation.unknown("connected_provider_request_ambiguous")
            raise ProviderOutcomeUnknown("Connected provider outcome is unknown") from exc
        reservation.settle()
        return value

    def _upload_attachment(
        self,
        attachment: AttachmentBytes,
        tool_slug: str,
        *,
        operation_id: UUID,
        reserve_budget: ReserveBudget,
    ) -> dict[str, str]:
        if hashlib.sha256(attachment.content).hexdigest() != attachment.content_sha256:
            raise ValueError("Attachment bytes do not match the reviewed version")
        md5 = base64.b64encode(
            hashlib.md5(attachment.content, usedforsecurity=False).digest()
        ).decode()

        def upload_file() -> Any:
            upload = self.client.files.create_presigned_url(
                filename=attachment.name,
                md5=md5,
                mimetype=attachment.media_type,
                tool_slug=tool_slug,
                toolkit_slug="gmail",
                timeout=float(self.timeout_seconds),
            )
            headers = {"Content-MD5": md5, "Content-Type": attachment.media_type}
            if upload.metadata.storage_backend == "azure_blob_storage":
                headers["x-ms-blob-type"] = "BlockBlob"
            response = httpx.put(
                upload.new_presigned_url,
                content=attachment.content,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return upload

        upload = self._connected_call(
            PRESIGNED_FILE_UPLOAD_OPERATION,
            operation_id,
            reserve_budget,
            upload_file,
        )
        return {"name": attachment.name, "mimetype": attachment.media_type, "s3key": upload.key}


def definitive_client_failure(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    return status in {400, 401, 403, 404, 409, 422}


def account_identity_email(account: AccountMetadata) -> str | None:
    identity = account.provider_identity or {}
    email = identity.get("email")
    return str(email).strip().casefold() if email else None


def _local_datetime(value: datetime, timezone: str) -> str:
    return value.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%dT%H:%M:%S")


def markdown_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        block_type = f"heading_{len(heading.group(1))}" if heading else "paragraph"
        content = heading.group(2) if heading else line
        for start in range(0, len(content), 1900):
            chunk = content[start : start + 1900]
            blocks.append(
                {
                    "object": "block",
                    "type": block_type if start == 0 else "paragraph",
                    (block_type if start == 0 else "paragraph"): {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}]
                    },
                }
            )
    if not blocks:
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": []},
            }
        )
    if len(blocks) > 100:
        raise ValueError("Notion publication exceeds the reviewed 100-block adapter limit")
    return blocks


def receipt_for(tool_slug: str, result: dict[str, Any]) -> ExecutionReceipt:
    data = result["data"]
    external_id: str | None = None
    url: str | None = None
    revision: str | None = None
    state = "succeeded"
    if tool_slug == "GMAIL_SEND_EMAIL":
        external_id = str(data.get("id") or "") or None
        url = str(data.get("display_url") or "") or None
        revision = str(data.get("historyId") or data.get("internalDate") or "") or None
    elif tool_slug in {"GOOGLECALENDAR_CREATE_EVENT", "GOOGLECALENDAR_PATCH_EVENT"}:
        event = data.get("response_data") if isinstance(data.get("response_data"), dict) else data
        external_id = str(event.get("id") or "") or None
        url = str(event.get("htmlLink") or event.get("display_url") or "") or None
        revision = str(event.get("etag") or event.get("updated") or "") or None
    elif tool_slug == "LINEAR_CREATE_LINEAR_ISSUE":
        external_id = str(data.get("id") or "") or None
        url = str(data.get("ticket_url") or "") or None
    elif tool_slug == "LINEAR_UPDATE_ISSUE":
        issue = data.get("issue") if isinstance(data.get("issue"), dict) else data
        external_id = str(issue.get("id") or "") or None
        url = str(issue.get("url") or "") or None
        revision = str(issue.get("updatedAt") or _revision_hash(issue))
    elif tool_slug == "NOTION_CREATE_NOTION_PAGE":
        external_id = str(data.get("id") or "") or None
        url = str(data.get("url") or data.get("public_url") or "") or None
        revision = str(data.get("last_edited_time") or "") or None
    elif tool_slug == "NOTION_REPLACE_PAGE_CONTENT":
        errors = data.get("errors")
        state = "partial" if errors or data.get("success") is not True else "succeeded"
        external_id = None
    return ExecutionReceipt(
        state=state,
        log_id=result.get("log_id"),
        external_id=external_id,
        url=url,
        remote_revision=revision,
        data=_bounded(data),
    )


def target_id(payload: Any) -> str | None:
    return (
        getattr(payload, "event_id", None)
        or getattr(payload, "issue_id", None)
        or getattr(payload, "page_id", None)
    )


def target_url(snapshot: dict[str, Any]) -> str | None:
    value = snapshot.get("htmlLink") or snapshot.get("url")
    return str(value) if value else None


def update_matches(payload: Any, snapshot: dict[str, Any], source_text: str | None) -> bool:
    if isinstance(payload, CalendarUpdatePayload):
        pairs = {"summary": payload.summary, "description": payload.description}
        return all(value is None or snapshot.get(key) == value for key, value in pairs.items())
    if isinstance(payload, LinearUpdatePayload):
        linear_pairs: dict[str, object] = {
            "title": payload.title,
            "description": payload.description,
            "priority": payload.priority,
            "dueDate": payload.due_date.isoformat() if payload.due_date else None,
        }
        return all(
            value is None or snapshot.get(key) == value for key, value in linear_pairs.items()
        )
    if isinstance(payload, NotionUpdatePayload) and source_text is not None:
        return snapshot.get("markdown_sha256") == hashlib.sha256(source_text.encode()).hexdigest()
    return False
