"""Public HTTP contracts. Ownership and IDs are assigned by the server."""

from datetime import date, datetime
from typing import Annotated, Any, Literal, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

Name = Annotated[str, Field(min_length=1, max_length=200)]
Title = Annotated[str, Field(min_length=1, max_length=300)]
Notes = Annotated[str, Field(max_length=20000)]
Stage = Literal["researching", "preparing", "applied", "interviewing", "offer", "closed"]
TaskState = Literal["open", "in_progress", "snoozed", "done", "cancelled"]
Relationship = Literal["new", "connected", "warm", "advocate"]
WorkMode = Literal["remote", "hybrid", "onsite", "unspecified"]
Priority = Annotated[int, Field(ge=0, le=3)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class Revision(Contract):
    expected_version: int = Field(ge=1)


class ResponseContract(Contract):
    # Persisted records contain private/internal columns; responses expose only declared fields.
    model_config = ConfigDict(extra="ignore")


class CompanyCreate(Contract):
    name: Name
    domain: str | None = Field(default=None, max_length=253, pattern=r"^[a-zA-Z0-9.-]+$")
    industry: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=200)
    description: Notes | None = None


class CompanyUpdate(Revision):
    name: Name | None = None
    domain: str | None = Field(default=None, max_length=253, pattern=r"^[a-zA-Z0-9.-]+$")
    industry: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=200)
    description: Notes | None = None


class ContactCreate(Contract):
    name: Name
    email: EmailStr | None = None
    title: Title | None = None
    company_id: UUID | None = None
    linkedin_url: HttpUrl | None = None
    relationship: Relationship = "new"
    notes: Notes | None = None


class ContactUpdate(Revision):
    name: Name | None = None
    email: EmailStr | None = None
    title: Title | None = None
    company_id: UUID | None = None
    linkedin_url: HttpUrl | None = None
    relationship: Relationship | None = None
    notes: Notes | None = None


class JobCreate(Contract):
    company_id: UUID
    title: Title
    location: str | None = Field(default=None, max_length=200)
    work_mode: WorkMode = "unspecified"
    source_url: HttpUrl | None = None
    salary_min: int | None = Field(default=None, ge=0, le=100000000)
    salary_max: int | None = Field(default=None, ge=0, le=100000000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    status: Literal["open", "closed", "unknown"] = "open"
    description: Notes | None = None


class JobUpdate(Revision):
    title: Title | None = None
    location: str | None = Field(default=None, max_length=200)
    work_mode: WorkMode | None = None
    source_url: HttpUrl | None = None
    salary_min: int | None = Field(default=None, ge=0, le=100000000)
    salary_max: int | None = Field(default=None, ge=0, le=100000000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    status: Literal["open", "closed", "unknown"] | None = None
    description: Notes | None = None


class OpportunityCreate(Contract):
    title: Title
    company_id: UUID
    job_id: UUID | None = None
    contact_id: UUID | None = None
    stage: Stage = "researching"
    priority: Priority = 1
    notes: Notes | None = None


class OpportunityUpdate(Revision):
    title: Title | None = None
    contact_id: UUID | None = None
    stage: Stage | None = None
    priority: Priority | None = None
    notes: Notes | None = None


class TaskCreate(Contract):
    title: Title
    opportunity_id: UUID | None = None
    priority: Priority = 1
    rationale: Notes | None = None
    due_date: date | None = None
    due_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_due(self) -> "TaskCreate":
        if self.due_date and self.due_at:
            raise ValueError("Choose a due date or an exact due time")
        return self


class TaskUpdate(Revision):
    title: Title | None = None
    opportunity_id: UUID | None = None
    state: TaskState | None = None
    priority: Priority | None = None
    rationale: Notes | None = None
    due_date: date | None = None
    due_at: AwareDatetime | None = None


class RecordRead(ResponseContract):
    id: UUID
    row_version: int
    created_at: datetime
    updated_at: datetime


class CompanyRead(CompanyCreate, RecordRead):
    archived_at: datetime | None


class CompanyLabel(ResponseContract):
    id: UUID
    name: str


class ContactRead(ContactCreate, RecordRead):
    archived_at: datetime | None


class JobRead(JobCreate, RecordRead):
    archived_at: datetime | None


class OpportunityRead(OpportunityCreate, RecordRead):
    archived_at: datetime | None


class TaskRead(TaskCreate, RecordRead):
    state: TaskState
    completed_at: datetime | None


Item = TypeVar("Item")


class Page[Item](Contract):
    items: list[Item]
    total: int
    limit: int
    offset: int


class ArtifactCreate(Contract):
    title: Title
    kind: Literal["document", "message", "research", "package", "source"] = "document"
    sensitivity: Literal["public", "private", "restricted"] = "private"
    document_type_id: UUID | None = None
    text: str = Field(default="", max_length=100000)


class ArtifactUpdate(Revision):
    title: Title | None = None
    sensitivity: Literal["public", "private", "restricted"] | None = None


class ArtifactRead(RecordRead):
    title: str
    kind: str
    sensitivity: str
    archived_at: datetime | None
    latest_version: int = 0
    document_type_id: UUID | None = None


class VersionCreate(Revision):
    based_on_version_id: UUID
    text: str = Field(max_length=100000)


class VersionRead(ResponseContract):
    id: UUID
    artifact_id: UUID
    version: int
    payload: dict[str, Any] | None
    content_sha256: str
    created_at: datetime


class VersionLineageRead(ResponseContract):
    artifact_id: UUID
    artifact_title: str
    artifact_kind: str
    version_id: UUID
    version: int
    content_sha256: str
    media_type: str
    method: str
    depth: int


class ReviewCreate(Contract):
    decision: Literal["approved", "rejected", "revoked"]
    reason: str = Field(min_length=1, max_length=2000)


class ReviewRead(ReviewCreate, ResponseContract):
    id: UUID
    artifact_version_id: UUID
    created_at: datetime


class ActivityRead(Contract):
    id: UUID
    action: str
    subject_type: str
    subject_id: UUID
    occurred_at: datetime
    details: dict[str, Any]


class ProfileUpdate(Revision):
    display_name: Name
    headline: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    timezone: str = Field(default="UTC", max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Choose a valid IANA time zone") from exc
        return value


class ProfileRead(Contract):
    actor_id: UUID
    display_name: str
    headline: str
    location: str
    timezone: str
    row_version: int
