"""Small HTTP controllers over actor-owned models and transaction receipts."""

from collections.abc import Callable, Iterator
from typing import Annotated, Any, TypeVar, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, HttpUrl
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from command_center.api import schemas as s
from command_center.core.identity import CurrentIdentity
from command_center.db.base import Base, utc_now
from command_center.db.crm import (
    CandidateProfile,
    Company,
    Contact,
    Job,
    Opportunity,
    OwnedRecord,
    record_event,
)
from command_center.db.idempotency import RequestReceipt
from command_center.db.models import AuditEvent, Task

router = APIRouter(prefix="/api/v1", tags=["workspace"])


def transaction(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session, session.begin():
        session.info["agent_run_id"] = getattr(request.state, "agent_run_id", None)
        yield session


Database = Annotated[Session, Depends(transaction)]
WriteKey = Annotated[UUID, Header(alias="Idempotency-Key")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Search = Annotated[str, Query(max_length=200)]
Record = TypeVar("Record", bound=Base)


def serialize(record: Base) -> dict[str, Any]:
    return dict(
        jsonable_encoder(
            {
                c.key: getattr(record, c.key)
                for c in inspect(type(record)).columns
                if c.key != "owner_id"
            }
        )
    )


def attribute(record: Any, name: str) -> Any:
    return getattr(record, name)


def owned[Record: Base](
    session: Session, model: type[Record], record_id: UUID, actor_id: UUID, *, lock: bool = False
) -> Record:
    statement = select(model).where(
        attribute(model, "id") == record_id, attribute(model, "owner_id") == actor_id
    )
    if lock:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(404, "Record not found")
    return row


def check_version(record: Any, expected: int) -> None:
    if record.row_version != expected:
        raise HTTPException(409, "This record changed. Refresh it before saving again.")
    if getattr(record, "archived_at", None):
        raise HTTPException(409, "Archived records cannot be edited")


def values(body: BaseModel, *, patch: bool = False) -> dict[str, Any]:
    result = body.model_dump(exclude_unset=patch, exclude={"expected_version"})
    return {
        key: str(value) if isinstance(value, HttpUrl) else value for key, value in result.items()
    }


def references(session: Session, actor_id: UUID, data: dict[str, Any]) -> None:
    for name, model in [
        ("company_id", Company),
        ("contact_id", Contact),
        ("job_id", Job),
        ("opportunity_id", Opportunity),
    ]:
        if data.get(name):
            row = owned(session, model, data[name], actor_id)
            if attribute(row, "archived_at"):
                raise HTTPException(422, "Choose an active linked record")
            if (
                name == "job_id"
                and data.get("company_id")
                and attribute(row, "company_id") != data["company_id"]
            ):
                raise HTTPException(422, "The job must belong to the selected company")


def write(
    session: Session,
    actor_id: UUID,
    key: UUID,
    operation: str,
    body: BaseModel,
    change: Callable[[UUID], dict[str, Any]],
) -> dict[str, Any]:
    return RequestReceipt.execute(
        session,
        actor_id=actor_id,
        key=key,
        operation=operation,
        payload=body.model_dump(mode="json"),
        change=change,
    )


def create_record[Record: Base](
    model: type[Record],
    body: BaseModel,
    session: Session,
    actor_id: UUID,
    key: UUID,
    request_id: UUID,
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        data = values(body)
        references(session, actor_id, data)
        record = model(id=record_id, owner_id=actor_id, **data)
        session.add(record)
        session.flush()
        record_event(
            session,
            actor_id,
            request_id,
            f"{model.__tablename__}.created",
            model.__tablename__,
            record_id,
        )
        return serialize(record)

    return write(session, actor_id, key, f"POST:{model.__tablename__}", body, change)


def update_record[Record: Base](
    model: type[Record],
    record_id: UUID,
    body: s.Revision,
    session: Session,
    actor_id: UUID,
    key: UUID,
    request_id: UUID,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        record = owned(session, model, record_id, actor_id, lock=True)
        check_version(record, body.expected_version)
        data = values(body, patch=True)
        for column in inspect(model).columns:
            if column.key in data and data[column.key] is None and not column.nullable:
                raise HTTPException(422, f"{column.key} is required")
        references(session, actor_id, data)
        cast(OwnedRecord | Task, record).revise(data, request_id=request_id)
        session.flush()
        return serialize(record)

    return write(session, actor_id, key, f"PATCH:{model.__tablename__}:{record_id}", body, change)


def archive_record[Record: Base](
    model: type[Record],
    record_id: UUID,
    body: s.Revision,
    session: Session,
    actor_id: UUID,
    key: UUID,
    request_id: UUID,
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        record = owned(session, model, record_id, actor_id, lock=True)
        check_version(record, body.expected_version)
        cast(OwnedRecord, record).archive(request_id=request_id)
        session.flush()
        return serialize(record)

    return write(session, actor_id, key, f"ARCHIVE:{model.__tablename__}:{record_id}", body, change)


def listing[Record: Base](
    model: type[Record],
    session: Session,
    actor_id: UUID,
    q: str,
    limit: int,
    offset: int,
    **filters: Any,
) -> dict[str, Any]:
    statement = select(model).where(attribute(model, "owner_id") == actor_id)
    if hasattr(model, "archived_at"):
        statement = statement.where(attribute(model, "archived_at").is_(None))
    if q:
        column = getattr(model, "name", None)
        if column is None:
            column = attribute(model, "title")
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(column.ilike(f"%{escaped}%", escape="\\"))
    for key, value in filters.items():
        if value is not None:
            statement = statement.where(getattr(model, key) == value)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(
        statement.order_by(attribute(model, "created_at").desc(), attribute(model, "id"))
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/me", response_model=s.ProfileRead)
def me(identity: CurrentIdentity, db: Database) -> CandidateProfile:
    from sqlalchemy.dialects.postgresql import insert

    db.execute(insert(CandidateProfile).values(actor_id=identity.id).on_conflict_do_nothing())
    profile = db.get(CandidateProfile, identity.id)
    assert profile is not None
    return profile


@router.patch("/me", response_model=s.ProfileRead)
def update_me(
    body: s.ProfileUpdate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        profile = db.scalar(
            select(CandidateProfile)
            .where(CandidateProfile.actor_id == identity.id)
            .with_for_update()
        )
        if profile is None:
            raise HTTPException(409, "Load your profile before editing")
        check_version(profile, body.expected_version)
        profile.revise(values(body, patch=True), request_id=UUID(request.state.request_id))
        db.flush()
        return serialize(profile)

    return write(db, identity.id, key, "PATCH:me", body, change)


@router.get("/activity", response_model=s.Page[s.ActivityRead])
def activity(
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 30,
    offset: Offset = 0,
    subject_id: UUID | None = None,
) -> dict[str, Any]:
    statement = select(AuditEvent).where(AuditEvent.actor_id == identity.id)
    if subject_id:
        statement = statement.where(AuditEvent.subject_id == subject_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    events = db.scalars(
        statement.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id).limit(limit).offset(offset)
    ).all()
    return {"items": events, "total": total, "limit": limit, "offset": offset}


@router.get("/company-labels", response_model=list[s.CompanyLabel])
def company_labels(
    identity: CurrentIdentity,
    db: Database,
    ids: Annotated[list[UUID] | None, Query(max_length=100)] = None,
) -> list[Company]:
    if not ids:
        return []
    return list(
        db.scalars(
            select(Company).where(
                Company.owner_id == identity.id,
                Company.archived_at.is_(None),
                Company.id.in_(ids),
            )
        )
    )


@router.get("/dashboard")
def dashboard(identity: CurrentIdentity, db: Database) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for model in [Company, Contact, Opportunity]:
        counts[model.__tablename__] = (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    attribute(model, "owner_id") == identity.id,
                    attribute(model, "archived_at").is_(None),
                )
            )
            or 0
        )
    counts["tasks"] = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.owner_id == identity.id, Task.state.in_(["open", "in_progress", "snoozed"]))
        )
        or 0
    )
    stages = {
        key: count
        for key, count in db.execute(
            select(Opportunity.stage, func.count())
            .where(Opportunity.owner_id == identity.id, Opportunity.archived_at.is_(None))
            .group_by(Opportunity.stage)
        ).all()
    }
    upcoming = db.scalars(
        select(Task)
        .where(Task.owner_id == identity.id, Task.state.in_(["open", "in_progress"]))
        .order_by(
            Task.due_date.asc().nulls_last(), Task.due_at.asc().nulls_last(), Task.priority.desc()
        )
        .limit(6)
    ).all()
    return {"counts": counts, "stages": stages, "tasks": [serialize(t) for t in upcoming]}


@router.post("/demo")
def demo(
    identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    """Explicit, repeatable synthetic fixture import; never copy personal source data."""

    def change(_: UUID) -> dict[str, Any]:
        added = 0
        samples = [
            (
                "Orbit Labs",
                "Developer tools",
                "San Francisco",
                "Staff Product Engineer",
                "interviewing",
            ),
            ("Northstar", "Climate tech", "Remote", "Senior Software Engineer", "preparing"),
            ("Forma", "Design software", "New York", "Founding Engineer", "researching"),
            ("Meridian", "Infrastructure", "Remote", "Platform Engineer", "applied"),
            ("Atlas Studio", "Product studio", "London", "Engineering Lead", "researching"),
        ]
        for index, (name, industry, location, title, stage) in enumerate(samples):
            company_id = uuid5(identity.id, f"demo:company:{index}")
            if db.get(Company, company_id):
                continue
            company = Company(
                id=company_id,
                owner_id=identity.id,
                name=name,
                industry=industry,
                location=location,
                domain=f"{name.lower().replace(' ', '-')}.example",
                description="Synthetic example company. Replace with your own research.",
            )
            db.add(company)
            db.flush()
            contact_id = uuid5(identity.id, f"demo:contact:{index}")
            db.add(
                Contact(
                    id=contact_id,
                    owner_id=identity.id,
                    company_id=company_id,
                    name=["Alex Morgan", "Sam Rivera", "Jordan Lee", "Taylor Chen", "Casey Parker"][
                        index
                    ],
                    title="Engineering Manager",
                    email=f"hello@{company.domain}",
                    relationship=["warm", "connected", "new", "advocate", "new"][index],
                )
            )
            db.flush()
            opportunity_id = uuid5(identity.id, f"demo:opportunity:{index}")
            db.add(
                Opportunity(
                    id=opportunity_id,
                    owner_id=identity.id,
                    company_id=company_id,
                    contact_id=contact_id,
                    title=title,
                    stage=stage,
                    priority=2 if index < 2 else 1,
                    notes="Synthetic example opportunity. No application has been sent.",
                )
            )
            db.flush()
            db.add(
                Task(
                    id=uuid5(identity.id, f"demo:task:{index}"),
                    owner_id=identity.id,
                    opportunity_id=opportunity_id,
                    title=[
                        "Prepare the technical interview brief",
                        "Tailor a resume for Northstar",
                        "Research the engineering team",
                        "Follow up on the application",
                        "Review the company and role",
                    ][index],
                    priority=2 if index < 2 else 1,
                    due_date=utc_now().date(),
                )
            )
            added += 1
        record_event(
            db,
            identity.id,
            UUID(request.state.request_id),
            "workspace.examples_added",
            "workspace",
            identity.id,
            companies=added,
        )
        return {"added": added}

    return write(db, identity.id, key, "POST:demo", s.Contract(), change)


@router.get("/companies", response_model=s.Page[s.CompanyRead])
def list_companies(
    identity: CurrentIdentity, db: Database, q: Search = "", limit: Limit = 30, offset: Offset = 0
) -> dict[str, Any]:
    return listing(Company, db, identity.id, q, limit, offset)


@router.get("/companies/{record_id}", response_model=s.CompanyRead)
def get_company(record_id: UUID, identity: CurrentIdentity, db: Database) -> Company:
    return owned(db, Company, record_id, identity.id)


@router.post("/companies", response_model=s.CompanyRead, status_code=201)
def create_company(
    body: s.CompanyCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    return create_record(Company, body, db, identity.id, key, UUID(request.state.request_id))


@router.patch("/companies/{record_id}", response_model=s.CompanyRead)
def update_company(
    record_id: UUID,
    body: s.CompanyUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return update_record(
        Company, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.post("/companies/{record_id}/archive", response_model=s.CompanyRead)
def archive_company(
    record_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return archive_record(
        Company, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.get("/contacts", response_model=s.Page[s.ContactRead])
def list_contacts(
    identity: CurrentIdentity,
    db: Database,
    q: Search = "",
    limit: Limit = 30,
    offset: Offset = 0,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    return listing(Contact, db, identity.id, q, limit, offset, company_id=company_id)


@router.get("/contacts/{record_id}", response_model=s.ContactRead)
def get_contact(record_id: UUID, identity: CurrentIdentity, db: Database) -> Contact:
    return owned(db, Contact, record_id, identity.id)


@router.post("/contacts", response_model=s.ContactRead, status_code=201)
def create_contact(
    body: s.ContactCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    return create_record(Contact, body, db, identity.id, key, UUID(request.state.request_id))


@router.patch("/contacts/{record_id}", response_model=s.ContactRead)
def update_contact(
    record_id: UUID,
    body: s.ContactUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return update_record(
        Contact, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.post("/contacts/{record_id}/archive", response_model=s.ContactRead)
def archive_contact(
    record_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return archive_record(
        Contact, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.get("/jobs", response_model=s.Page[s.JobRead])
def list_jobs(
    identity: CurrentIdentity,
    db: Database,
    q: Search = "",
    limit: Limit = 30,
    offset: Offset = 0,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    return listing(Job, db, identity.id, q, limit, offset, company_id=company_id)


@router.get("/jobs/{record_id}", response_model=s.JobRead)
def get_job(record_id: UUID, identity: CurrentIdentity, db: Database) -> Job:
    return owned(db, Job, record_id, identity.id)


@router.post("/jobs", response_model=s.JobRead, status_code=201)
def create_job(
    body: s.JobCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    return create_record(Job, body, db, identity.id, key, UUID(request.state.request_id))


@router.patch("/jobs/{record_id}", response_model=s.JobRead)
def update_job(
    record_id: UUID,
    body: s.JobUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return update_record(Job, record_id, body, db, identity.id, key, UUID(request.state.request_id))


@router.post("/jobs/{record_id}/archive", response_model=s.JobRead)
def archive_job(
    record_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return archive_record(
        Job, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.get("/opportunities", response_model=s.Page[s.OpportunityRead])
def list_opportunities(
    identity: CurrentIdentity,
    db: Database,
    q: Search = "",
    limit: Limit = 30,
    offset: Offset = 0,
    company_id: UUID | None = None,
    stage: s.Stage | None = None,
) -> dict[str, Any]:
    return listing(
        Opportunity, db, identity.id, q, limit, offset, company_id=company_id, stage=stage
    )


@router.get("/opportunities/{record_id}", response_model=s.OpportunityRead)
def get_opportunity(record_id: UUID, identity: CurrentIdentity, db: Database) -> Opportunity:
    return owned(db, Opportunity, record_id, identity.id)


@router.post("/opportunities", response_model=s.OpportunityRead, status_code=201)
def create_opportunity(
    body: s.OpportunityCreate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return create_record(Opportunity, body, db, identity.id, key, UUID(request.state.request_id))


@router.patch("/opportunities/{record_id}", response_model=s.OpportunityRead)
def update_opportunity(
    record_id: UUID,
    body: s.OpportunityUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return update_record(
        Opportunity, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.post("/opportunities/{record_id}/archive", response_model=s.OpportunityRead)
def archive_opportunity(
    record_id: UUID,
    body: s.Revision,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return archive_record(
        Opportunity, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )


@router.get("/tasks", response_model=s.Page[s.TaskRead])
def list_tasks(
    identity: CurrentIdentity,
    db: Database,
    q: Search = "",
    limit: Limit = 30,
    offset: Offset = 0,
    opportunity_id: UUID | None = None,
    state: s.TaskState | None = None,
) -> dict[str, Any]:
    return listing(
        Task, db, identity.id, q, limit, offset, opportunity_id=opportunity_id, state=state
    )


@router.get("/tasks/{record_id}", response_model=s.TaskRead)
def get_task(record_id: UUID, identity: CurrentIdentity, db: Database) -> Task:
    return owned(db, Task, record_id, identity.id)


@router.post("/tasks", response_model=s.TaskRead, status_code=201)
def create_task(
    body: s.TaskCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    return create_record(Task, body, db, identity.id, key, UUID(request.state.request_id))


@router.patch("/tasks/{record_id}", response_model=s.TaskRead)
def update_task(
    record_id: UUID,
    body: s.TaskUpdate,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    return update_record(
        Task, record_id, body, db, identity.id, key, UUID(request.state.request_id)
    )
