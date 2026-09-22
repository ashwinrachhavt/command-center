"""Canonical HTTP and extension message contracts; generated clients never own schemas."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, HttpUrl

from command_center.api import schemas as s

FieldId = Annotated[str, Field(pattern=r"^f[0-9]{1,3}$")]
FieldValue = Annotated[str, Field(max_length=5000)]
Option = Annotated[str, Field(max_length=300)]


class PairCreate(s.Contract):
    name: str = Field(default="My browser", min_length=1, max_length=100)


class PairExchange(s.Contract):
    code: str = Field(min_length=32, max_length=100)


class FormField(s.Contract):
    id: str = Field(pattern=r"^f[0-9]{1,3}$")
    label: str = Field(max_length=500)
    type: Literal["text", "email", "tel", "url", "textarea", "select"]
    required: bool = False
    options: list[Option] = Field(default_factory=list, max_length=100)


class SnapshotCreate(s.Contract):
    id: UUID
    page_url: HttpUrl
    title: str = Field(max_length=300)
    fields: list[FormField] = Field(max_length=100)


class FillCreate(s.Contract):
    snapshot_id: UUID
    fields: dict[FieldId, FieldValue] = Field(min_length=1, max_length=100)


class FillResult(s.Contract):
    state: Literal["applied", "rejected", "failed", "outcome_unknown"]


class PairCredentials(s.Contract):
    device_id: UUID
    token: str = Field(min_length=32)


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


class ClaimResult(s.Contract):
    state: Literal["claimed"]


class InspectMessage(s.Contract):
    version: Literal[1]
    action: Literal["inspect"]


class ApplyMessage(s.Contract):
    version: Literal[1]
    action: Literal["apply"]
    command: FillCommand


class ApplyResult(FillResult):
    message: str = Field(max_length=500)
