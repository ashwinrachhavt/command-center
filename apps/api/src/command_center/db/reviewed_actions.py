"""Exact, human-reviewed external effects and their durable outcomes."""

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    model_validator,
)
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import Opportunity, OwnedRecord, record_event
from command_center.db.errors import RecordConflict
from command_center.db.models import Task

ActionKind = Literal[
    "gmail_send",
    "calendar_create",
    "calendar_update",
    "linear_create",
    "linear_update",
    "notion_publish",
    "notion_update",
]
ActionState = Literal[
    "proposed",
    "queued",
    "running",
    "succeeded",
    "failed",
    "outcome_unknown",
    "partial",
    "conflicted",
    "rejected",
    "revoked",
]
ReviewDecision = Literal["approved", "rejected", "revoked"]
ReviewState = Literal["proposed", "approved", "rejected", "revoked"]
ConnectedContextKind = Literal["calendar_events", "calendar_event", "linear_issue", "notion_page"]

TOOLKIT_FOR_KIND: dict[str, str] = {
    "gmail_send": "gmail",
    "calendar_create": "googlecalendar",
    "calendar_update": "googlecalendar",
    "linear_create": "linear",
    "linear_update": "linear",
    "notion_publish": "notion",
    "notion_update": "notion",
}
TOOL_FOR_KIND: dict[str, str] = {
    "gmail_send": "GMAIL_SEND_EMAIL",
    "calendar_create": "GOOGLECALENDAR_CREATE_EVENT",
    "calendar_update": "GOOGLECALENDAR_PATCH_EVENT",
    "linear_create": "LINEAR_CREATE_LINEAR_ISSUE",
    "linear_update": "LINEAR_UPDATE_ISSUE",
    "notion_publish": "NOTION_CREATE_NOTION_PAGE",
    "notion_update": "NOTION_REPLACE_PAGE_CONTENT",
}
ACTION_LABEL_FOR_KIND: dict[str, str] = {
    "gmail_send": "Send Gmail message",
    "calendar_create": "Create Google Calendar event",
    "calendar_update": "Update Google Calendar event",
    "linear_create": "Create Linear issue",
    "linear_update": "Update Linear issue",
    "notion_publish": "Publish Notion page",
    "notion_update": "Update Notion page",
}
TOOLKIT_VERSIONS = {
    "gmail": "20260915_00",
    "googlecalendar": "20260915_00",
    "linear": "20260915_00",
    "notion": "20260707_00",
}
CONDITIONAL_UPDATE_NOTICE = (
    "The provider tool does not expose a conditional revision header. Command Center checks the "
    "target immediately before execution, but a remote edit can still race with the write."
)
CONTEXT_TOOLKIT_FOR_KIND: dict[str, str] = {
    "calendar_events": "googlecalendar",
    "calendar_event": "googlecalendar",
    "linear_issue": "linear",
    "notion_page": "notion",
}


class ContextQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: ConnectedContextKind


class CalendarEventsQuery(ContextQuery):
    kind: Literal["calendar_events"]
    calendar_id: str = Field(default="primary", min_length=1, max_length=300)
    time_min: AwareDatetime
    time_max: AwareDatetime
    max_results: int = Field(default=20, ge=1, le=50)
    page_token: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def bounded_window(self) -> "CalendarEventsQuery":
        if self.time_max <= self.time_min:
            raise ValueError("Calendar context end must follow its start")
        if self.time_max - self.time_min > timedelta(days=31):
            raise ValueError("Calendar context is limited to 31 days")
        return self


class CalendarEventQuery(ContextQuery):
    kind: Literal["calendar_event"]
    calendar_id: str = Field(default="primary", min_length=1, max_length=300)
    event_id: str = Field(min_length=1, max_length=500)


class LinearIssueQuery(ContextQuery):
    kind: Literal["linear_issue"]
    issue_id: str = Field(min_length=1, max_length=100)


class NotionPageQuery(ContextQuery):
    kind: Literal["notion_page"]
    page_id: str = Field(min_length=1, max_length=100)


ConnectedContextQuery = Annotated[
    CalendarEventsQuery | CalendarEventQuery | LinearIssueQuery | NotionPageQuery,
    Field(discriminator="kind"),
]
CONNECTED_CONTEXT_QUERY: TypeAdapter[ConnectedContextQuery] = TypeAdapter(ConnectedContextQuery)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: ActionKind


