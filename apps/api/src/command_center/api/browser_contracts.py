"""Canonical HTTP and extension message contracts; generated clients never own schemas."""

import base64
import binascii
import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from command_center.api import schemas as s
from command_center.db.browser import HTML_NUMBER_PATTERN, parse_browser_decimal

FieldId = Annotated[str, Field(pattern=r"^f[0-9]{1,3}$")]
FieldValue = Annotated[str, Field(max_length=5000)]
Option = Annotated[str, Field(max_length=300)]
OptionLabel = Annotated[str, Field(max_length=500)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_RESUME_BYTES = 20 * 1024 * 1024
MAX_RESUME_BASE64 = 4 * ((MAX_RESUME_BYTES + 2) // 3)
NumericValue = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=HTML_NUMBER_PATTERN),
]


class PairCreate(s.Contract):
    name: str = Field(default="My browser", min_length=1, max_length=100)


class PairExchange(s.Contract):
    code: str = Field(min_length=32, max_length=100)


class NumericConstraints(s.Contract):
    minimum: NumericValue | None = None
    maximum: NumericValue | None = None
    step: NumericValue | Literal["any"]
    step_base: NumericValue

    @model_validator(mode="after")
    def validate_decimals(self) -> "NumericConstraints":
        try:
            minimum = parse_browser_decimal(self.minimum) if self.minimum is not None else None
            maximum = parse_browser_decimal(self.maximum) if self.maximum is not None else None
            step = None if self.step == "any" else parse_browser_decimal(self.step)
            parse_browser_decimal(self.step_base)
        except ValueError as exc:
            raise ValueError("Numeric constraints must contain finite decimals") from exc
        if step is not None and step <= 0:
            raise ValueError("Numeric step must be positive or 'any'")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("Numeric minimum cannot exceed maximum")
        return self


class FormField(s.Contract):
    id: FieldId
    label: str = Field(max_length=500)
    type: Literal[
        "text",
        "email",
        "tel",
        "url",
        "textarea",
        "select",
        "file",
        "radio",
        "checkbox",
        "number",
        "unsupported",
    ]
    required: bool = False
    options: list[Option] = Field(default_factory=list, max_length=300)
    value_state: Literal["empty", "present"]
    autocomplete: str = Field(default="", max_length=100)
    accept: str = Field(default="", max_length=300)
    option_labels: dict[Option, OptionLabel] = Field(default_factory=dict, max_length=300)
    unsupported_reason: str | None = Field(default=None, max_length=300)
    numeric_constraints: NumericConstraints | None = None

    @model_validator(mode="after")
    def validate_options(self) -> "FormField":
        if not set(self.option_labels) <= set(self.options):
            raise ValueError("Option labels must describe shared option values")
        if self.type == "number" and self.numeric_constraints is None:
            raise ValueError("Number fields require normalized numeric constraints")
        if self.type != "number" and self.numeric_constraints is not None:
            raise ValueError("Only number fields may contain numeric constraints")
        return self


class SnapshotCreate(s.Contract):
    id: UUID
    protocol_version: Literal[2]
    page_url: HttpUrl
    title: str = Field(max_length=300)
    fields: list[FormField] = Field(max_length=100)


class FillCreate(s.Contract):
    snapshot_id: UUID
    fields: dict[FieldId, FieldValue] = Field(default_factory=dict, max_length=100)
    uploads: dict[FieldId, UUID] = Field(default_factory=dict, max_length=10)
    replace_fields: list[FieldId] = Field(default_factory=list, max_length=100)
    preparation_version_id: UUID | None = None

    @model_validator(mode="after")
    def validate_requested_fields(self) -> "FillCreate":
        field_ids, upload_ids = set(self.fields), set(self.uploads)
        if not field_ids and not upload_ids:
            raise ValueError("Choose at least one field or file to apply")
        if field_ids & upload_ids:
            raise ValueError("A form field cannot receive text and a file")
        replacements = set(self.replace_fields)
        if len(replacements) != len(self.replace_fields):
            raise ValueError("Replacement fields must be unique")
        if not replacements <= field_ids | upload_ids:
            raise ValueError("Replacement fields must be part of this command")
        return self


class FieldResult(s.Contract):
    status: Literal[
        "filled",
        "uploaded",
        "preserved",
        "unsupported",
        "rejected",
        "failed",
        "outcome_unknown",
    ]
    detail: str = Field(default="", max_length=300)


class FillResult(s.Contract):
    state: Literal["applied", "partial", "rejected", "failed", "outcome_unknown"]
    field_results: dict[FieldId, FieldResult] = Field(default_factory=dict, max_length=110)


class PairCredentials(s.Contract):
    device_id: UUID
    token: str = Field(min_length=32)


class ResumeFile(s.Contract):
    version_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=1, le=MAX_RESUME_BYTES)
    sha256: Sha256


class ResumeOption(ResumeFile):
    artifact_id: UUID
    title: str = Field(min_length=1, max_length=300)
    version: int = Field(ge=1)


class ResumeOptions(s.Contract):
    default_version_id: UUID | None
    items: list[ResumeOption] = Field(max_length=100)


class FillCommand(FillCreate):
    page_url: HttpUrl


class PendingCommand(FillCommand):
    id: UUID
    owner_id: UUID
    device_id: UUID
    state: Literal["pending"]
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    form_fields: list[FormField] = Field(max_length=100)
    upload_files: dict[FieldId, ResumeFile] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def validate_upload_metadata(self) -> "PendingCommand":
        if set(self.upload_files) != set(self.uploads):
            raise ValueError("Every requested upload needs exact file metadata")
        if any(
            self.uploads[field_id] != file.version_id
            for field_id, file in self.upload_files.items()
        ):
            raise ValueError("Upload metadata must match the pinned version")
        return self


class ClaimResult(s.Contract):
    state: Literal["claimed"]


class InspectMessage(s.Contract):
    version: Literal[2]
    action: Literal["inspect"]


class FileTransfer(ResumeFile):
    data_base64: str = Field(max_length=MAX_RESUME_BASE64)

    @model_validator(mode="after")
    def validate_bytes(self) -> "FileTransfer":
        try:
            content = base64.b64decode(self.data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Resume bytes must be valid base64") from None
        if len(content) != self.size_bytes or hashlib.sha256(content).hexdigest() != self.sha256:
            raise ValueError("Resume bytes do not match the pinned file")
        return self


class ApplyMessage(s.Contract):
    version: Literal[2]
    action: Literal["apply"]
    command: FillCommand
    files: dict[FieldId, FileTransfer] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def validate_files(self) -> "ApplyMessage":
        if set(self.files) != set(self.command.uploads):
            raise ValueError("Every requested upload needs reviewed bytes")
        if any(
            self.command.uploads[field_id] != file.version_id
            for field_id, file in self.files.items()
        ):
            raise ValueError("Transferred files must match the pinned versions")
        return self


class ApplyResult(FillResult):
    message: str = Field(default="", max_length=500)
