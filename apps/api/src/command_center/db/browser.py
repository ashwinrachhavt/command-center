"""Revocable browser devices and exact, site-bound application assistance."""

import hashlib
import importlib
import math
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
from pathlib import PurePath
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Select,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.artifacts import Artifact, ArtifactVersion, Blob, Document, DocumentType
from command_center.db.base import Base, UTCDateTime, utc_now
from command_center.db.career import date_interval
from command_center.db.crm import CandidateProfile, record_event
from command_center.db.document_imports import DocumentImport
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor
from command_center.db.pdf_exports import PdfExport

NUMBER_DECIMAL_WORK_LIMIT = 10_000
HTML_NUMBER_PATTERN = r"^-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"


def parse_browser_decimal(value: str) -> Decimal:
    """Parse the finite number grammar and range used by native HTML inputs."""
    if len(value) > 100 or re.fullmatch(HTML_NUMBER_PATTERN, value) is None:
        raise ValueError("Enter a finite number for this field")
    try:
        number = Decimal(value)
        browser_number = float(value)
    except (DecimalException, OverflowError, ValueError) as exc:
        raise ValueError("Enter a finite number for this field") from exc
    if not number.is_finite() or not math.isfinite(browser_number):
        raise ValueError("Enter a finite number for this field")
    return number