class GmailSendPayload(Payload):
    kind: Literal["gmail_send"]
    to: list[EmailStr] = Field(min_length=1, max_length=50)
    cc: list[EmailStr] = Field(default_factory=list, max_length=50)
    bcc: list[EmailStr] = Field(default_factory=list, max_length=50)
    subject: str = Field(max_length=998)
    body: str = Field(max_length=100_000)
    is_html: bool = False

    @model_validator(mode="after")
    def content(self) -> "GmailSendPayload":
        if not self.subject and not self.body:
            raise ValueError("Email needs a subject or body")
        if len({str(address).casefold() for address in self.to + self.cc + self.bcc}) != len(
            self.to + self.cc + self.bcc
        ):
            raise ValueError("Email recipients must be unique")
        return self


class CalendarCreatePayload(Payload):
    kind: Literal["calendar_create"]
    calendar_id: str = Field(default="primary", min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=20_000)
    start_at: AwareDatetime
    end_at: AwareDatetime
    timezone: str = Field(min_length=1, max_length=100)
    attendees: list[EmailStr] = Field(default_factory=list, max_length=100)
    send_updates: Literal["all", "externalOnly", "none"] = "all"
    create_meeting_room: bool = False

    @model_validator(mode="after")
    def time_range(self) -> "CalendarCreatePayload":
        if self.end_at <= self.start_at:
            raise ValueError("Calendar event end must follow its start")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use an IANA calendar timezone") from exc
        return self


class CalendarUpdatePayload(Payload):
    kind: Literal["calendar_update"]
    calendar_id: str = Field(default="primary", min_length=1, max_length=300)
    event_id: str = Field(min_length=1, max_length=500)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=20_000)
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    attendees: list[EmailStr] | None = Field(default=None, max_length=100)
    send_updates: Literal["all", "externalOnly", "none"] = "all"

    @model_validator(mode="after")
    def changes(self) -> "CalendarUpdatePayload":
        changed = (self.summary, self.description, self.start_at, self.end_at, self.attendees)
        if all(value is None for value in changed):
            raise ValueError("Calendar update needs at least one changed field")
        if (self.start_at is None) != (self.end_at is None):
            raise ValueError("Change calendar start and end together")
        if self.start_at is not None and self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("Calendar event end must follow its start")
        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Use an IANA calendar timezone") from exc
        return self


class LinearCreatePayload(Payload):
    kind: Literal["linear_create"]
    team_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=50_000)
    priority: int = Field(default=0, ge=0, le=4)
    due_date: date | None = None
    state_id: str | None = Field(default=None, max_length=100)
    assignee_id: str | None = Field(default=None, max_length=100)
    label_ids: list[str] = Field(default_factory=list, max_length=100)


class LinearUpdatePayload(Payload):
    kind: Literal["linear_update"]
    issue_id: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=50_000)
    priority: int | None = Field(default=None, ge=0, le=4)
    due_date: date | None = None
    state_id: str | None = Field(default=None, max_length=100)
    assignee_id: str | None = Field(default=None, max_length=100)
    label_ids: list[str] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def changes(self) -> "LinearUpdatePayload":
        changed = (
            self.title,
            self.description,
            self.priority,
            self.due_date,
            self.state_id,
            self.assignee_id,
            self.label_ids,
        )
        if all(value is None for value in changed):
            raise ValueError("Linear update needs at least one changed field")
        return self


class NotionPublishPayload(Payload):
    kind: Literal["notion_publish"]
    parent_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=1000)


class NotionUpdatePayload(Payload):
    kind: Literal["notion_update"]
    page_id: str = Field(min_length=1, max_length=100)


ActionPayload = Annotated[
    GmailSendPayload
    | CalendarCreatePayload
    | CalendarUpdatePayload
    | LinearCreatePayload
    | LinearUpdatePayload
    | NotionPublishPayload
    | NotionUpdatePayload,
    Field(discriminator="kind"),
]
ACTION_PAYLOAD: TypeAdapter[ActionPayload] = TypeAdapter(ActionPayload)


def canonical_payload(payload: ActionPayload | dict[str, Any]) -> tuple[dict[str, Any], str]:
    model = payload if isinstance(payload, Payload) else ACTION_PAYLOAD.validate_python(payload)
    data = model.model_dump(mode="json")
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return data, hashlib.sha256(encoded).hexdigest()


