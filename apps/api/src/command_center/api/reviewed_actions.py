"""Thin HTTP boundary for exact, human-reviewed connected actions."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from command_center.api import schemas as s
from command_center.api.workspace import Database, Limit, Offset, WriteKey, check_version
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity, Identity
from command_center.db.agents import AgentRun
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.conversations import AgentSession
from command_center.db.crm import record_event
from command_center.db.idempotency import IdempotencyConflict, RequestReceipt
from command_center.db.reviewed_actions import (
    CONDITIONAL_UPDATE_NOTICE,
    ActionAttempt,
    ActionPayload,
    ConnectedContextKind,
    ConnectedContextQuery,
    ConnectedRequest,
    ExternalAccount,
    ProviderObservation,
    ReviewDecision,
    ReviewedAction,
    ReviewedActionAttachment,
    ReviewedActionRevision,
)
from command_center.db.spending import SpendingDenied
from command_center.integrations.composio_actions import (
    AccountMetadata,
    ChargeContext,
    ComposioActionClient,
    ProviderFailure,
    ProviderOutcomeUnknown,
    ReserveBudget,
)

router = APIRouter(prefix="/api/v1", tags=["reviewed-actions"])


class AccountRead(s.ResponseContract):
    id: UUID
    row_version: int
    toolkit: str
    display_name: str
    provider_identity: dict[str, Any]
    connection_status: str
    identity_verified_at: datetime
    selected_purpose: str | None


class AccountSelection(s.Revision):
    purpose: Literal["outreach"]


class GmailSearchCreate(s.Contract):
    account_id: UUID | None = None
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=10, ge=1, le=20)


class GmailSearchRead(s.ResponseContract):
    observation_id: UUID
    account_id: UUID
    observed_at: datetime
    messages: list[dict[str, Any]]
    next_page_token: str | None
    result_size_estimate: int | None


class ConnectedContextCreate(s.Contract):
    account_id: UUID
    query: ConnectedContextQuery


class ConnectedContextRead(s.ResponseContract):
    observation_id: UUID
    account_id: UUID
    kind: ConnectedContextKind
    observed_at: datetime
    external_revision: str
    provider_log_ids: list[Annotated[str, Field(max_length=500)]] = Field(max_length=4)
    context: dict[str, Any]
    truncated: bool
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ActionFields(s.Contract):
    account_id: UUID
    payload: ActionPayload
    task_id: UUID | None = None
    opportunity_id: UUID | None = None
    source_version_id: UUID | None = None
    attachment_version_ids: list[UUID] = Field(default_factory=list, max_length=10)
    expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def one_scope(self) -> "ActionFields":
        if self.task_id is not None and self.opportunity_id is not None:
            raise ValueError("Choose a task or an opportunity scope")
        return self


class ActionCreate(ActionFields):
    pass


class ActionVersionCreate(s.Contract):
    expected_version: int = Field(ge=1)
    payload: ActionPayload
    source_version_id: UUID | None = None
    attachment_version_ids: list[UUID] = Field(default_factory=list, max_length=10)
    expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=2000)


class ActionReviewCreate(s.Revision):
    revision_id: UUID
    decision: ReviewDecision
    reason: str = Field(min_length=1, max_length=2000)


class ActionAttachmentRead(s.ResponseContract):
    artifact_id: UUID
    artifact_version_id: UUID
    filename: str
    position: int
    content_sha256: str
    media_type: str


class ActionRevisionRead(s.ResponseContract):
    id: UUID
    version: int
    tool_slug: str
    toolkit_version: str
    payload: dict[str, Any]
    payload_hash: str
    source_version_id: UUID | None
    source_content_sha256: str | None
    attachments: list[ActionAttachmentRead]
    expected_remote_revision: str | None
    observed_target: dict[str, Any] | None
    expires_at: datetime | None
    review_state: str
    reason: str
    created_at: datetime


class AttemptRead(s.ResponseContract):
    id: UUID
    state: str
    provider_log_id: str | None
    provider_external_id: str | None
    provider_url: str | None
    receipt: dict[str, Any] | None
    observed_before_revision: str | None
    observed_after_revision: str | None
    error_code: str | None
    reconciliation: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None


class ActionRead(s.ResponseContract):
    id: UUID
    row_version: int
    kind: str
    state: str
    account: AccountRead
    task_id: UUID | None
    opportunity_id: UUID | None
    current: ActionRevisionRead
    approved_revision_id: UUID | None
    attempt: AttemptRead | None
    conditional_update_notice: str | None
    created_at: datetime
    updated_at: datetime


def _human(identity: Identity) -> None:
    if identity.run_id is not None:
        raise HTTPException(403, "Human review is required")


def _adapter(request: Request) -> ComposioActionClient:
    value = getattr(request.app.state, "composio_actions", None)
    if not isinstance(value, ComposioActionClient):
        raise HTTPException(503, "Reviewed connected actions are not configured")
    return value


def _budget(
    request: Request,
    owner_id: UUID,
    task_id: UUID | None,
    opportunity_id: UUID | None,
    request_scope_id: UUID,
) -> ReserveBudget:
    factory = getattr(request.app.state, "reviewed_action_budget", None)
    if not callable(factory):
        raise HTTPException(503, "Connected-tool cost controls are not configured")
    value = factory(
        owner_id,
        task_id,
        opportunity_id,
        request_scope_id=request_scope_id,
        agent_run_id=getattr(request.state, "agent_run_id", None),
        agent_lease_id=getattr(request.state, "agent_lease_id", None),
    )
    if not callable(value):
        raise HTTPException(503, "Connected-tool cost controls are not configured")
    return cast(ReserveBudget, value)


def _metadata(account: ExternalAccount) -> AccountMetadata:
    return AccountMetadata(
        connected_account_id=account.composio_connected_account_id,
        toolkit=account.toolkit,
        auth_config_id=account.composio_auth_config_id,
        status=account.connection_status,
        is_disabled=account.connection_status != "ACTIVE",
        provider_updated_at=account.provider_updated_at,
        provider_identity=account.provider_identity,
    )


def _account_read(account: ExternalAccount) -> AccountRead:
    return AccountRead.model_validate(account)


def _scope(db: Database, identity: Identity) -> tuple[UUID | None, UUID | None]:
    if identity.run_id is None:
        return None, None
    row = db.execute(
        select(AgentSession.task_id, AgentSession.opportunity_id)
        .join(AgentRun, AgentRun.session_id == AgentSession.id)
        .where(
            AgentRun.id == identity.run_id,
            AgentRun.owner_id == identity.id,
            AgentSession.owner_id == identity.id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(403, "Agent run has no owned work scope")
    return row[0], row[1]


def _owned_account(
    db: Database, account_id: UUID, owner_id: UUID, *, lock: bool = False
) -> ExternalAccount:
    query = select(ExternalAccount).where(
        ExternalAccount.id == account_id,
        ExternalAccount.owner_id == owner_id,
        ExternalAccount.archived_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    account = db.scalar(query)
    if account is None:
        raise HTTPException(404, "Connected account not found")
    return account


def _owned_action(
    db: Database, action_id: UUID, owner_id: UUID, *, lock: bool = False
) -> ReviewedAction:
    query = select(ReviewedAction).where(
        ReviewedAction.id == action_id,
        ReviewedAction.owner_id == owner_id,
        ReviewedAction.archived_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    action = db.scalar(query)
    if action is None:
        raise HTTPException(404, "Reviewed action not found")
    return action


def _revision_read(db: Database, revision: ReviewedActionRevision) -> ActionRevisionRead:
    source = (
        db.get(ArtifactVersion, revision.source_version_id) if revision.source_version_id else None
    )
    attachments = db.execute(
        select(ReviewedActionAttachment, ArtifactVersion.artifact_id, Artifact.title)
        .join(
            ArtifactVersion,
            ArtifactVersion.id == ReviewedActionAttachment.artifact_version_id,
        )
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(ReviewedActionAttachment.revision_id == revision.id)
        .order_by(ReviewedActionAttachment.position)
    ).all()
    return ActionRevisionRead(
        id=revision.id,
        version=revision.version,
        tool_slug=revision.tool_slug,
        toolkit_version=revision.toolkit_version,
        payload=revision.payload,
        payload_hash=revision.payload_hash,
        source_version_id=revision.source_version_id,
        source_content_sha256=source.content_sha256 if source else None,
        attachments=[
            ActionAttachmentRead(
                artifact_id=artifact_id,
                artifact_version_id=item.artifact_version_id,
                filename=title,
                position=item.position,
                content_sha256=item.content_sha256,
                media_type=item.media_type,
            )
            for item, artifact_id, title in attachments
        ],
        expected_remote_revision=revision.expected_remote_revision,
        observed_target=revision.observed_target,
        expires_at=revision.expires_at,
        review_state=revision.review_state(db),
        reason=revision.reason,
        created_at=revision.created_at,
    )


def _action_read(db: Database, action: ReviewedAction) -> ActionRead:
    account = db.get(ExternalAccount, action.account_id)
    current = db.get(ReviewedActionRevision, action.current_revision_id)
    if account is None or current is None:
        raise ValueError("Reviewed action lineage is incomplete")
    attempt = db.scalar(
        select(ActionAttempt)
        .where(ActionAttempt.action_id == action.id)
        .order_by(ActionAttempt.started_at.desc())
        .limit(1)
    )
    return ActionRead(
        id=action.id,
        row_version=action.row_version,
        kind=action.kind,
        state=action.state,
        account=_account_read(account),
        task_id=action.task_id,
        opportunity_id=action.opportunity_id,
        current=_revision_read(db, current),
        approved_revision_id=action.approved_revision_id,
        attempt=AttemptRead.model_validate(attempt) if attempt else None,
        conditional_update_notice=(
            CONDITIONAL_UPDATE_NOTICE if action.kind.endswith("_update") else None
        ),
        created_at=action.created_at,
        updated_at=action.updated_at,
    )


def _execute(
    db: Database,
    *,
    actor_id: UUID,
    key: UUID,
    operation: str,
    payload: dict[str, Any],
    change: Callable[[UUID], dict[str, Any]],
) -> dict[str, Any]:
    return RequestReceipt.execute(
        db,
        actor_id=actor_id,
        key=key,
        operation=operation,
        payload=payload,
        change=change,
    )


def _claim_connected(
    request: Request,
    *,
    actor_id: UUID,
    key: UUID,
    operation: str,
    payload: dict[str, Any],
) -> tuple[UUID, dict[str, Any] | None]:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    record_id = uuid5(NAMESPACE_URL, f"command-center:{actor_id}:{operation}:{key}")
    with Session(request.app.state.engine) as db, db.begin():
        inserted = db.scalar(
            insert(ConnectedRequest)
            .values(
                id=record_id,
                actor_id=actor_id,
                key=key,
                operation=operation,
                request_hash=digest,
                state="running",
            )
            .on_conflict_do_nothing(index_elements=["actor_id", "key"])
            .returning(ConnectedRequest.id)
        )
        claim = db.scalar(
            select(ConnectedRequest)
            .where(ConnectedRequest.actor_id == actor_id, ConnectedRequest.key == key)
            .with_for_update()
        )
        if claim is None:
            raise RuntimeError("Connected request claim is unavailable")
        if inserted is not None:
            return record_id, None
        if claim.operation != operation or claim.request_hash != digest:
            raise IdempotencyConflict("This idempotency key was already used with different input")
        if claim.state == "completed" and claim.response is not None:
            return claim.id, claim.response
        if claim.state == "running":
            raise HTTPException(
                409,
                {
                    "code": "connected_request_running",
                    "message": "This connected request is already running",
                },
            )
        if claim.state == "outcome_unknown":
            raise HTTPException(
                409,
                {
                    "code": "connected_request_outcome_unknown",
                    "message": "The connected provider outcome is unknown; do not replay it",
                },
            )
        raise HTTPException(
            409,
            {
                "code": "connected_request_failed",
                "message": "This connected request already failed and was not replayed",
            },
        )


def _fail_connected(request: Request, claim_id: UUID, code: str, *, unknown: bool) -> None:
    with Session(request.app.state.engine) as db, db.begin():
        claim = db.get(ConnectedRequest, claim_id, with_for_update=True)
        if claim is not None:
            claim.fail(code, unknown=unknown)


def _deny_connected(request: Request, claim_id: UUID, exc: SpendingDenied) -> None:
    _fail_connected(request, claim_id, exc.code, unknown=False)
    raise HTTPException(
        409,
        {"code": exc.code, "message": "Spending control denied this connected request."},
    ) from exc


def _complete_connected(db: Database, claim_id: UUID, response: dict[str, Any]) -> None:
    claim = db.get(ConnectedRequest, claim_id, with_for_update=True)
    if claim is None:
        raise RuntimeError("Connected request claim is unavailable")
    claim.complete(response)


def _finalize_connected(
    request: Request,
    *,
    claim_id: UUID,
    actor_id: UUID,
    key: UUID,
    operation: str,
    payload: dict[str, Any],
    change: Callable[[Session, UUID], dict[str, Any]],
) -> dict[str, Any]:
    try:
        with Session(request.app.state.engine) as db, db.begin():
            response = _execute(
                db,
                actor_id=actor_id,
                key=key,
                operation=operation,
                payload=payload,
                change=lambda record_id: change(db, record_id),
            )
            _complete_connected(db, claim_id, response)
            return response
    except Exception:
        _fail_connected(request, claim_id, "connected_request_finalize_failed", unknown=False)
        raise


@router.get("/integrations/composio/accounts", response_model=list[AccountRead])
def list_accounts(identity: CurrentIdentity, db: Database) -> list[AccountRead]:
    rows = db.scalars(
        select(ExternalAccount)
        .where(ExternalAccount.owner_id == identity.id, ExternalAccount.archived_at.is_(None))
        .order_by(ExternalAccount.toolkit, ExternalAccount.display_name)
    ).all()
    return [_account_read(row) for row in rows]


@router.post(
    "/integrations/composio/accounts/sync",
    response_model=list[AccountRead],
)
def sync_accounts(
    request: Request, identity: CurrentIdentity, key: WriteKey
) -> list[dict[str, Any]]:
    _human(identity)
    operation = "POST:/api/v1/integrations/composio/accounts/sync"
    adapter = _adapter(request)
    configs = request.app.state.settings.composio_auth_configs
    if not configs:
        raise HTTPException(503, "No reviewed Composio auth configurations are configured")
    claim_id, replay = _claim_connected(
        request, actor_id=identity.id, key=key, operation=operation, payload={}
    )
    if replay is not None:
        return cast(list[dict[str, Any]], replay["items"])
    budget = _budget(request, identity.id, None, None, claim_id)
    try:
        found = adapter.list_accounts(
            user_id=str(identity.id),
            auth_config_ids=list(configs.values()),
            operation_id=uuid5(claim_id, "accounts-list"),
            reserve_budget=budget,
        )
        identities = [
            adapter.verify_identity(
                item,
                user_id=str(identity.id),
                charge=ChargeContext(uuid5(claim_id, f"identity:{item.connected_account_id}")),
                reserve_budget=budget,
            )
            for item in found
        ]
    except SpendingDenied as exc:
        _deny_connected(request, claim_id, exc)
    except (ProviderFailure, ProviderOutcomeUnknown) as exc:
        unknown = isinstance(exc, ProviderOutcomeUnknown)
        _fail_connected(request, claim_id, "account_sync_provider_failed", unknown=unknown)
        raise HTTPException(503, "Connected accounts could not be synchronized") from exc
    except Exception:
        _fail_connected(request, claim_id, "account_sync_failed", unknown=False)
        raise

    def change(db: Session, record_id: UUID) -> dict[str, Any]:
        if record_id != claim_id:
            raise RuntimeError("Connected request identity changed")
        items = []
        for index, (metadata, verified) in enumerate(zip(found, identities, strict=True)):
            account = ExternalAccount.sync(
                db,
                owner_id=identity.id,
                toolkit=metadata.toolkit,
                connected_account_id=metadata.connected_account_id,
                auth_config_id=metadata.auth_config_id,
                display_name=verified.display_name,
                provider_identity=verified.identity,
                connection_status=metadata.status,
                provider_updated_at=metadata.provider_updated_at,
                request_id=UUID(request.state.request_id),
                record_id=uuid5(record_id, str(index)),
            )
            items.append(_account_read(account).model_dump(mode="json"))
        return {"items": items}

    response = _finalize_connected(
        request,
        claim_id=claim_id,
        actor_id=identity.id,
        key=key,
        operation=operation,
        payload={},
        change=change,
    )
    return cast(list[dict[str, Any]], response["items"])


@router.post("/integrations/composio/accounts/{account_id}/select", response_model=AccountRead)
def select_account(
    account_id: UUID,
    body: AccountSelection,
    request: Request,
    identity: CurrentIdentity,
    key: WriteKey,
) -> dict[str, Any]:
    _human(identity)
    operation = f"POST:/api/v1/integrations/composio/accounts/{account_id}/select"
    payload = body.model_dump(mode="json")
    with Session(request.app.state.engine) as db:
        account = _owned_account(db, account_id, identity.id)
        check_version(account, body.expected_version)
        metadata_input = _metadata(account)
        stored_identity = dict(account.provider_identity)
    adapter = _adapter(request)
    claim_id, replay = _claim_connected(
        request, actor_id=identity.id, key=key, operation=operation, payload=payload
    )
    if replay is not None:
        return replay
    budget = _budget(request, identity.id, None, None, claim_id)
    try:
        metadata = adapter.account_metadata(
            connected_account_id=metadata_input.connected_account_id,
            expected_toolkit=metadata_input.toolkit,
            expected_auth_config_id=metadata_input.auth_config_id,
            user_id=str(identity.id),
            operation_id=uuid5(claim_id, "selection-account"),
            reserve_budget=budget,
        )
        verified = adapter.verify_identity(
            metadata,
            user_id=str(identity.id),
            charge=ChargeContext(uuid5(claim_id, "selection-identity")),
            reserve_budget=budget,
        )
        if verified.identity != stored_identity:
            raise ProviderFailure("Connected account identity changed")
    except SpendingDenied as exc:
        _deny_connected(request, claim_id, exc)
    except (ProviderFailure, ProviderOutcomeUnknown) as exc:
        unknown = isinstance(exc, ProviderOutcomeUnknown)
        _fail_connected(request, claim_id, "account_selection_provider_failed", unknown=unknown)
        raise HTTPException(503, "Connected account could not be verified") from exc
    except Exception:
        _fail_connected(request, claim_id, "account_selection_failed", unknown=False)
        raise

    def change(db: Session, record_id: UUID) -> dict[str, Any]:
        if record_id != claim_id:
            raise RuntimeError("Connected request identity changed")
        account = _owned_account(db, account_id, identity.id, lock=True)
        check_version(account, body.expected_version)
        if account.provider_identity != verified.identity:
            raise ValueError("Connected account identity changed; synchronize it again")
        account.select_for(body.purpose, request_id=UUID(request.state.request_id))
        db.flush()
        return _account_read(account).model_dump(mode="json")

    return _finalize_connected(
        request,
        claim_id=claim_id,
        actor_id=identity.id,
        key=key,
        operation=operation,
        payload=payload,
        change=change,
    )


@router.post("/gmail/search", response_model=GmailSearchRead)
def search_gmail(
    body: GmailSearchCreate,
    request: Request,
    identity: CurrentIdentity,
    key: WriteKey,
) -> dict[str, Any]:
    if identity.run_id is not None:
        raise HTTPException(
            403, "Pull email explicitly from the workspace before using it in agent work"
        )
    operation = "POST:/api/v1/gmail/search"
    payload = body.model_dump(mode="json")
    with Session(request.app.state.engine) as db:
        task_id, opportunity_id = _scope(db, identity)
        account = db.scalar(
            select(ExternalAccount).where(
                ExternalAccount.owner_id == identity.id,
                ExternalAccount.toolkit == "gmail",
                ExternalAccount.selected_purpose == "outreach",
                ExternalAccount.connection_status == "ACTIVE",
                ExternalAccount.archived_at.is_(None),
            )
        )
        if account is None:
            raise ValueError("Select a verified Gmail outreach account")
        if body.account_id is not None and body.account_id != account.id:
            raise HTTPException(
                422, "The selected Gmail account changed. Check Connected apps before pulling email"
            )
        account_id = account.id
        account_input = _metadata(account)
        stored_identity = dict(account.provider_identity)
        if identity.run_id is not None:
            fence_agent_write(request, db)
    adapter = _adapter(request)
    claim_id, replay = _claim_connected(
        request, actor_id=identity.id, key=key, operation=operation, payload=payload
    )
    if replay is not None:
        return replay
    budget = _budget(request, identity.id, task_id, opportunity_id, claim_id)
    try:
        metadata = adapter.account_metadata(
            connected_account_id=account_input.connected_account_id,
            expected_toolkit="gmail",
            expected_auth_config_id=account_input.auth_config_id,
            user_id=str(identity.id),
            operation_id=uuid5(claim_id, "account"),
            reserve_budget=budget,
        )
        verified = adapter.verify_identity(
            metadata,
            user_id=str(identity.id),
            charge=ChargeContext(uuid5(claim_id, "identity")),
            reserve_budget=budget,
        )
        if verified.identity.get("email") != stored_identity.get("email"):
            raise ProviderFailure("Gmail account identity changed")
        result = adapter.gmail_search(
            metadata,
            user_id=str(identity.id),
            query=body.query,
            max_results=body.max_results,
            charge=ChargeContext(uuid5(claim_id, "search")),
            reserve_budget=budget,
        )
    except SpendingDenied as exc:
        _deny_connected(request, claim_id, exc)
    except (ProviderFailure, ProviderOutcomeUnknown) as exc:
        unknown = isinstance(exc, ProviderOutcomeUnknown)
        _fail_connected(request, claim_id, "gmail_search_provider_failed", unknown=unknown)
        raise HTTPException(503, "Gmail search is temporarily unavailable") from exc
    except Exception:
        _fail_connected(request, claim_id, "gmail_search_failed", unknown=False)
        raise

    def change(db: Session, record_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        current = _owned_account(db, account_id, identity.id, lock=True)
        if current.selected_purpose != "outreach" or current.provider_identity.get(
            "email"
        ) != verified.identity.get("email"):
            raise ValueError("Selected Gmail account changed during search")
        observation = ProviderObservation.capture(
            record_id=record_id,
            owner_id=identity.id,
            account_id=current.id,
            task_id=task_id,
            opportunity_id=opportunity_id,
            kind="gmail_search",
            request=payload,
            result=result,
        )
        db.add(observation)
        db.flush()
        return GmailSearchRead(
            observation_id=observation.id,
            account_id=current.id,
            observed_at=observation.observed_at,
            messages=result["messages"],
            next_page_token=result["next_page_token"],
            result_size_estimate=result["result_size_estimate"],
        ).model_dump(mode="json")

    return _finalize_connected(
        request,
        claim_id=claim_id,
        actor_id=identity.id,
        key=key,
        operation=operation,
        payload=payload,
        change=change,
    )


@router.post("/integrations/composio/context", response_model=ConnectedContextRead)
def connected_context(
    body: ConnectedContextCreate,
    request: Request,
    identity: CurrentIdentity,
    key: WriteKey,
) -> dict[str, Any]:
    operation = "POST:/api/v1/integrations/composio/context"
    payload = body.model_dump(mode="json")
    with Session(request.app.state.engine) as db:
        task_id, opportunity_id = _scope(db, identity)
        account = _owned_account(db, body.account_id, identity.id)
        account.require_context_query(body.query)
        account_input = _metadata(account)
        stored_identity = dict(account.provider_identity)
        if identity.run_id is not None:
            fence_agent_write(request, db)
    adapter = _adapter(request)
    claim_id, replay = _claim_connected(
        request, actor_id=identity.id, key=key, operation=operation, payload=payload
    )
    if replay is not None:
        return replay
    budget = _budget(request, identity.id, task_id, opportunity_id, claim_id)
    try:
        metadata = adapter.account_metadata(
            connected_account_id=account_input.connected_account_id,
            expected_toolkit=account_input.toolkit,
            expected_auth_config_id=account_input.auth_config_id,
            user_id=str(identity.id),
            operation_id=uuid5(claim_id, "account"),
            reserve_budget=budget,
        )
        verified = adapter.verify_identity(
            metadata,
            user_id=str(identity.id),
            charge=ChargeContext(uuid5(claim_id, "identity")),
            reserve_budget=budget,
        )
        if verified.identity != stored_identity:
            raise ProviderFailure("Connected account identity changed")
        result = adapter.read_context(
            body.query,
            account=metadata,
            user_id=str(identity.id),
            charge=ChargeContext(uuid5(claim_id, "context")),
            reserve_budget=budget,
        )
    except SpendingDenied as exc:
        _deny_connected(request, claim_id, exc)
    except (ProviderFailure, ProviderOutcomeUnknown) as exc:
        unknown = isinstance(exc, ProviderOutcomeUnknown)
        _fail_connected(request, claim_id, "connected_context_provider_failed", unknown=unknown)
        raise HTTPException(503, "Connected context is temporarily unavailable") from exc
    except Exception:
        _fail_connected(request, claim_id, "connected_context_failed", unknown=False)
        raise

    def change(db: Session, record_id: UUID) -> dict[str, Any]:
        if identity.run_id is not None:
            fence_agent_write(request, db)
        current = _owned_account(db, body.account_id, identity.id, lock=True)
        current.require_context_query(body.query)
        if (
            current.composio_connected_account_id != metadata.connected_account_id
            or current.composio_auth_config_id != metadata.auth_config_id
            or current.provider_identity != verified.identity
        ):
            raise ValueError("Connected account changed during context retrieval")
        stored_result = {
            "context": result.context,
            "provider_log_ids": result.provider_log_ids,
            "truncated": result.truncated,
            "content_sha256": result.content_sha256,
        }
        observation = ProviderObservation.capture_context(
            db,
            request_id=UUID(request.state.request_id),
            record_id=record_id,
            owner_id=identity.id,
            account_id=current.id,
            task_id=task_id,
            opportunity_id=opportunity_id,
            kind=body.query.kind,
            request=payload,
            result=stored_result,
            external_revision=result.external_revision,
        )
        return ConnectedContextRead(
            observation_id=observation.id,
            account_id=current.id,
            kind=body.query.kind,
            observed_at=observation.observed_at,
            external_revision=result.external_revision,
            provider_log_ids=result.provider_log_ids,
            context=result.context,
            truncated=result.truncated,
            content_sha256=result.content_sha256,
        ).model_dump(mode="json")

    return _finalize_connected(
        request,
        claim_id=claim_id,
        actor_id=identity.id,
        key=key,
        operation=operation,
        payload=payload,
        change=change,
    )


def _observe_update(
    body: ActionFields | ActionVersionCreate,
    *,
    account: AccountMetadata,
    request: Request,
    identity: Identity,
    operation_id: UUID,
    request_scope_id: UUID,
    task_id: UUID | None,
    opportunity_id: UUID | None,
) -> tuple[str | None, dict[str, Any] | None]:
    payload = body.payload.model_dump(mode="json")
    if not payload["kind"].endswith("_update"):
        return None, None
    observation = _adapter(request).observe_target(
        kind=payload["kind"],
        payload=payload,
        account=account,
        user_id=str(identity.id),
        charge=ChargeContext(operation_id),
        reserve_budget=_budget(
            request,
            identity.id,
            task_id,
            opportunity_id,
            request_scope_id,
        ),
    )
    return observation.revision, observation.safe_snapshot


@router.post("/reviewed-actions", response_model=ActionRead, status_code=status.HTTP_201_CREATED)
def create_action(
    body: ActionCreate,
    request: Request,
    identity: CurrentIdentity,
    key: WriteKey,
) -> dict[str, Any]:
    operation = "POST:/api/v1/reviewed-actions"
    payload = body.model_dump(mode="json")
    with Session(request.app.state.engine) as db:
        run_task, run_opportunity = _scope(db, identity)
        task_id, opportunity_id = (
            (run_task, run_opportunity)
            if identity.run_id is not None
            else (body.task_id, body.opportunity_id)
        )
        if identity.run_id is not None and (
            (body.task_id is not None and body.task_id != task_id)
            or (body.opportunity_id is not None and body.opportunity_id != opportunity_id)
        ):
            raise HTTPException(403, "Agent action scope must match its current run")
        fence_agent_write(request, db)
        account = ReviewedAction._validate_context(
            db,
            owner_id=identity.id,
            account_id=body.account_id,
            kind=body.payload.kind,
            task_id=task_id,
            opportunity_id=opportunity_id,
            source_version_id=body.source_version_id,
            attachment_version_ids=body.attachment_version_ids,
            expected_remote_revision=("pending" if body.payload.kind.endswith("_update") else None),
            source_run_id=identity.run_id,
            expires_at=body.expires_at,
            reason=body.reason,
        )
        account_input = _metadata(account)
        stored_identity = dict(account.provider_identity)

    marker: str | None = None
    snapshot: dict[str, Any] | None = None
    claim_id: UUID | None = None
    if body.payload.kind.endswith("_update"):
        adapter = _adapter(request)
        claim_id, replay = _claim_connected(
            request, actor_id=identity.id, key=key, operation=operation, payload=payload
        )
        if replay is not None:
            return replay
        budget = _budget(request, identity.id, task_id, opportunity_id, claim_id)
        try:
            metadata = adapter.account_metadata(
                connected_account_id=account_input.connected_account_id,
                expected_toolkit=account_input.toolkit,
                expected_auth_config_id=account_input.auth_config_id,
                user_id=str(identity.id),
                operation_id=uuid5(claim_id, "account"),
                reserve_budget=budget,
            )
            verified = adapter.verify_identity(
                metadata,
                user_id=str(identity.id),
                charge=ChargeContext(uuid5(claim_id, "identity")),
                reserve_budget=budget,
            )
            if verified.identity != stored_identity:
                raise ProviderFailure("Connected account identity changed")
            marker, snapshot = _observe_update(
                body,
                account=metadata,
                request=request,
                identity=identity,
                operation_id=uuid5(claim_id, "proposal-observation"),
                request_scope_id=claim_id,
                task_id=task_id,
                opportunity_id=opportunity_id,
            )
        except SpendingDenied as exc:
            _deny_connected(request, claim_id, exc)
        except (ProviderFailure, ProviderOutcomeUnknown) as exc:
            unknown = isinstance(exc, ProviderOutcomeUnknown)
            _fail_connected(request, claim_id, "action_observation_failed", unknown=unknown)
            raise HTTPException(503, "Action target could not be observed") from exc
        except Exception:
            _fail_connected(request, claim_id, "action_observation_failed", unknown=False)
            raise

    def change(db: Session, record_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        action = ReviewedAction.propose(
            db,
            record_id=record_id,
            owner_id=identity.id,
            account_id=body.account_id,
            payload=body.payload,
            task_id=task_id,
            opportunity_id=opportunity_id,
            source_version_id=body.source_version_id,
            attachment_version_ids=body.attachment_version_ids,
            expected_remote_revision=marker,
            observed_target=snapshot,
            source_run_id=identity.run_id,
            expires_at=body.expires_at,
            reason=body.reason,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return _action_read(db, action).model_dump(mode="json")

    if claim_id is not None:
        return _finalize_connected(
            request,
            claim_id=claim_id,
            actor_id=identity.id,
            key=key,
            operation=operation,
            payload=payload,
            change=change,
        )
    with Session(request.app.state.engine) as db, db.begin():
        return _execute(
            db,
            actor_id=identity.id,
            key=key,
            operation=operation,
            payload=payload,
            change=lambda record_id: change(db, record_id),
        )


@router.get("/reviewed-actions", response_model=s.Page[ActionRead])
def list_actions(
    identity: CurrentIdentity, db: Database, limit: Limit = 50, offset: Offset = 0
) -> dict[str, Any]:
    _human(identity)
    where = (ReviewedAction.owner_id == identity.id, ReviewedAction.archived_at.is_(None))
    total = db.scalar(select(func.count()).select_from(ReviewedAction).where(*where)) or 0
    rows = db.scalars(
        select(ReviewedAction)
        .where(*where)
        .order_by(ReviewedAction.updated_at.desc(), ReviewedAction.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [_action_read(db, item) for item in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/reviewed-actions/{action_id}", response_model=ActionRead)
def get_action(action_id: UUID, identity: CurrentIdentity, db: Database) -> ActionRead:
    _human(identity)
    return _action_read(db, _owned_action(db, action_id, identity.id))


@router.get("/reviewed-actions/{action_id}/versions", response_model=list[ActionRevisionRead])
def list_action_versions(
    action_id: UUID, identity: CurrentIdentity, db: Database
) -> list[ActionRevisionRead]:
    _human(identity)
    action = _owned_action(db, action_id, identity.id)
    rows = db.scalars(
        select(ReviewedActionRevision)
        .where(ReviewedActionRevision.action_id == action.id)
        .order_by(ReviewedActionRevision.version.desc())
    ).all()
    return [_revision_read(db, row) for row in rows]


@router.patch("/reviewed-actions/{action_id}", response_model=ActionRead)
def revise_action(
    action_id: UUID,
    body: ActionVersionCreate,
    request: Request,
    identity: CurrentIdentity,
    key: WriteKey,
) -> dict[str, Any]:
    operation = f"PATCH:/api/v1/reviewed-actions/{action_id}"
    payload = body.model_dump(mode="json")
    with Session(request.app.state.engine) as db:
        fence_agent_write(request, db)
        action = _owned_action(db, action_id, identity.id)
        check_version(action, body.expected_version)
        if body.payload.kind != action.kind:
            raise ValueError("Action kind cannot change")
        account = _owned_account(db, action.account_id, identity.id)
        ReviewedAction._validate_context(
            db,
            owner_id=identity.id,
            account_id=action.account_id,
            kind=body.payload.kind,
            task_id=action.task_id,
            opportunity_id=action.opportunity_id,
            source_version_id=body.source_version_id,
            attachment_version_ids=body.attachment_version_ids,
            expected_remote_revision=("pending" if body.payload.kind.endswith("_update") else None),
            source_run_id=identity.run_id,
            expires_at=body.expires_at,
            reason=body.reason,
        )
        task_id, opportunity_id = action.task_id, action.opportunity_id
        account_id = action.account_id
        account_input = _metadata(account)
        stored_identity = dict(account.provider_identity)

    marker: str | None = None
    snapshot: dict[str, Any] | None = None
    claim_id: UUID | None = None
    if body.payload.kind.endswith("_update"):
        adapter = _adapter(request)
        claim_id, replay = _claim_connected(
            request, actor_id=identity.id, key=key, operation=operation, payload=payload
        )
        if replay is not None:
            return replay
        budget = _budget(request, identity.id, task_id, opportunity_id, claim_id)
        try:
            metadata = adapter.account_metadata(
                connected_account_id=account_input.connected_account_id,
                expected_toolkit=account_input.toolkit,
                expected_auth_config_id=account_input.auth_config_id,
                user_id=str(identity.id),
                operation_id=uuid5(claim_id, "account"),
                reserve_budget=budget,
            )
            verified = adapter.verify_identity(
                metadata,
                user_id=str(identity.id),
                charge=ChargeContext(uuid5(claim_id, "identity")),
                reserve_budget=budget,
            )
            if verified.identity != stored_identity:
                raise ProviderFailure("Connected account identity changed")
            marker, snapshot = _observe_update(
                body,
                account=metadata,
                request=request,
                identity=identity,
                operation_id=uuid5(claim_id, "revision-observation"),
                request_scope_id=claim_id,
                task_id=task_id,
                opportunity_id=opportunity_id,
            )
        except SpendingDenied as exc:
            _deny_connected(request, claim_id, exc)
        except (ProviderFailure, ProviderOutcomeUnknown) as exc:
            unknown = isinstance(exc, ProviderOutcomeUnknown)
            _fail_connected(request, claim_id, "action_observation_failed", unknown=unknown)
            raise HTTPException(503, "Action target could not be observed") from exc
        except Exception:
            _fail_connected(request, claim_id, "action_observation_failed", unknown=False)
            raise

    def change(db: Session, record_id: UUID) -> dict[str, Any]:
        fence_agent_write(request, db)
        action = _owned_action(db, action_id, identity.id, lock=True)
        check_version(action, body.expected_version)
        if action.account_id != account_id:
            raise ValueError("Reviewed action account changed")
        action.append_revision(
            payload=body.payload,
            source_version_id=body.source_version_id,
            attachment_version_ids=body.attachment_version_ids,
            expected_remote_revision=marker,
            observed_target=snapshot,
            source_run_id=identity.run_id,
            expires_at=body.expires_at,
            reason=body.reason,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return _action_read(db, action).model_dump(mode="json")

    if claim_id is not None:
        return _finalize_connected(
            request,
            claim_id=claim_id,
            actor_id=identity.id,
            key=key,
            operation=operation,
            payload=payload,
            change=change,
        )
    with Session(request.app.state.engine) as db, db.begin():
        return _execute(
            db,
            actor_id=identity.id,
            key=key,
            operation=operation,
            payload=payload,
            change=lambda record_id: change(db, record_id),
        )


@router.post("/reviewed-actions/{action_id}/reviews", response_model=ActionRead)
def review_action(
    action_id: UUID,
    body: ActionReviewCreate,
    request: Request,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
) -> dict[str, Any]:
    _human(identity)

    def change(record_id: UUID) -> dict[str, Any]:
        action = _owned_action(db, action_id, identity.id, lock=True)
        check_version(action, body.expected_version)
        action.review(
            revision_id=body.revision_id,
            reviewer_id=identity.id,
            reviewer_is_human=True,
            decision=body.decision,
            reason=body.reason,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return _action_read(db, action).model_dump(mode="json")

    return _execute(
        db,
        actor_id=identity.id,
        key=key,
        operation=f"POST:/api/v1/reviewed-actions/{action_id}/reviews",
        payload=body.model_dump(mode="json"),
        change=change,
    )


@router.post("/reviewed-actions/{action_id}/reconcile", response_model=ActionRead)
def reconcile_action(
    action_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    key: WriteKey,
) -> dict[str, Any]:
    _human(identity)
    operation = f"POST:/api/v1/reviewed-actions/{action_id}/reconcile"
    with Session(request.app.state.engine) as db:
        action = _owned_action(db, action_id, identity.id)
        attempt = db.scalar(
            select(ActionAttempt).where(
                ActionAttempt.action_id == action.id,
                ActionAttempt.state.in_(["outcome_unknown", "partial"]),
            )
        )
        revision = db.get(ReviewedActionRevision, action.approved_revision_id)
        account = db.get(ExternalAccount, action.account_id)
        if attempt is None or revision is None or account is None:
            raise ValueError("Only an unknown or partial approved attempt can be reconciled")
        source_text: str | None = None
        if revision.source_version_id:
            source = ReviewedAction._owned_text_version(db, identity.id, revision.source_version_id)
            source_text = cast(str, source.payload["text"]) if source.payload else None
        attempt_id = attempt.id
        revision_id = revision.id
        revision_payload = dict(revision.payload)
        account_input = _metadata(account)
        stored_identity = dict(account.provider_identity)
        task_id, opportunity_id = action.task_id, action.opportunity_id

    adapter = _adapter(request)
    claim_id, replay = _claim_connected(
        request, actor_id=identity.id, key=key, operation=operation, payload={}
    )
    if replay is not None:
        return replay
    budget = _budget(request, identity.id, task_id, opportunity_id, claim_id)
    try:
        metadata = adapter.account_metadata(
            connected_account_id=account_input.connected_account_id,
            expected_toolkit=account_input.toolkit,
            expected_auth_config_id=account_input.auth_config_id,
            user_id=str(identity.id),
            operation_id=uuid5(claim_id, "account"),
            reserve_budget=budget,
        )
        verified = adapter.verify_identity(
            metadata,
            user_id=str(identity.id),
            charge=ChargeContext(uuid5(claim_id, "identity")),
            reserve_budget=budget,
        )
        if verified.identity != stored_identity:
            raise ProviderFailure("Connected account identity changed")
        receipt = adapter.reconcile(
            revision_id=revision_id,
            payload=revision_payload,
            account=metadata,
            user_id=str(identity.id),
            source_text=source_text,
            reserve_budget=budget,
            operation_id=uuid5(claim_id, "reconcile"),
        )
    except SpendingDenied as exc:
        _deny_connected(request, claim_id, exc)
    except (ProviderFailure, ProviderOutcomeUnknown) as exc:
        unknown = isinstance(exc, ProviderOutcomeUnknown)
        _fail_connected(request, claim_id, "action_reconciliation_failed", unknown=unknown)
        raise HTTPException(503, "Action reconciliation is temporarily unavailable") from exc
    except Exception:
        _fail_connected(request, claim_id, "action_reconciliation_failed", unknown=False)
        raise

    def change(db: Session, record_id: UUID) -> dict[str, Any]:
        locked = _owned_action(db, action_id, identity.id, lock=True)
        locked_attempt = db.get(ActionAttempt, attempt_id, with_for_update=True)
        if locked_attempt is None or locked_attempt.state not in {
            "outcome_unknown",
            "partial",
        }:
            raise ValueError("Action reconciliation state changed")
        locked_attempt.reconciliation = {
            "state": receipt.state,
            "log_id": receipt.log_id,
            "external_id": receipt.external_id,
            "url": receipt.url,
            "remote_revision": receipt.remote_revision,
            "data": receipt.data,
        }
        if receipt.state == "succeeded":
            locked_attempt.state = "succeeded"
            locked.state = "succeeded"
        record_event(
            db,
            identity.id,
            UUID(request.state.request_id),
            "reviewed_action.reconciled",
            "reviewed_actions",
            locked.id,
            attempt_id=str(locked_attempt.id),
            reconciliation_state=receipt.state,
        )
        db.flush()
        return _action_read(db, locked).model_dump(mode="json")

    return _finalize_connected(
        request,
        claim_id=claim_id,
        actor_id=identity.id,
        key=key,
        operation=operation,
        payload={},
        change=change,
    )
