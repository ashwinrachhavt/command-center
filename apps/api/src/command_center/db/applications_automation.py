"""Application intake and automation attempts, separate from application_tracks."""

import csv
import hashlib
import io
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.crm import record_event
from command_center.db.errors import RecordConflict
from command_center.db.models import AuditEvent

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 200
RUN_TOKEN_MINUTES = 10
FORMULA_TRIGGERS = ("=", "+", "-", "@")


def normalize_cell(value: str) -> str:
    """Trim one CSV cell and neutralize spreadsheet formula triggers."""
    clean = value.strip()
    if clean.startswith(FORMULA_TRIGGERS):
        return "'" + clean
    return clean


class ApplicationImport(Base):
    """One CSV batch of application rows, parsed synchronously at upload."""

    __tablename__ = "application_imports"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_application_imports_id_owner"),
        CheckConstraint("state IN ('queued', 'running', 'parse_error', 'completed')", name="state"),
        CheckConstraint(f"byte_size BETWEEN 1 AND {MAX_IMPORT_BYTES}", name="byte_size"),
        CheckConstraint("row_version >= 1", name="row_version"),
        CheckConstraint("(state = 'parse_error') = (error IS NOT NULL)", name="error_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    reject_reasons: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def parse_rows(cls, text: str) -> tuple[list[dict[str, str]], dict[int, str]]:
        """Parse one CSV upload into candidate rows and per-row rejection reasons.

        The header requires company, job_title and job_url columns. Rows missing a
        required value, exceeding field limits, or carrying a formula-trigger cell
        that cannot be safely neutralized are rejected with a reason instead of
        silently normalized.
        """
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("The CSV requires a header row")
        header_map = {name.strip().lower(): name.strip() for name in reader.fieldnames}
        missing = {"company", "job_title", "job_url"} - header_map.keys()
        if missing:
            raise ValueError(f"The CSV requires columns: {', '.join(sorted(missing))}")

        candidates: list[dict[str, str]] = []
        rejections: dict[int, str] = {}
        for position, raw in enumerate(reader, start=1):
            if position > MAX_IMPORT_ROWS:
                raise ValueError(f"The CSV accepts at most {MAX_IMPORT_ROWS} rows")
            company = normalize_cell(raw.get("company") or "")
            job_title = normalize_cell(raw.get("job_title") or "")
            job_url = normalize_cell(raw.get("job_url") or "")
            job_location = normalize_cell(raw.get("job_location") or "")
            if not company or not job_title or not job_url:
                rejections[position] = "missing company, job_title or job_url"
                continue
            if any(len(field) > 2048 for field in (company, job_title, job_url, job_location)):
                rejections[position] = "a field exceeds 2048 characters"
                continue
            if not job_url.startswith(("http://", "https://")):
                rejections[position] = "job_url must be an http(s) URL"
                continue
            candidates.append(
                {
                    "company": company,
                    "job_title": job_title,
                    "job_url": job_url,
                    "job_location": job_location,
                }
            )
        return candidates, rejections

    @classmethod
    def create_from_upload(
        cls,
        session: Session,
        *,
        import_id: UUID,
        owner_id: UUID,
        filename: str,
        text: str,
        request_id: UUID,
    ) -> "ApplicationImport":
        """Parse the CSV and create one normalized Application row per accepted row."""
        from command_center.db.applications_automation import Application

        batch = cls(
            id=import_id,
            owner_id=owner_id,
            filename=filename.strip()[:255] or "applications.csv",
            byte_size=len(text.encode()),
            state="queued",
        )
        if not 0 < batch.byte_size <= MAX_IMPORT_BYTES:
            raise ValueError("CSV uploads accept between 1 byte and 5 MiB")
        candidates, rejections = cls.parse_rows(text)

        record_event(
            session,
            owner_id,
            request_id,
            "application.import_queued",
            "application_imports",
            import_id,
            filename=batch.filename,
            rows=len(candidates) + len(rejections),
        )
        session.add(batch)
        session.flush([batch])
        for position, candidate in enumerate(candidates, start=1):
            session.add(
                Application.create_from_row(
                    session,
                    import_id=import_id,
                    owner_id=owner_id,
                    source_row=position,
                    row=candidate,
                    request_id=request_id,
                )
            )
        rejected = len(rejections)
        batch.state = "completed"
        batch.row_count = len(candidates) + rejected
        batch.accepted_count = len(candidates)
        batch.rejected_count = rejected
        batch.reject_reasons = {str(row): reason for row, reason in rejections.items()}
        session.flush()
        return batch


class Application(Base):
    """One normalized job application row from a CSV import."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_applications_id_owner"),
        ForeignKeyConstraint(
            ["import_id", "owner_id"],
            ["application_imports.id", "application_imports.owner_id"],
            name="fk_applications_import_id_owner",
        ),
        ForeignKeyConstraint(
            ["job_id", "owner_id"],
            ["jobs.id", "jobs.owner_id"],
            name="fk_applications_job_id_owner",
        ),
        ForeignKeyConstraint(
            ["submit_authorized_by"],
            ["actors.id"],
            name="fk_applications_submit_authorized_by",
        ),
        CheckConstraint(
            "status IN ('intake', 'ready_to_run', 'running', 'ready_for_review', "
            "'skipped', 'failed', 'submitted')",
            name="status",
        ),
        CheckConstraint("source_row >= 1", name="source_row"),
        CheckConstraint(
            "(submit_authorized_at IS NULL) = (submit_authorized_by IS NULL)",
            name="authorization_state",
        ),
        CheckConstraint("row_version >= 1", name="row_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    import_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    source_row: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    company: Mapped[str] = mapped_column(String(2048))
    job_title: Mapped[str] = mapped_column(String(2048))
    job_url: Mapped[str] = mapped_column(Text)
    job_location: Mapped[str | None] = mapped_column(String(2048))
    job_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(20), default="ready_to_run", index=True)
    submit_authorized_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    submit_authorized_by: Mapped[UUID | None] = mapped_column(Uuid)
    adapter_platform: Mapped[str | None] = mapped_column(String(20))
    last_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    profile_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def create_from_row(
        cls,
        session: Session,
        *,
        import_id: UUID,
        owner_id: UUID,
        source_row: int,
        row: dict[str, str],
        request_id: UUID,
    ) -> "Application":
        """Create one normalized row and link a matching saved job when recognized."""
        from command_center.db.crm import Job
        from command_center.db.job_identity import posting_identity

        identity = posting_identity(row["job_url"])
        job = None
        if identity is not None:
            job = session.scalar(
                select(Job).where(
                    Job.owner_id == owner_id,
                    Job.source_url == row["job_url"],
                    Job.archived_at.is_(None),
                )
            )
        application = cls(
            id=uuid5(import_id, f"application:{source_row}"),
            owner_id=owner_id,
            import_id=import_id,
            source_row=source_row,
            source_hash=hashlib.sha256(
                "\x1f".join(row[key] for key in sorted(row)).encode()
            ).hexdigest(),
            company=row["company"],
            job_title=row["job_title"],
            job_url=row["job_url"],
            job_location=row.get("job_location") or None,
            job_id=job.id if job is not None else None,
            adapter_platform=identity["platform"] if identity is not None else None,
            status="ready_to_run",
        )
        session.add(application)
        record_event(
            session,
            owner_id,
            request_id,
            "applications.created",
            "applications",
            application.id,
            import_id=str(import_id),
            source_row=source_row,
            adapter_platform=application.adapter_platform,
        )
        return application

    def authorize(self, *, request_id: UUID) -> None:
        """Stamp explicit submission authorization. The only writer of the flag."""
        if self.submit_authorized_at is not None:
            return
        session = object_session(self)
        if session is None:
            raise ValueError("Application must belong to a transaction")
        self.submit_authorized_at = utc_now()
        self.submit_authorized_by = self.owner_id
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "application.submit_authorized",
            "applications",
            self.id,
            status=self.status,
        )

    def revoke_authorization(self, *, request_id: UUID) -> None:
        """Clear an unused authorization; a submitted application is final."""
        if self.status == "submitted":
            raise RecordConflict("A submitted application cannot revoke its authorization")
        if self.submit_authorized_at is None:
            return
        session = object_session(self)
        if session is None:
            raise ValueError("Application must belong to a transaction")
        self.submit_authorized_at = None
        self.submit_authorized_by = None
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "application.submit_revoked",
            "applications",
            self.id,
            status=self.status,
        )

    def record_run(self, run: "AutomationRun", *, request_id: UUID) -> None:
        """Mirror one automation run's terminal state onto this application."""
        session = object_session(self)
        if session is None:
            raise ValueError("Application must belong to a transaction")
        self.last_run_id = run.id
        if run.state == "running":
            self.status = "running"
        elif run.state in {"completed", "failed", "outcome_unknown", "cancelled"}:
            authorized = self.submit_authorized_at is not None
            if run.state == "completed" and run.mode == "submit" and authorized:
                self.status = "submitted"
            elif run.state == "completed":
                self.status = "ready_for_review"
            else:
                self.status = "failed"
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "application.status_recorded",
            "applications",
            self.id,
            status=self.status,
            run_state=run.state,
            run_mode=run.mode,
            source="automation",
        )