def validate_numeric_answer(field: dict[str, Any], value: str) -> None:
    """Validate an HTML number answer with exact decimal bounds and stepping."""
    constraints = field.get("numeric_constraints")
    if not isinstance(constraints, dict):
        raise ValueError("Reshare this number field with its numeric constraints")
    number = parse_browser_decimal(value)
    try:
        minimum = (
            parse_browser_decimal(constraints["minimum"])
            if constraints.get("minimum") is not None
            else None
        )
        maximum = (
            parse_browser_decimal(constraints["maximum"])
            if constraints.get("maximum") is not None
            else None
        )
        step_base = parse_browser_decimal(constraints["step_base"])
        step_value = constraints["step"]
        step = None if step_value == "any" else parse_browser_decimal(step_value)
    except (DecimalException, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Reshare this number field with valid numeric constraints") from exc
    decimals = [item for item in (number, minimum, maximum, step_base, step) if item is not None]
    if not all(item.is_finite() for item in decimals):
        raise ValueError("Enter a finite number for this field")
    if minimum is not None and number < minimum:
        raise ValueError("Number is below the minimum for this field")
    if maximum is not None and number > maximum:
        raise ValueError("Number is above the maximum for this field")
    if step is not None:
        if step <= 0:
            raise ValueError("Reshare this number field with valid numeric constraints")
        try:
            exponents: list[int] = []
            for item in decimals:
                exponent = item.as_tuple().exponent
                if not isinstance(exponent, int):
                    raise ValueError("Enter a number compatible with this field")
                exponents.append(exponent)
            adjusted = [item.adjusted() for item in decimals if item]
            precision = max(adjusted, default=0) - min(exponents, default=0) + 2
            positions = (*exponents, *adjusted)
            if precision > NUMBER_DECIMAL_WORK_LIMIT or any(
                abs(position) > NUMBER_DECIMAL_WORK_LIMIT for position in positions
            ):
                raise ValueError("Enter a number compatible with this field")
            with localcontext() as context:
                context.prec = max(28, precision)
                if (number - step_base) % step != 0:
                    raise ValueError("Number does not match the step for this field")
        except DecimalException as exc:
            raise ValueError("Enter a number compatible with this field") from exc


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def calendar_number(value: str, kind: str) -> int:
    if len(value) != (7 if kind == "month" else 10):
        raise ValueError("Enter a complete calendar value for this control")
    first, _ = date_interval(value)
    return first.year * 12 + first.month - 1 if kind == "month" else first.toordinal()


def temporal_numbers(kind: str, constraints: dict[str, Any]) -> dict[str, Any]:
    converted = {
        key: str(calendar_number(constraints[key], kind))
        if constraints.get(key) is not None
        else None
        for key in ("minimum", "maximum", "step_base")
    }
    if converted["step_base"] is None:
        raise ValueError("Calendar controls require their step base")
    minimum, maximum = converted["minimum"], converted["maximum"]
    if minimum and maximum and int(minimum) > int(maximum):
        raise ValueError("Calendar minimum cannot exceed maximum")
    step = constraints["step"]
    if step != "any" and parse_browser_decimal(step) <= 0:
        raise ValueError("Calendar step must be positive")
    return converted | {"step": step}


def validate_temporal_answer(field: dict[str, Any], value: str) -> None:
    constraints = field.get("temporal_constraints")
    if not isinstance(constraints, dict):
        raise ValueError("Reshare this calendar control with its constraints")
    validate_numeric_answer(
        {"numeric_constraints": temporal_numbers(field["type"], constraints)},
        str(calendar_number(value, field["type"])),
    )


def application_file_query(owner_id: UUID, kind: Literal["resume", "cover-letter"]) -> Select[Any]:
    """Only imported originals or completed owned PDF exports are attachable files."""
    return (
        select(ArtifactVersion, Artifact, Blob, DocumentImport.filename)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .join(Blob, Blob.id == ArtifactVersion.blob_id)
        .join(Document, Document.artifact_id == Artifact.id)
        .join(DocumentType, DocumentType.id == Document.document_type_id)
        .outerjoin(
            DocumentImport,
            and_(
                DocumentImport.source_version_id == ArtifactVersion.id,
                DocumentImport.owner_id == owner_id,
            ),
        )
        .outerjoin(
            PdfExport,
            and_(
                PdfExport.output_version_id == ArtifactVersion.id,
                PdfExport.owner_id == owner_id,
                PdfExport.state == "completed",
            ),
        )
        .join(Actor, Actor.id == Artifact.owner_id)
        .where(
            Artifact.owner_id == owner_id,
            Artifact.archived_at.is_(None),
            DocumentType.slug == kind,
            Actor.active.is_(True),
            or_(DocumentImport.id.is_not(None), PdfExport.id.is_not(None)),
        )
    )


def application_filename(artifact: Artifact, imported_name: str | None) -> str:
    if imported_name:
        return imported_name
    name = re.sub(r"[^a-zA-Z0-9 .()-]", "_", artifact.title).strip()[:180]
    return (name or "application-document") + ".pdf"


def application_file(
    session: Session,
    owner_id: UUID,
    version_id: UUID,
    *,
    kind: Literal["resume", "cover-letter"],
) -> dict[str, object]:
    row = session.execute(
        application_file_query(owner_id, kind).where(ArtifactVersion.id == version_id)
    ).first()
    if row is None:
        raise RecordConflict(f"Choose an active uploaded or exported {kind} version")
    version, artifact, blob, filename = row
    return {
        "version_id": str(version.id),
        "filename": application_filename(artifact, filename),
        "media_type": version.media_type,
        "size_bytes": blob.byte_size,
        "sha256": blob.sha256,
    }


def resume_file(session: Session, owner_id: UUID, version_id: UUID) -> dict[str, object]:
    return application_file(session, owner_id, version_id, kind="resume")


def application_file_options(
    session: Session,
    owner_id: UUID,
    *,
    kind: Literal["resume", "cover-letter"],
) -> dict[str, object]:
    rows = session.execute(
        application_file_query(owner_id, kind)
        .order_by(ArtifactVersion.created_at.desc(), ArtifactVersion.id)
        .limit(100)
    ).all()
    items = [
        {
            "version_id": version.id,
            "artifact_id": artifact.id,
            "title": artifact.title,
            "version": version.version,
            "filename": application_filename(artifact, filename),
            "media_type": version.media_type,
            "size_bytes": blob.byte_size,
            "sha256": blob.sha256,
        }
        for version, artifact, blob, filename in rows
    ]
    profile = session.get(CandidateProfile, owner_id) if kind == "resume" else None
    available = {item["version_id"] for item in items}
    selected = profile.default_resume_version_id if profile else None
    return {
        "default_version_id": selected if selected in available else None,
        "items": items,
    }


def resume_options(session: Session, owner_id: UUID) -> dict[str, object]:
    return application_file_options(session, owner_id, kind="resume")


def preparation_payload(session: Session, owner_id: UUID, version_id: UUID) -> dict[str, Any]:
    module = importlib.import_module("command_center.db.application_preparations")
    validator = module.validate_preparation_for_fill
    return dict(validator(session, owner_id, version_id))


def validate_preparation_command(
    payload: dict[str, Any],
    *,
    snapshot_id: UUID,
    fields: dict[str, str],
    uploads: dict[str, UUID],
    replace_fields: list[str],
) -> None:
    prepared_fields = payload.get("fields")
    if not isinstance(prepared_fields, list):
        raise RecordConflict("Reviewed application answers are unavailable")
    prepared_values = {
        row.get("field_id"): row.get("value")
        for row in prepared_fields
        if isinstance(row, dict) and isinstance(row.get("field_id"), str)
    }
    selected_uploads = preparation_uploads(payload)
    try:
        prepared_snapshot_id = UUID(str(payload.get("snapshot_id")))
    except (TypeError, ValueError, AttributeError):
        raise RecordConflict("Reviewed application snapshot is unavailable") from None
    if prepared_snapshot_id != snapshot_id:
        raise RecordConflict("Reviewed answers belong to a different form snapshot")
    if any(prepared_values.get(field_id) != value for field_id, value in fields.items()):
        raise RecordConflict("Fill values must match the reviewed application answers")
    if set(replace_fields) != set(payload.get("replace_fields", [])):
        raise RecordConflict("Replacement choices must match the reviewed application answers")
    if any(
        selected_uploads.get(field_id) != str(version_id)
        for field_id, version_id in uploads.items()
    ):
        raise RecordConflict("Uploads must use the reviewed document version for each field")
    if set(selected_uploads) & set(fields):
        raise RecordConflict("Reviewed file fields require the selected document")


def preparation_uploads(payload: dict[str, Any]) -> dict[str, str]:
    """Resolve the exact file-to-control choices in an immutable application package."""
    selected: dict[str, str] = {}
    for prefix, field_key in (
        ("resume", "upload_fields"),
        ("cover_letter", "cover_letter_upload_fields"),
    ):
        field_ids = payload.get(field_key, [])
        version_id = payload.get(f"{prefix}_version_id")
        if not isinstance(field_ids, list) or any(not isinstance(item, str) for item in field_ids):
            raise RecordConflict("Reviewed application upload fields are unavailable")
        if field_ids and not version_id:
            raise RecordConflict("Reviewed application document is unavailable")
        for field_id in field_ids:
            if field_id in selected:
                raise RecordConflict("Only one reviewed document can be attached to each field")
            selected[field_id] = str(version_id)
    if len(selected) > 10:
        raise RecordConflict("Select at most ten file controls")
    return selected


def file_accepts(filename: str, media_type: str, accepted: str) -> bool:
    if not accepted.strip():
        return True
    suffix = PurePath(filename).suffix.casefold()
    media = media_type.casefold()
    for raw in accepted.split(","):
        token = raw.strip().casefold()
        if not token:
            continue
        if token.startswith(".") and token == suffix:
            return True
        if token.endswith("/*") and media.startswith(token[:-1]):
            return True
        if token == media:
            return True
    return False


class BrowserDevice(Base):
    __tablename__ = "browser_devices"
    __table_args__ = (UniqueConstraint("id", "owner_id"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    pairing_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    pairing_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    token_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    paired_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @classmethod
    def pair(
        cls, session: Session, *, device_id: UUID, owner_id: UUID, name: str, request_id: UUID
    ) -> tuple["BrowserDevice", str]:
        code = secrets.token_urlsafe(32)
        device = cls(
            id=device_id,
            owner_id=owner_id,
            name=name,
            pairing_digest=digest(code),
            pairing_expires_at=utc_now() + timedelta(minutes=5),
        )
        session.add(device)
        record_event(
            session, owner_id, request_id, "browser.pairing_created", "browser_devices", device_id
        )
        return device, code

    @classmethod
    def redeem(
        cls, session: Session, code: str, *, request_id: UUID
    ) -> tuple["BrowserDevice", str]:
        device = session.scalar(
            select(cls)
            .where(
                cls.pairing_digest == digest(code),
                cls.revoked_at.is_(None),
                cls.pairing_expires_at > utc_now(),
            )
            .with_for_update()
        )
        if device is None:
            raise ValueError("Pairing code is invalid, expired or already used")
        token = secrets.token_urlsafe(48)
        device.token_digest, device.pairing_digest, device.paired_at = (
            digest(token),
            None,
            utc_now(),
        )
        record_event(
            session, device.owner_id, request_id, "browser.paired", "browser_devices", device.id
        )
        return device, token

    def revoke(self, *, request_id: UUID) -> None:
        if self.revoked_at:
            return
        self.revoked_at, self.token_digest, self.pairing_digest = utc_now(), None, None
        session = object_session(self)
        if session:
            record_event(
                session, self.owner_id, request_id, "browser.revoked", "browser_devices", self.id
            )


class BrowserSnapshot(Base):
    __tablename__ = "browser_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "device_id", "owner_id"),
        UniqueConstraint("id", "owner_id", name="uq_browser_snapshots_id_owner"),
        ForeignKeyConstraint(
            ["device_id", "owner_id"], ["browser_devices.id", "browser_devices.owner_id"]
        ),
        CheckConstraint("protocol_version IN (1, 2)", name="protocol_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    protocol_version: Mapped[int] = mapped_column(Integer, default=2)
    origin: Mapped[str] = mapped_column(String(500))
    page_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300))
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @classmethod
    def capture(
        cls,
        session: Session,
        device: BrowserDevice,
        *,
        snapshot_id: UUID,
        protocol_version: int,
        page_url: str,
        title: str,
        fields: list[dict[str, Any]],
        request_id: UUID,
    ) -> "BrowserSnapshot":
        parsed = urlsplit(page_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Share only the page origin and path")
        if len({field["id"] for field in fields}) != len(fields):
            raise ValueError("Field IDs must be unique")
        existing = session.get(cls, snapshot_id)
        if existing:
            if (
                existing.device_id != device.id
                or existing.protocol_version != protocol_version
                or existing.fields != fields
                or existing.page_url != page_url
                or existing.title != title
            ):
                raise RecordConflict("Snapshot ID already exists")
            return existing
        snapshot = cls(
            id=snapshot_id,
            device_id=device.id,
            owner_id=device.owner_id,
            protocol_version=protocol_version,
            origin=f"{parsed.scheme}://{parsed.netloc}",
            page_url=page_url,
            title=title,
            fields=fields,
        )
        session.add(snapshot)
        record_event(
            session,
            device.owner_id,
            request_id,
            "browser.form_shared",
            "browser_snapshots",
            snapshot_id,
            field_count=len(fields),
            origin=snapshot.origin,
            protocol_version=protocol_version,
        )
        return snapshot

    def require_current(self) -> None:
        if self.protocol_version != 2:
            raise RecordConflict("Reshare this form with the current browser companion")

    def propose_fill(
        self,
        *,
        command_id: UUID,
        fields: dict[str, str],
        uploads: dict[str, UUID],
        replace_fields: list[str],
        preparation_version_id: UUID | None,
        request_id: UUID,
    ) -> "BrowserCommand":
        session = object_session(self)
        if session is None:
            raise ValueError("Share a form first")
        self.require_current()
        device = session.get(BrowserDevice, self.device_id)
        if not device or device.revoked_at or self.created_at < utc_now() - timedelta(minutes=30):
            raise RecordConflict("Share a fresh form from a paired browser")
        known = {field["id"]: field for field in self.fields}
        requested = set(fields) | set(uploads)
        if not requested or not set(replace_fields) <= requested:
            raise ValueError("Use valid fields from this snapshot")
        for field_id, value in fields.items():
            field = known.get(field_id)
            if field is None or field["type"] in {"file", "unsupported"}:
                raise ValueError("Use valid values for fields in this snapshot")
            if field.get("value_state") == "present" and field_id not in replace_fields:
                raise RecordConflict("Choose explicitly before replacing an existing value")
            if field["type"] in {"select", "radio"} and value not in field.get("options", []):
                raise ValueError("Use one of the options shared for this field")
            if field["type"] == "checkbox" and value not in {"true", "false"}:
                raise ValueError("Checkbox values must be true or false")
            if field["type"] == "number":
                validate_numeric_answer(field, value)
            if field["type"] in {"date", "month"}:
                validate_temporal_answer(field, value)
        reviewed = (
            preparation_payload(session, self.owner_id, preparation_version_id)
            if preparation_version_id is not None
            else None
        )
        if reviewed is not None:
            validate_preparation_command(
                reviewed,
                snapshot_id=self.id,
                fields=fields,
                uploads=uploads,
                replace_fields=replace_fields,
            )
        upload_files: dict[str, dict[str, object]] = {}
        for field_id, version_id in uploads.items():
            field = known.get(field_id)
            if field is None or field["type"] != "file":
                raise ValueError("Upload only to file fields in this snapshot")
            if field.get("value_state") == "present" and field_id not in replace_fields:
                raise RecordConflict("Choose explicitly before replacing an existing file")
            kind: Literal["resume", "cover-letter"] = (
                "cover-letter"
                if reviewed is not None
                and field_id in reviewed.get("cover_letter_upload_fields", [])
                else "resume"
            )
            metadata = application_file(session, self.owner_id, version_id, kind=kind)
            if not file_accepts(
                str(metadata["filename"]), str(metadata["media_type"]), field.get("accept", "")
            ):
                raise ValueError("The selected document is not accepted by this file field")
            upload_files[field_id] = metadata
        command = BrowserCommand(
            id=command_id,
            owner_id=self.owner_id,
            device_id=self.device_id,
            snapshot_id=self.id,
            fields=fields,
            uploads={field_id: str(version_id) for field_id, version_id in uploads.items()},
            replace_fields=replace_fields,
            preparation_version_id=preparation_version_id,
            upload_files=upload_files,
            field_results={},
            expires_at=utc_now() + timedelta(minutes=10),
        )
        session.add(command)
        record_event(
            session,
            self.owner_id,
            request_id,
            "browser.fill_proposed",
            "browser_commands",
            command_id,
            origin=self.origin,
            field_count=len(fields),
            upload_count=len(uploads),
        )
        return command


class BrowserCommand(Base):
    __tablename__ = "browser_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "device_id", "owner_id"],
            ["browser_snapshots.id", "browser_snapshots.device_id", "browser_snapshots.owner_id"],
        ),
        CheckConstraint(
            "state IN ('pending', 'claimed', 'applied', 'partial', 'rejected', 'failed', "
            "'outcome_unknown')",
            name="state",
        ),
        CheckConstraint("jsonb_typeof(uploads) = 'object'", name="uploads_object"),
        CheckConstraint("jsonb_typeof(replace_fields) = 'array'", name="replace_fields_array"),
        CheckConstraint("jsonb_typeof(upload_files) = 'object'", name="upload_files_object"),
        CheckConstraint("jsonb_typeof(field_results) = 'object'", name="field_results_object"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    device_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid)
    fields: Mapped[dict[str, str]] = mapped_column(JSONB)
    uploads: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    replace_fields: Mapped[list[str]] = mapped_column(JSONB, default=list)
    preparation_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifact_versions.id"))
    upload_files: Mapped[dict[str, dict[str, Any]]] = mapped_column(JSONB, default=dict)
    field_results: Mapped[dict[str, dict[str, str]]] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @property
    def requested_fields(self) -> set[str]:
        return set(self.fields) | set(self.uploads)

    def expire(self, *, request_id: UUID) -> None:
        if self.state in {"pending", "claimed"} and self.expires_at <= utc_now():
            state = "outcome_unknown" if self.state == "claimed" else "rejected"
            status = "outcome_unknown" if self.state == "claimed" else "rejected"
            results = {
                field_id: {"status": status, "detail": "Command expired before confirmation"}
                for field_id in self.requested_fields
            }
            self._finish(state, results, request_id)

    def claim(self, *, request_id: UUID) -> None:
        if self.state != "pending" or self.expires_at <= utc_now():
            raise RecordConflict(
                "This command has already been claimed or expired; do not replay it"
            )
        session = object_session(self)
        if session is None:
            raise RecordConflict("This command is unavailable")
        snapshot = session.get(BrowserSnapshot, self.snapshot_id)
        if snapshot is None:
            raise RecordConflict("Reshare this form before applying values")
        snapshot.require_current()
        reviewed = None
        if self.preparation_version_id is not None:
            reviewed = preparation_payload(session, self.owner_id, self.preparation_version_id)
            validate_preparation_command(
                reviewed,
                snapshot_id=self.snapshot_id,
                fields=self.fields,
                uploads={key: UUID(value) for key, value in self.uploads.items()},
                replace_fields=self.replace_fields,
            )
        for field_id, metadata in self.upload_files.items():
            kind: Literal["resume", "cover-letter"] = (
                "cover-letter"
                if reviewed is not None
                and field_id in reviewed.get("cover_letter_upload_fields", [])
                else "resume"
            )
            application_file(session, self.owner_id, UUID(str(metadata["version_id"])), kind=kind)
        self.state = "claimed"
        record_event(
            session,
            self.owner_id,
            request_id,
            "browser.fill_claimed",
            "browser_commands",
            self.id,
        )

    def report(
        self,
        state: str,
        field_results: dict[str, dict[str, str]],
        *,
        request_id: UUID,
    ) -> None:
        if state not in {"applied", "partial", "rejected", "failed", "outcome_unknown"}:
            raise ValueError("Invalid fill outcome")
        if self.state in {"applied", "partial", "rejected", "failed", "outcome_unknown"}:
            if self.state == state and self.field_results == field_results:
                return
            raise RecordConflict("A different terminal result is already recorded")
        if self.state != "claimed":
            raise RecordConflict("Only a claimed command can receive an outcome")
        if set(field_results) != self.requested_fields:
            raise ValueError("Report one result for every requested field")
        for field_id, result in field_results.items():
            status = result.get("status")
            if field_id in self.uploads and status == "filled":
                raise ValueError("File fields must report uploads separately")
            if field_id in self.fields and status == "uploaded":
                raise ValueError("Text fields cannot report file uploads")
        statuses = {result["status"] for result in field_results.values()}
        successes = statuses & {"filled", "uploaded"}
        if "outcome_unknown" in statuses:
            expected = "outcome_unknown"
        elif statuses and statuses <= {"filled", "uploaded"}:
            expected = "applied"
        elif successes:
            expected = "partial"
        elif "failed" in statuses:
            expected = "failed"
        else:
            expected = "rejected"
        if state != expected:
            raise ValueError("Overall result does not match the per-field outcomes")
        self._finish(state, field_results, request_id)

    def _finish(
        self, state: str, field_results: dict[str, dict[str, str]], request_id: UUID
    ) -> None:
        self.state, self.field_results, self.completed_at = state, field_results, utc_now()
        session = object_session(self)
        if session:
            record_event(
                session,
                self.owner_id,
                request_id,
                f"browser.fill_{state}",
                "browser_commands",
                self.id,
            )