class ExternalAccount(OwnedRecord, Base):
    """Safe local reference to one actor-owned Composio connection."""

    __tablename__ = "external_accounts"
    __table_args__ = (
        CheckConstraint(
            "toolkit IN ('gmail', 'googlecalendar', 'linear', 'notion')", name="toolkit"
        ),
        CheckConstraint(
            "connection_status IN ('ACTIVE', 'INACTIVE', 'EXPIRED', 'REVOKED', 'FAILED')",
            name="connection_status",
        ),
        UniqueConstraint("owner_id", "composio_connected_account_id"),
        UniqueConstraint("id", "owner_id"),
        Index(
            "uq_external_accounts_selected_purpose",
            "owner_id",
            "selected_purpose",
            unique=True,
            postgresql_where=text("selected_purpose IS NOT NULL"),
        ),
    )

    toolkit: Mapped[str] = mapped_column(String(30), index=True)
    composio_connected_account_id: Mapped[str] = mapped_column(String(200))
    composio_auth_config_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(300))
    provider_identity: Mapped[dict[str, Any]] = mapped_column(JSONB)
    connection_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    provider_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    identity_verified_at: Mapped[datetime] = mapped_column(UTCDateTime)
    selected_purpose: Mapped[str | None] = mapped_column(String(50))

    def require_context_query(self, query: ConnectedContextQuery) -> None:
        if self.connection_status != "ACTIVE" or self.archived_at is not None:
            raise ValueError("Choose an active connected account")
        if self.toolkit != CONTEXT_TOOLKIT_FOR_KIND[query.kind]:
            raise ValueError("Connected account does not match this context query")

    @classmethod
    def sync(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        toolkit: str,
        connected_account_id: str,
        auth_config_id: str,
        display_name: str,
        provider_identity: dict[str, Any],
        connection_status: str,
        provider_updated_at: datetime | None,
        request_id: UUID,
        record_id: UUID | None = None,
    ) -> "ExternalAccount":
        if toolkit not in TOOLKIT_VERSIONS or connection_status != "ACTIVE":
            raise ValueError("Only active supported connections can be synchronized")
        if not display_name.strip() or not provider_identity:
            raise ValueError("Verified provider identity is required")
        account = session.scalar(
            select(cls).where(
                cls.owner_id == owner_id,
                cls.composio_connected_account_id == connected_account_id,
            )
        )
        created = account is None
        if account is None:
            account = cls(
                id=record_id or uuid4(),
                owner_id=owner_id,
                toolkit=toolkit,
                composio_connected_account_id=connected_account_id,
                composio_auth_config_id=auth_config_id,
                display_name=display_name.strip(),
                provider_identity=provider_identity,
                connection_status="ACTIVE",
                provider_updated_at=provider_updated_at,
                identity_verified_at=utc_now(),
            )
            session.add(account)
        else:
            if account.toolkit != toolkit:
                raise RecordConflict("Connected account toolkit changed")
            identity_changed = account.provider_identity != provider_identity
            account.composio_auth_config_id = auth_config_id
            account.display_name = display_name.strip()
            account.provider_identity = provider_identity
            account.connection_status = "ACTIVE"
            account.provider_updated_at = provider_updated_at
            account.identity_verified_at = utc_now()
            if identity_changed:
                account.selected_purpose = None
            account.updated_at = utc_now()
        session.flush()
        record_event(
            session,
            owner_id,
            request_id,
            "external_account.synced" if created else "external_account.verified",
            "external_accounts",
            account.id,
            toolkit=toolkit,
        )
        return account

    def select_for(self, purpose: Literal["outreach"], *, request_id: UUID) -> None:
        if purpose != "outreach" or self.toolkit != "gmail" or self.connection_status != "ACTIVE":
            raise ValueError("Outreach requires an active Gmail account")
        session = object_session(self)
        if session is None:
            raise ValueError("Select a persisted account")
        session.execute(
            update(ExternalAccount)
            .where(
                ExternalAccount.owner_id == self.owner_id,
                ExternalAccount.selected_purpose == purpose,
                ExternalAccount.id != self.id,
            )
            .values(selected_purpose=None),
            execution_options={"synchronize_session": False},
        )
        self.selected_purpose = purpose
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "external_account.selected",
            "external_accounts",
            self.id,
            purpose=purpose,
        )


