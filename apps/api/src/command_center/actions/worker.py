"""Claim once, dispatch once, and fence durable reviewed-action outcomes."""

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.core.storage import BlobStore
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.crm import record_event
from command_center.db.reviewed_actions import (
    ActionAttempt,
    ExternalAccount,
    ReviewedAction,
    ReviewedActionAttachment,
    ReviewedActionRevision,
)
from command_center.db.spending import SpendingDenied
from command_center.integrations.composio_actions import (
    AccountMetadata,
    AttachmentBytes,
    ChargeContext,
    ComposioActionClient,
    ProviderFailure,
    ProviderOutcomeUnknown,
    ReserveBudget,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedAttachment:
    name: str
    media_type: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ClaimedAction:
    action_id: UUID
    attempt_id: UUID
    lease_id: UUID
    owner_id: UUID
    task_id: UUID | None
    opportunity_id: UUID | None
    revision_id: UUID
    kind: str
    tool_slug: str
    toolkit_version: str
    payload: dict[str, Any]
    expected_remote_revision: str | None
    source_text: str | None
    attachments: tuple[ClaimedAttachment, ...]
    account: AccountMetadata
    stored_identity: dict[str, Any]


def claim(engine: Engine, action_id: UUID) -> ClaimedAction | None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        attempt = ReviewedAction.claim(db, action_id)
        if attempt is None:
            return None
        action = db.get(ReviewedAction, attempt.action_id)
        revision = db.get(ReviewedActionRevision, attempt.revision_id)
        account = db.get(ExternalAccount, action.account_id) if action else None
        if action is None or revision is None or account is None or attempt.lease_id is None:
            raise ValueError("Reviewed action claim lineage is incomplete")
        if (
            account.connection_status != "ACTIVE"
            or account.archived_at is not None
            or (action.kind == "gmail_send" and account.selected_purpose != "outreach")
        ):
            attempt.finish("failed", error_code="account_unavailable")
            action.state = "failed"
            return None
        source_text: str | None = None
        if revision.source_version_id is not None:
            source = ReviewedAction._owned_text_version(
                db, action.owner_id, revision.source_version_id, email=action.kind == "gmail_send"
            )
            canonical = json.dumps(
                source.payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            if hashlib.sha256(canonical).hexdigest() != source.content_sha256:
                attempt.finish("failed", error_code="source_digest_mismatch")
                action.state = "failed"
                return None
            source_text = cast(str, (source.payload or {})["text"])
        attachment_rows = db.execute(
            select(ReviewedActionAttachment, ArtifactVersion, Artifact)
            .join(
                ArtifactVersion,
                ArtifactVersion.id == ReviewedActionAttachment.artifact_version_id,
            )
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ReviewedActionAttachment.revision_id == revision.id,
                Artifact.owner_id == action.owner_id,
                Artifact.archived_at.is_(None),
            )
            .order_by(ReviewedActionAttachment.position)
        ).all()
        attachments = tuple(
            ClaimedAttachment(
                name=artifact.title,
                media_type=attachment.media_type,
                content_sha256=attachment.content_sha256,
            )
            for attachment, _version, artifact in attachment_rows
        )
        return ClaimedAction(
            action_id=action.id,
            attempt_id=attempt.id,
            lease_id=attempt.lease_id,
            owner_id=action.owner_id,
            task_id=action.task_id,
            opportunity_id=action.opportunity_id,
            revision_id=revision.id,
            kind=action.kind,
            tool_slug=revision.tool_slug,
            toolkit_version=revision.toolkit_version,
            payload=revision.payload,
            expected_remote_revision=revision.expected_remote_revision,
            source_text=source_text,
            attachments=attachments,
            account=AccountMetadata(
                connected_account_id=account.composio_connected_account_id,
                toolkit=account.toolkit,
                auth_config_id=account.composio_auth_config_id,
                status=account.connection_status,
                is_disabled=False,
                provider_updated_at=account.provider_updated_at,
                provider_identity=account.provider_identity,
            ),
            stored_identity=account.provider_identity,
        )


def _finish(
    engine: Engine,
    claimed: ClaimedAction,
    *,
    state: str,
    receipt: dict[str, Any] | None = None,
    before_revision: str | None = None,
    after_revision: str | None = None,
    provider_log_id: str | None = None,
    provider_external_id: str | None = None,
    provider_url: str | None = None,
    error_code: str | None = None,
) -> None:
    with Session(engine) as db, db.begin():
        attempt = db.scalar(
            select(ActionAttempt).where(ActionAttempt.id == claimed.attempt_id).with_for_update()
        )
        action = db.scalar(
            select(ReviewedAction).where(ReviewedAction.id == claimed.action_id).with_for_update()
        )
        if attempt is None or action is None or not attempt.accepts(claimed.lease_id):
            return
        if state == "outcome_unknown":
            attempt.finish_unknown(error_code or "provider_outcome_unknown")
            attempt.receipt = receipt
            attempt.provider_log_id = provider_log_id
        else:
            attempt.finish(
                cast(Any, state),
                provider_log_id=provider_log_id,
                provider_external_id=provider_external_id,
                provider_url=provider_url,
                receipt=receipt,
                before_revision=before_revision,
                after_revision=after_revision,
                error_code=error_code,
            )
        action.state = cast(Any, state)
        record_event(
            db,
            action.owner_id,
            uuid5(attempt.id, "reviewed-action-result"),
            "reviewed_action.executed",
            "reviewed_actions",
            action.id,
            revision_id=str(claimed.revision_id),
            attempt_id=str(attempt.id),
            state=state,
            error_code=error_code,
        )


def perform_reviewed_action(
    engine: Engine,
    settings: Settings,
    action_id: UUID | str,
    *,
    reserve_budget: ReserveBudget,
    adapter: ComposioActionClient | None = None,
) -> bool:
    """Execute one approved revision; broker redelivery cannot dispatch it twice."""
    claimed = claim(engine, UUID(str(action_id)))
    if claimed is None:
        return False
    own_adapter = adapter is None
    client = adapter
    stage = "account"
    try:
        if client is None:
            api_key = settings.composio_api_key.get_secret_value()
            if not api_key:
                _finish(
                    engine,
                    claimed,
                    state="failed",
                    error_code="action_provider_not_configured",
                )
                return True
            client = ComposioActionClient(
                api_key=api_key,
                timeout_seconds=int(settings.composio_action_timeout_seconds),
            )
        metadata = client.account_metadata(
            connected_account_id=claimed.account.connected_account_id,
            expected_toolkit=claimed.account.toolkit,
            expected_auth_config_id=claimed.account.auth_config_id,
            user_id=str(claimed.owner_id),
            operation_id=uuid5(claimed.attempt_id, "account"),
            reserve_budget=reserve_budget,
        )
        identity = client.verify_identity(
            metadata,
            user_id=str(claimed.owner_id),
            charge=ChargeContext(uuid5(claimed.attempt_id, "account-identity")),
            reserve_budget=reserve_budget,
        )
        if identity.identity != claimed.stored_identity:
            _finish(engine, claimed, state="failed", error_code="account_identity_changed")
            return True
        metadata = replace(metadata, provider_identity=identity.identity)
        before_revision: str | None = None
        if claimed.kind.endswith("_update"):
            stage = "preflight"
            observed = client.observe_target(
                kind=claimed.kind,
                payload=claimed.payload,
                account=metadata,
                user_id=str(claimed.owner_id),
                charge=ChargeContext(uuid5(claimed.attempt_id, "target-preflight")),
                reserve_budget=reserve_budget,
            )
            before_revision = observed.revision
            if observed.revision != claimed.expected_remote_revision:
                _finish(
                    engine,
                    claimed,
                    state="conflicted",
                    before_revision=observed.revision,
                    error_code="target_revision_changed",
                    receipt=observed.safe_snapshot,
                )
                return True
        store = BlobStore(settings.blob_store_path)
        attachments = [
            AttachmentBytes(
                name=item.name,
                media_type=item.media_type,
                content_sha256=item.content_sha256,
                content=store.read(item.content_sha256),
            )
            for item in claimed.attachments
        ]
        stage = "write"
        outcome = client.execute_write(
            operation_id=claimed.attempt_id,
            revision_id=claimed.revision_id,
            tool_slug=claimed.tool_slug,
            toolkit_version=claimed.toolkit_version,
            payload=claimed.payload,
            account=metadata,
            user_id=str(claimed.owner_id),
            source_text=claimed.source_text,
            attachments=attachments,
            reserve_budget=reserve_budget,
        )
        _finish(
            engine,
            claimed,
            state=outcome.state,
            receipt=outcome.data,
            before_revision=before_revision,
            after_revision=outcome.remote_revision,
            provider_log_id=outcome.log_id,
            provider_external_id=outcome.external_id,
            provider_url=outcome.url,
        )
        return True
    except SpendingDenied as exc:
        _finish(engine, claimed, state="failed", error_code=exc.code)
        return True
    except ProviderOutcomeUnknown:
        _finish(
            engine,
            claimed,
            state="outcome_unknown" if stage == "write" else "failed",
            error_code=(
                "provider_outcome_unknown" if stage == "write" else "provider_preflight_unknown"
            ),
        )
        return True
    except ProviderFailure:
        _finish(engine, claimed, state="failed", error_code=f"provider_{stage}_failed")
        return True
    except Exception:
        logger.warning("Reviewed action %s failed; provider details suppressed", claimed.action_id)
        _finish(
            engine,
            claimed,
            state="outcome_unknown" if stage == "write" else "failed",
            error_code="unexpected_after_dispatch"
            if stage == "write"
            else "action_preflight_failed",
        )
        return True
    finally:
        if own_adapter and client is not None:
            client.close()
