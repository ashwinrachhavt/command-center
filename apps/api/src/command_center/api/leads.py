"""Job-lead capture and public evidence controllers."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from command_center.api import schemas as s
from command_center.api.workspace import Database, Limit, Offset, WriteKey, owned
from command_center.core.capabilities import fence_agent_write
from command_center.core.identity import CurrentIdentity
from command_center.core.public_urls import normalize_public_url
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.crm import Job, Opportunity
from command_center.db.evidence import SourceRecord
from command_center.db.idempotency import IdempotencyConflict, RequestReceipt
from command_center.integrations.clients import ProviderError
from command_center.integrations.public_research import scrape_public

router = APIRouter(prefix="/api/v1", tags=["leads"])


class LeadCaptureRequest(s.Contract):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=300)
    company_name: str = Field(min_length=1, max_length=200)
    snippet: str | None = Field(default=None, max_length=3000)


class LeadSourceRead(s.ResponseContract):
    id: UUID
    artifact_id: UUID
    version_id: UUID
    version: int
    url: str
    title: str
    provider: str
    retrieved_at: datetime
    excerpt: str


class LeadCaptureRead(s.ResponseContract):
    opportunity_id: UUID
    job_id: UUID
    company_id: UUID
    created: bool
    source: LeadSourceRead


def source_read(session: Session, source: SourceRecord) -> LeadSourceRead:
    version = session.get(ArtifactVersion, source.artifact_version_id)
    artifact = session.get(Artifact, version.artifact_id) if version else None
    if version is None or artifact is None:
        raise ValueError("Source provenance is incomplete")
    payload = version.payload or {}
    text = payload.get("text", "")
    if not isinstance(text, str):
        raise ValueError("Source content is not text")
    return LeadSourceRead(
        id=source.id,
        artifact_id=artifact.id,
        version_id=version.id,
        version=version.version,
        url=source.locator,
        title=artifact.title,
        provider=source.provider,
        retrieved_at=source.retrieved_at,
        excerpt=text[:3000],
    )


@router.post("/leads/capture", response_model=LeadCaptureRead, status_code=status.HTTP_201_CREATED)
def capture_lead(
    body: LeadCaptureRequest,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    url = normalize_public_url(body.url)
    payload = body.model_dump()
    payload["url"] = url
    request_id = UUID(request.state.request_id)

    def change(record_id: UUID) -> dict[str, Any]:
        opportunity, job, company, source, created = Opportunity.capture_lead(
            db,
            record_id=record_id,
            owner_id=identity.id,
            url=url,
            title=body.title,
            company_name=body.company_name,
            snippet=body.snippet or "",
            request_id=request_id,
        )
        result = LeadCaptureRead(
            opportunity_id=opportunity.id,
            job_id=job.id,
            company_id=company.id,
            created=created,
            source=source_read(db, source),
        )
        return result.model_dump(mode="json")

    return RequestReceipt.execute(
        db,
        actor_id=identity.id,
        key=key,
        operation="POST:/api/v1/leads/capture",
        payload=payload,
        change=change,
    )


@router.get("/opportunities/{opportunity_id}/research", response_model=s.Page[LeadSourceRead])
def opportunity_research(
    opportunity_id: UUID,
    identity: CurrentIdentity,
    db: Database,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict[str, Any]:
    owned(db, Opportunity, opportunity_id, identity.id)
    statement = (
        select(SourceRecord)
        .join(ArtifactVersion, ArtifactVersion.id == SourceRecord.artifact_version_id)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(
            SourceRecord.opportunity_id == opportunity_id,
            Artifact.owner_id == identity.id,
        )
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    sources = db.scalars(
        statement.order_by(SourceRecord.retrieved_at.desc(), SourceRecord.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [source_read(db, source).model_dump(mode="json") for source in sources],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/opportunities/{opportunity_id}/enrich",
    response_model=LeadSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def enrich_opportunity(
    opportunity_id: UUID,
    identity: CurrentIdentity,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    operation = f"POST:/api/v1/opportunities/{opportunity_id}/enrich"
    engine = request.app.state.engine

    # Keep receipt/ownership lookup short and release its read transaction before I/O.
    with Session(engine) as session:
        receipt = session.get(RequestReceipt, (identity.id, key))
        if receipt is not None:
            if receipt.operation != operation:
                raise IdempotencyConflict(
                    "This idempotency key was already used with different input"
                )
            return dict(receipt.response)
        opportunity = owned(session, Opportunity, opportunity_id, identity.id)
        if opportunity.job_id is None:
            raise ValueError("Opportunity has no job source")
        job = session.scalar(
            select(Job).where(Job.id == opportunity.job_id, Job.owner_id == identity.id)
        )
        if job is None or job.source_url is None:
            raise ValueError("Opportunity has no job source")
        original_job_id = job.id
        original_target = job.source_url
        fetch_url = normalize_public_url(original_target)
        fallback_title = opportunity.title

    try:
        page = await scrape_public(request.app.state.firecrawl, fetch_url)
    except ProviderError as exc:
        raise HTTPException(503, "Web research is temporarily unavailable") from exc

    page_url = normalize_public_url(page.url)
    page_title = page.title.strip()[:300] or fallback_title
    request_id = UUID(request.state.request_id)
    with Session(engine) as session, session.begin():
        session.info["agent_run_id"] = getattr(request.state, "agent_run_id", None)

        def change(source_id: UUID) -> dict[str, Any]:
            fence_agent_write(request, session)
            current = owned(session, Opportunity, opportunity_id, identity.id, lock=True)
            if current.job_id != original_job_id:
                raise ValueError("Opportunity job source changed during enrichment")
            current_job = session.scalar(
                select(Job)
                .where(Job.id == original_job_id, Job.owner_id == identity.id)
                .with_for_update()
            )
            if current_job is None or current_job.source_url != original_target:
                raise ValueError("Opportunity job source changed during enrichment")
            source = SourceRecord.capture_for_opportunity(
                session,
                record_id=source_id,
                opportunity_id=current.id,
                owner_id=identity.id,
                title=page_title,
                url=page_url,
                text=page.markdown,
                provider=page.provider,
                extraction_method=page.extraction_method,
                request_id=request_id,
            )
            return source_read(session, source).model_dump(mode="json")

        return RequestReceipt.execute(
            session,
            actor_id=identity.id,
            key=key,
            operation=operation,
            payload={},
            change=change,
        )