class ReviewedAction(OwnedRecord, Base):
    """Mutable pointers and execution state over exact immutable proposals."""

    __tablename__ = "reviewed_actions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('gmail_send','calendar_create','calendar_update','linear_create',"
            "'linear_update','notion_publish','notion_update')",
            name="kind",
        ),
        CheckConstraint(
            "state IN ('proposed','queued','running','succeeded','failed','outcome_unknown',"
            "'partial','conflicted','rejected','revoked')",
            name="state",
        ),
        CheckConstraint("row_version >= 1", name="row_version"),
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["account_id", "owner_id"], ["external_accounts.id", "external_accounts.owner_id"]
        ),
        ForeignKeyConstraint(
            ["current_revision_id", "id"],
            ["reviewed_action_revisions.id", "reviewed_action_revisions.action_id"],
            name="fk_reviewed_actions_current_revision",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["approved_revision_id", "id"],
            ["reviewed_action_revisions.id", "reviewed_action_revisions.action_id"],
            name="fk_reviewed_actions_approved_revision",
            use_alter=True,
        ),
    )

    kind: Mapped[ActionKind] = mapped_column(String(30), index=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), index=True)
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    approved_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    state: Mapped[ActionState] = mapped_column(String(30), default="proposed", index=True)

    @classmethod
    def propose(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        account_id: UUID,
        payload: ActionPayload | dict[str, Any],
        task_id: UUID | None,
        opportunity_id: UUID | None,
        source_version_id: UUID | None,
        attachment_version_ids: list[UUID],
        expected_remote_revision: str | None,
        observed_target: dict[str, Any] | None,
        source_run_id: UUID | None,
        expires_at: datetime | None,
        reason: str,
        request_id: UUID,
    ) -> "ReviewedAction":
        data, digest = canonical_payload(payload)
        kind = data["kind"]
        account = cls._validate_context(
            session,
            owner_id=owner_id,
            account_id=account_id,
            kind=kind,
            task_id=task_id,
            opportunity_id=opportunity_id,
            source_version_id=source_version_id,
            attachment_version_ids=attachment_version_ids,
            expected_remote_revision=expected_remote_revision,
            source_run_id=source_run_id,
            expires_at=expires_at,
            reason=reason,
        )
        action = cls(
            id=record_id,
            owner_id=owner_id,
            kind=kind,
            account_id=account.id,
            task_id=task_id,
            opportunity_id=opportunity_id,
            state="proposed",
        )
        session.add(action)
        session.flush()
        revision = ReviewedActionRevision(
            action_id=action.id,
            version=1,
            tool_slug=TOOL_FOR_KIND[kind],
            toolkit_version=TOOLKIT_VERSIONS[account.toolkit],
            payload=data,
            payload_hash=digest,
            source_version_id=source_version_id,
            expected_remote_revision=expected_remote_revision,
            observed_target=observed_target,
            source_run_id=source_run_id,
            expires_at=expires_at,
            proposed_by_id=owner_id,
            reason=reason.strip(),
        )
        session.add(revision)
        session.flush()
        cls._add_attachments(session, revision, owner_id, attachment_version_ids)
        session.execute(
            update(cls).where(cls.id == action.id).values(current_revision_id=revision.id),
            execution_options={"synchronize_session": False},
        )
        session.refresh(action)
        record_event(
            session,
            owner_id,
            request_id,
            "reviewed_action.proposed",
            "reviewed_actions",
            action.id,
            revision_id=str(revision.id),
            kind=kind,
            account_id=str(account.id),
        )
        return action

    def append_revision(
        self,
        *,
        payload: ActionPayload | dict[str, Any],
        source_version_id: UUID | None,
        attachment_version_ids: list[UUID],
        expected_remote_revision: str | None,
        observed_target: dict[str, Any] | None,
        source_run_id: UUID | None,
        expires_at: datetime | None,
        reason: str,
        request_id: UUID,
    ) -> "ReviewedActionRevision":
        session = object_session(self)
        if session is None or self.current_revision_id is None:
            raise ValueError("Revise a persisted action")
        if self.state in {"running", "succeeded", "outcome_unknown", "partial"}:
            raise RecordConflict("This action already reached the provider boundary")
        data, digest = canonical_payload(payload)
        if data["kind"] != self.kind:
            raise ValueError("Action kind cannot change")
        self._validate_context(
            session,
            owner_id=self.owner_id,
            account_id=self.account_id,
            kind=self.kind,
            task_id=self.task_id,
            opportunity_id=self.opportunity_id,
            source_version_id=source_version_id,
            attachment_version_ids=attachment_version_ids,
            expected_remote_revision=expected_remote_revision,
            source_run_id=source_run_id,
            expires_at=expires_at,
            reason=reason,
        )
        current = session.get(ReviewedActionRevision, self.current_revision_id)
        if current is None:
            raise ValueError("Action current revision is missing")
        revision = ReviewedActionRevision(
            action_id=self.id,
            version=current.version + 1,
            tool_slug=TOOL_FOR_KIND[self.kind],
            toolkit_version=current.toolkit_version,
            payload=data,
            payload_hash=digest,
            source_version_id=source_version_id,
            expected_remote_revision=expected_remote_revision,
            observed_target=observed_target,
            source_run_id=source_run_id,
            expires_at=expires_at,
            proposed_by_id=self.owner_id,
            reason=reason.strip(),
        )
        session.add(revision)
        session.flush()
        self._add_attachments(session, revision, self.owner_id, attachment_version_ids)
        self.current_revision_id = revision.id
        self.approved_revision_id = None
        self.state = "proposed"
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "reviewed_action.revised",
            "reviewed_actions",
            self.id,
            revision_id=str(revision.id),
            version=revision.version,
        )
        return revision

    def review(
        self,
        *,
        revision_id: UUID,
        reviewer_id: UUID,
        reviewer_is_human: bool,
        decision: ReviewDecision,
        reason: str,
        request_id: UUID,
    ) -> "ReviewedActionReview":
        if not reviewer_is_human or reviewer_id != self.owner_id:
            raise PermissionError("Only the human owner can review an external action")
        if not reason.strip() or len(reason) > 2000:
            raise ValueError("Review reason must contain 1 to 2000 characters")
        session = object_session(self)
        if session is None:
            raise ValueError("Review a persisted action")
        revision = session.scalar(
            select(ReviewedActionRevision).where(
                ReviewedActionRevision.id == revision_id,
                ReviewedActionRevision.action_id == self.id,
            )
        )
        if revision is None:
            raise ValueError("Revision does not belong to this action")
        state = revision.review_state(session)
        if decision == "revoked":
            if self.approved_revision_id != revision.id or self.state != "queued":
                raise RecordConflict("Only a queued approved action can be revoked")
            self.approved_revision_id = None
            self.state = "revoked"
        else:
            if self.current_revision_id != revision.id or state != "proposed":
                raise RecordConflict("Only the current proposal can be reviewed")
            if decision == "approved":
                if revision.expires_at is not None and revision.expires_at <= utc_now():
                    raise RecordConflict("Expired actions cannot be approved")
                self.approved_revision_id = revision.id
                self.state = "queued"
            else:
                self.approved_revision_id = None
                self.state = "rejected"
        review = ReviewedActionReview(
            action_id=self.id,
            revision_id=revision.id,
            reviewer_id=reviewer_id,
            decision=decision,
            reason=reason.strip(),
        )
        session.add(review)
        self.updated_at = utc_now()
        record_event(
            session,
            reviewer_id,
            request_id,
            "reviewed_action.reviewed",
            "reviewed_actions",
            self.id,
            revision_id=str(revision.id),
            decision=decision,
        )
        return review

    @classmethod
    def claim(cls, session: Session, action_id: UUID | None = None) -> "ActionAttempt | None":
        statement = (
            select(cls)
            .join(ReviewedActionRevision, ReviewedActionRevision.id == cls.approved_revision_id)
            .where(
                cls.state == "queued",
                (ReviewedActionRevision.expires_at.is_(None))
                | (ReviewedActionRevision.expires_at > utc_now()),
            )
            .order_by(cls.updated_at, cls.id)
        )
        if action_id is not None:
            statement = statement.where(cls.id == action_id)
        action = session.scalar(statement.with_for_update(skip_locked=True))
        if action is None or action.approved_revision_id != action.current_revision_id:
            return None
        existing = session.scalar(
            select(ActionAttempt).where(ActionAttempt.revision_id == action.approved_revision_id)
        )
        if existing is not None:
            return None
        attempt = ActionAttempt(
            action_id=action.id,
            revision_id=action.approved_revision_id,
            attempt_number=1,
            state="running",
            lease_id=uuid4(),
            lease_expires_at=utc_now() + timedelta(minutes=5),
            started_at=utc_now(),
        )
        session.add(attempt)
        action.state = "running"
        action.updated_at = utc_now()
        session.flush()
        return attempt

    @classmethod
    def expire_stale(cls, session: Session) -> int:
        attempts = session.scalars(
            select(ActionAttempt)
            .where(
                ActionAttempt.state == "running",
                ActionAttempt.lease_expires_at < utc_now(),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for attempt in attempts:
            action = session.get(cls, attempt.action_id)
            attempt.finish_unknown("worker_lease_expired")
            if action is not None:
                action.state = "outcome_unknown"
                action.updated_at = utc_now()
        return len(attempts)

    @staticmethod
    def _validate_context(
        session: Session,
        *,
        owner_id: UUID,
        account_id: UUID,
        kind: str,
        task_id: UUID | None,
        opportunity_id: UUID | None,
        source_version_id: UUID | None,
        attachment_version_ids: list[UUID],
        expected_remote_revision: str | None,
        source_run_id: UUID | None,
        expires_at: datetime | None,
        reason: str,
    ) -> ExternalAccount:
        account = session.scalar(
            select(ExternalAccount).where(
                ExternalAccount.id == account_id,
                ExternalAccount.owner_id == owner_id,
                ExternalAccount.archived_at.is_(None),
            )
        )
        if account is None or account.connection_status != "ACTIVE":
            raise ValueError("Choose an active owned external account")
        if account.toolkit != TOOLKIT_FOR_KIND[kind]:
            raise ValueError("Connected account does not match this action")
        if kind == "gmail_send" and account.selected_purpose != "outreach":
            raise ValueError("Choose the selected Gmail outreach account")
        task = None
        if task_id is not None:
            task = session.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
            if task is None:
                raise ValueError("Choose an owned task")
        if opportunity_id is not None:
            opportunity = session.scalar(
                select(Opportunity).where(
                    Opportunity.id == opportunity_id,
                    Opportunity.owner_id == owner_id,
                    Opportunity.archived_at.is_(None),
                )
            )
            if opportunity is None:
                raise ValueError("Choose an active owned opportunity")
            if task is not None and task.opportunity_id not in {None, opportunity_id}:
                raise ValueError("Task and opportunity scopes do not match")
        if kind in {"calendar_update", "linear_update", "notion_update"}:
            if not expected_remote_revision:
                raise ValueError("Updates require an observed remote revision")
        elif expected_remote_revision is not None:
            raise ValueError("Create actions cannot target an existing remote revision")
        if kind.startswith("notion_"):
            if source_version_id is None:
                raise ValueError("Notion publication requires an exact document version")
            ReviewedAction._owned_text_version(session, owner_id, source_version_id)
        elif source_version_id is not None:
            raise ValueError("This action does not use a source document")
        if kind != "gmail_send" and attachment_version_ids:
            raise ValueError("Only Gmail send supports attachments")
        if (
            len(set(attachment_version_ids)) != len(attachment_version_ids)
            or len(attachment_version_ids) > 10
        ):
            raise ValueError("Use at most ten unique attachments")
        for version_id in attachment_version_ids:
            version = ReviewedAction._owned_version(session, owner_id, version_id)
            if version.blob_id is None:
                raise ValueError("Email attachments require exact stored bytes")
        if source_run_id is not None:
            from command_center.db.agents import AgentRun

            run = session.scalar(
                select(AgentRun).where(
                    AgentRun.id == source_run_id,
                    AgentRun.owner_id == owner_id,
                )
            )
            if run is None:
                raise ValueError("Choose an owned source run")
            if not reason.strip():
                raise ValueError("Agent proposals require a reason")
        if expires_at is not None and expires_at <= utc_now():
            raise ValueError("Action expiry must be in the future")
        if not reason.strip() or len(reason) > 2000:
            raise ValueError("Proposal reason must contain 1 to 2000 characters")
        return account

    @staticmethod
    def _owned_version(session: Session, owner_id: UUID, version_id: UUID) -> ArtifactVersion:
        version = session.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ArtifactVersion.id == version_id,
                Artifact.owner_id == owner_id,
                Artifact.archived_at.is_(None),
            )
        )
        if version is None:
            raise ValueError("Choose an owned active artifact version")
        return version

    @staticmethod
    def _owned_text_version(session: Session, owner_id: UUID, version_id: UUID) -> ArtifactVersion:
        version = ReviewedAction._owned_version(session, owner_id, version_id)
        if (
            version.schema_key not in {"text.v1", "docling.document.v1"}
            or version.payload is None
            or not isinstance(version.payload.get("text"), str)
        ):
            raise ValueError("Choose a textual document version")
        return version

    @staticmethod
    def _add_attachments(
        session: Session,
        revision: "ReviewedActionRevision",
        owner_id: UUID,
        version_ids: list[UUID],
    ) -> None:
        for position, version_id in enumerate(version_ids):
            version = ReviewedAction._owned_version(session, owner_id, version_id)
            session.add(
                ReviewedActionAttachment(
                    revision_id=revision.id,
                    position=position,
                    artifact_version_id=version.id,
                    content_sha256=version.content_sha256,
                    media_type=version.media_type,
                )
            )