class AutomationRun(Base):
    """One browser automation attempt against one application, fenced by run token."""

    __tablename__ = "automation_runs"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_automation_runs_id_owner"),
        ForeignKeyConstraint(
            ["application_id", "owner_id"],
            ["applications.id", "applications.owner_id"],
            name="fk_automation_runs_application_id_owner",
        ),
        ForeignKeyConstraint(
            ["device_id"], ["browser_devices.id"], name="fk_automation_runs_device_id"
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'outcome_unknown', 'cancelled')",
            name="state",
        ),
        CheckConstraint("attempt >= 1", name="attempt"),
        CheckConstraint("mode IN ('fill_only', 'submit')", name="mode"),
        CheckConstraint(
            "(state = 'running') = (run_token IS NOT NULL AND run_token_expires_at IS NOT NULL)",
            name="token_state",
        ),
        CheckConstraint("mode = 'fill_only' OR attempt > 0", name="submission_mode"),
        CheckConstraint("row_version >= 1", name="row_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    application_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    device_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    adapter_platform: Mapped[str] = mapped_column(String(20))
    adapter_revision: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(20), default="fill_only")
    run_token: Mapped[UUID | None] = mapped_column(Uuid)
    run_token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    field_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    page_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    simplify_step: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def enqueue(
        cls,
        session: Session,
        *,
        application: Application,
        mode: str,
        adapter_platform: str,
        adapter_revision: str,
        request_id: UUID,
    ) -> "AutomationRun":
        """Queue one run; submission mode requires an explicit authorization stamp."""
        if mode not in {"fill_only", "submit"}:
            raise ValueError("Run mode must be fill_only or submit")
        if mode == "submit" and application.submit_authorized_at is None:
            raise RecordConflict("Submission requires explicit authorization")
        attempt = 1
        previous = session.scalar(
            select(cls)
            .where(cls.application_id == application.id, cls.owner_id == application.owner_id)
            .order_by(cls.attempt.desc())
            .limit(1)
        )
        if previous is not None:
            attempt = previous.attempt + 1
        run = cls(
            id=uuid4(),
            owner_id=application.owner_id,
            application_id=application.id,
            attempt=attempt,
            adapter_platform=adapter_platform,
            adapter_revision=adapter_revision,
            mode=mode,
            state="queued",
        )
        session.add(run)
        record_event(
            session,
            application.owner_id,
            request_id,
            "automation.run_queued",
            "automation_runs",
            run.id,
            application_id=str(application.id),
            mode=mode,
            attempt=attempt,
        )
        return run

    @classmethod
    def claim(
        cls, session: Session, *, device_id: UUID, owner_id: UUID | None = None
    ) -> "AutomationRun | None":
        """Claim the oldest queued run for one device. Expired runs are recycled.

        A targeted owner scope must not sweep or lock another workspace's runs.
        """
        cls.expire_stale(session)
        conditions = [cls.state == "queued"]
        if owner_id is not None:
            conditions.append(cls.owner_id == owner_id)
        run = session.scalar(
            select(cls)
            .where(*conditions, cls.device_id.is_(None) | (cls.device_id == device_id))
            .order_by(cls.created_at, cls.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        run.state = "running"
        run.device_id = device_id
        run.run_token = uuid4()
        run.run_token_expires_at = utc_now() + timedelta(minutes=RUN_TOKEN_MINUTES)
        run.error = None
        run.started_at = utc_now()
        application = session.get(Application, run.application_id)
        if application is not None:
            application.record_run(run, request_id=run.id)
        record_event(
            session,
            run.owner_id,
            run.id,
            "automation.run_claimed",
            "automation_runs",
            run.id,
            device_id=str(device_id),
            attempt=run.attempt,
        )
        return run

    def accepts(self, run_token: UUID | None) -> bool:
        return bool(
            run_token
            and self.state == "running"
            and self.run_token == run_token
            and self.run_token_expires_at is not None
            and self.run_token_expires_at > utc_now()
        )

    def renew(self, run_token: UUID) -> None:
        if not self.accepts(run_token):
            raise ValueError("Automation run token was lost")
        self.run_token_expires_at = utc_now() + timedelta(minutes=RUN_TOKEN_MINUTES)

    def report(
        self,
        run_token: UUID,
        *,
        field_evidence: dict[str, Any],
        page_evidence: dict[str, Any] | None = None,
        simplify_step: dict[str, Any] | None = None,
    ) -> None:
        """Persist mid-run evidence; the whole payload replaces prior evidence."""
        if not self.accepts(run_token):
            raise ValueError("Automation run token was lost")
        self.field_evidence = field_evidence
        if page_evidence is not None:
            self.page_evidence = page_evidence
        if simplify_step is not None:
            self.simplify_step = simplify_step
        self.updated_at = utc_now()

    def _finish(self, state: str, run_token: UUID, *, error: str | None, request_id: UUID) -> None:
        if not self.accepts(run_token):
            raise RecordConflict("Automation run token was lost")
        session = object_session(self)
        if session is None:
            raise ValueError("Automation run must belong to a transaction")
        self.state = state
        self.error = error[:1000] if error else None
        self.run_token = None
        self.run_token_expires_at = None
        self.finished_at = utc_now()
        self.updated_at = utc_now()
        application = session.get(Application, self.application_id)
        if application is not None:
            application.record_run(self, request_id=request_id)
        record_event(
            session,
            self.owner_id,
            request_id,
            f"automation.run_{state}",
            "automation_runs",
            self.id,
            application_id=str(self.application_id),
            mode=self.mode,
            error=self.error,
        )

    def complete(
        self,
        run_token: UUID,
        *,
        field_evidence: dict[str, Any],
        page_evidence: dict[str, Any] | None = None,
        simplify_step: dict[str, Any] | None = None,
        request_id: UUID,
    ) -> None:
        if not self.accepts(run_token):
            raise RecordConflict("Automation run token was lost")
        self.field_evidence = field_evidence
        if page_evidence is not None:
            self.page_evidence = page_evidence
        if simplify_step is not None:
            self.simplify_step = simplify_step
        self._finish("completed", run_token, error=None, request_id=request_id)

    def fail(
        self,
        run_token: UUID,
        *,
        error: str,
        field_evidence: dict[str, Any] | None = None,
        request_id: UUID,
    ) -> None:
        if field_evidence is not None:
            self.field_evidence = field_evidence
        self._finish("failed", run_token, error=error, request_id=request_id)

    def mark_outcome_unknown(
        self,
        run_token: UUID,
        *,
        detail: str,
        field_evidence: dict[str, Any] | None = None,
        request_id: UUID,
    ) -> None:
        """A mid-navigation crash never counts as success or triggers blind retries."""
        if field_evidence is not None:
            self.field_evidence = field_evidence
        self._finish("outcome_unknown", run_token, error=detail, request_id=request_id)

    def cancel(self, *, request_id: UUID) -> None:
        if self.state != "queued":
            raise RecordConflict("Only queued automation runs can be cancelled")
        session = object_session(self)
        if session is None:
            raise ValueError("Automation run must belong to a transaction")
        self.state = "cancelled"
        self.finished_at = utc_now()
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "automation.run_cancelled",
            "automation_runs",
            self.id,
        )

    @classmethod
    def expire_stale(cls, session: Session) -> int:
        """Fail running runs with expired tokens so the next claim recycles them."""
        rows = list(
            session.scalars(
                select(cls)
                .where(
                    cls.state == "running",
                    cls.run_token_expires_at.is_not(None),
                    cls.run_token_expires_at <= utc_now(),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for run in rows:
            session.add(
                AuditEvent(
                    actor_id=run.owner_id,
                    request_id=uuid4(),
                    action="automation.run_failed",
                    subject_type="automation_runs",
                    subject_id=run.id,
                    details={"error": "run_token_expired"},
                )
            )
            run.state = "failed"
            run.error = "run_token_expired"
            run.run_token = None
            run.run_token_expires_at = None
            run.finished_at = utc_now()
            run.updated_at = utc_now()
            application = session.get(Application, run.application_id)
            if application is not None:
                application.record_run(run, request_id=uuid4())
        return len(rows)