class ReviewedActionRevision(Base):
    __tablename__ = "reviewed_action_revisions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash"),
        CheckConstraint("length(reason) BETWEEN 1 AND 2000", name="reason_length"),
        UniqueConstraint("action_id", "version"),
        UniqueConstraint("id", "action_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    action_id: Mapped[UUID] = mapped_column(ForeignKey("reviewed_actions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    tool_slug: Mapped[str] = mapped_column(String(100))
    toolkit_version: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    source_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifact_versions.id"), index=True
    )
    expected_remote_revision: Mapped[str | None] = mapped_column(String(500))
    observed_target: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    proposed_by_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    def parsed_payload(self) -> ActionPayload:
        return ACTION_PAYLOAD.validate_python(self.payload)

    def review_state(self, session: Session | None = None) -> ReviewState:
        current_session = session or object_session(self)
        if current_session is None:
            raise ValueError("Read review state from a persisted revision")
        decision = current_session.scalar(
            select(ReviewedActionReview.decision)
            .where(ReviewedActionReview.revision_id == self.id)
            .order_by(ReviewedActionReview.created_at.desc(), ReviewedActionReview.id.desc())
            .limit(1)
        )
        return decision if decision in {"approved", "rejected", "revoked"} else "proposed"


class ReviewedActionAttachment(Base):
    __tablename__ = "reviewed_action_attachments"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        UniqueConstraint("revision_id", "position"),
        UniqueConstraint(
            "revision_id",
            "artifact_version_id",
            name="uq_reviewed_action_attachments_revision_artifact",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("reviewed_action_revisions.id"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    artifact_version_id: Mapped[UUID] = mapped_column(ForeignKey("artifact_versions.id"))
    content_sha256: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(200))


class ReviewedActionReview(Base):
    __tablename__ = "reviewed_action_reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('approved','rejected','revoked')", name="decision"),
        CheckConstraint("length(reason) BETWEEN 1 AND 2000", name="reason_length"),
        ForeignKeyConstraint(
            ["revision_id", "action_id"],
            ["reviewed_action_revisions.id", "reviewed_action_revisions.action_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    action_id: Mapped[UUID] = mapped_column(ForeignKey("reviewed_actions.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    decision: Mapped[ReviewDecision] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class ActionAttempt(Base):
    __tablename__ = "reviewed_action_attempts"
    __table_args__ = (
        CheckConstraint(
            "state IN ('running','succeeded','failed','outcome_unknown','partial','conflicted')",
            name="state",
        ),
        CheckConstraint("attempt_number >= 1", name="attempt_number"),
        CheckConstraint(
            "(state = 'running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="lease_state",
        ),
        UniqueConstraint("revision_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    action_id: Mapped[UUID] = mapped_column(ForeignKey("reviewed_actions.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("reviewed_action_revisions.id"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30), index=True)
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    provider_log_id: Mapped[str | None] = mapped_column(String(300))
    provider_external_id: Mapped[str | None] = mapped_column(String(500))
    provider_url: Mapped[str | None] = mapped_column(Text)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    observed_before_revision: Mapped[str | None] = mapped_column(String(500))
    observed_after_revision: Mapped[str | None] = mapped_column(String(500))
    error_code: Mapped[str | None] = mapped_column(String(100))
    reconciliation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    def accepts(self, lease_id: UUID) -> bool:
        return bool(
            self.state == "running"
            and self.lease_id == lease_id
            and self.lease_expires_at
            and self.lease_expires_at > utc_now()
        )

    def renew(self, lease_id: UUID) -> None:
        if not self.accepts(lease_id):
            raise RecordConflict("Reviewed action lease was lost")
        self.lease_expires_at = utc_now() + timedelta(minutes=5)

    def finish(
        self,
        state: Literal["succeeded", "failed", "partial", "conflicted"],
        *,
        provider_log_id: str | None = None,
        provider_external_id: str | None = None,
        provider_url: str | None = None,
        receipt: dict[str, Any] | None = None,
        before_revision: str | None = None,
        after_revision: str | None = None,
        error_code: str | None = None,
    ) -> None:
        if self.state != "running":
            raise RecordConflict("Only a running action attempt can finish")
        self.state = state
        self.provider_log_id = provider_log_id
        self.provider_external_id = provider_external_id
        self.provider_url = provider_url
        self.receipt = receipt
        self.observed_before_revision = before_revision
        self.observed_after_revision = after_revision
        self.error_code = error_code
        self.lease_id = None
        self.lease_expires_at = None
        self.completed_at = utc_now()

    def finish_unknown(self, reason: str) -> None:
        if self.state != "running":
            raise RecordConflict("Only a running action attempt can become unknown")
        self.state = "outcome_unknown"
        self.error_code = reason[:100]
        self.lease_id = None
        self.lease_expires_at = None
        self.completed_at = utc_now()


class ProviderObservation(Base):
    __tablename__ = "provider_observations"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('gmail_search','calendar_events','calendar_event','linear_issue',"
            "'notion_page')",
            name="kind",
        ),
        CheckConstraint("length(request_hash) = 64", name="request_hash"),
        Index("ix_provider_observations_owner_kind", "owner_id", "kind", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("external_accounts.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    request_hash: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    external_revision: Mapped[str | None] = mapped_column(String(500))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @classmethod
    def capture(
        cls,
        *,
        record_id: UUID | None = None,
        owner_id: UUID,
        account_id: UUID,
        task_id: UUID | None,
        opportunity_id: UUID | None,
        kind: str,
        request: dict[str, Any],
        result: dict[str, Any],
        external_revision: str | None = None,
    ) -> "ProviderObservation":
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        return cls(
            id=record_id or uuid4(),
            owner_id=owner_id,
            account_id=account_id,
            task_id=task_id,
            opportunity_id=opportunity_id,
            kind=kind,
            request_hash=hashlib.sha256(encoded).hexdigest(),
            request=request,
            result=result,
            external_revision=external_revision,
        )

    @classmethod
    def capture_context(
        cls,
        session: Session,
        *,
        request_id: UUID,
        record_id: UUID,
        owner_id: UUID,
        account_id: UUID,
        task_id: UUID | None,
        opportunity_id: UUID | None,
        kind: ConnectedContextKind,
        request: dict[str, Any],
        result: dict[str, Any],
        external_revision: str,
    ) -> "ProviderObservation":
        observation = cls.capture(
            record_id=record_id,
            owner_id=owner_id,
            account_id=account_id,
            task_id=task_id,
            opportunity_id=opportunity_id,
            kind=kind,
            request=request,
            result=result,
            external_revision=external_revision,
        )
        session.add(observation)
        session.flush()
        record_event(
            session,
            owner_id,
            request_id,
            "connected_context.observed",
            cls.__tablename__,
            observation.id,
            account_id=str(account_id),
            kind=kind,
        )
        return observation


class ConnectedRequest(Base):
    """Durable no-replay claim spanning provider I/O and a later finalize transaction."""

    __tablename__ = "connected_requests"
    __table_args__ = (
        CheckConstraint(
            "state IN ('running','completed','failed','outcome_unknown')", name="state"
        ),
        CheckConstraint("length(request_hash) = 64", name="request_hash"),
        UniqueConstraint("actor_id", "key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    key: Mapped[UUID] = mapped_column(Uuid)
    operation: Mapped[str] = mapped_column(String(300))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(30), default="running", index=True)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    def complete(self, response: dict[str, Any]) -> None:
        if self.state != "running":
            raise RecordConflict("Connected request is no longer running")
        self.state = "completed"
        self.response = response
        self.completed_at = utc_now()

    def fail(self, code: str, *, unknown: bool) -> None:
        if self.state != "running":
            return
        self.state = "outcome_unknown" if unknown else "failed"
        self.error_code = code[:100]
        self.completed_at = utc_now()
