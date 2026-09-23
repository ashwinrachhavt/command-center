"""Explicit contact discovery; provider I/O has a durable no-replay claim."""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.api import schemas as s
from command_center.api.reviewed_actions import (
    _claim_connected,
    _fail_connected,
    _finalize_connected,
    _human,
)
from command_center.api.workspace import Database, WriteKey, owned, serialize, write
from command_center.core.identity import CurrentIdentity
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.contact_discovery import SCHEMA, ContactDiscoveryEvidence
from command_center.db.crm import Contact
from command_center.integrations.contact_discovery import (
    ContactDiscoveryClient,
    ContactProviderError,
    Prospect,
    ProspectPage,
    Provider,
    professional_domain,
)

router = APIRouter(prefix="/api/v1/contact-discovery", tags=["contact discovery"])


class DiscoveryQuery(s.Contract):
    provider: Provider
    domain: str = Field(max_length=2000)
    title: str = Field(default="", max_length=200)
    page: int = Field(default=1, ge=1, le=500)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return professional_domain(value)


class DiscoveryRead(s.ResponseContract):
    source_version_id: UUID
    source_artifact_id: UUID
    query: dict[str, Any]
    result: ProspectPage
    observed_at: datetime
    cached: bool


class ProspectSelection(s.Contract):
    source_version_id: UUID
    external_id: str = Field(min_length=1, max_length=320)


class ProspectImport(ProspectSelection):
    company_id: UUID | None = None


class ImportRead(s.ResponseContract):
    contact: s.ContactRead
    created: bool


class FillMissing(ProspectSelection, s.Revision):
    contact_id: UUID
    fields: list[Literal["email", "title", "linkedin_url"]] = Field(min_length=1, max_length=3)


class DiscoveryEvidenceRead(s.ResponseContract):
    source_version_id: UUID
    source_artifact_id: UUID
    observed_at: datetime
    prospect: Prospect


@router.get("/contacts/{contact_id}/evidence", response_model=list[DiscoveryEvidenceRead])
def evidence(contact_id: UUID, identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    owned(db, Contact, contact_id, identity.id)
    rows = db.scalars(
        select(ContactDiscoveryEvidence)
        .where(
            ContactDiscoveryEvidence.owner_id == identity.id,
            ContactDiscoveryEvidence.contact_id == contact_id,
        )
        .order_by(ContactDiscoveryEvidence.id)
        .limit(20)
    )
    results = []
    for row in rows:
        version, person = ContactDiscoveryEvidence.prospect(
            db, owner_id=identity.id, version_id=row.source_version_id, external_id=row.external_id
        )
        results.append(
            {
                "source_version_id": version.id,
                "source_artifact_id": version.artifact_id,
                "observed_at": version.created_at,
                "prospect": person.model_dump(mode="json"),
            }
        )
    return results


@router.post("/fill-missing", response_model=s.ContactRead)
def fill_missing(
    body: FillMissing, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    _human(identity)

    def change(record_id: UUID) -> dict[str, Any]:
        contact = ContactDiscoveryEvidence.fill_missing(
            db,
            owner_id=identity.id,
            contact_id=body.contact_id,
            version_id=body.source_version_id,
            external_id=body.external_id,
            fields=body.fields,
            expected_version=body.expected_version,
            request_id=UUID(request.state.request_id),
        )
        return serialize(contact)

    return write(db, identity.id, key, "POST:contact-discovery/fill-missing", body, change)


@router.get("/providers")
def providers(identity: CurrentIdentity, request: Request) -> list[dict[str, Any]]:
    _human(identity)
    config = request.app.state.settings
    return [
        {
            "id": "apollo",
            "name": "Apollo",
            "configured": bool(config.apollo_api_key.get_secret_value()),
            "setup_variable": "APOLLO_API_KEY",
            "documentation_url": "https://docs.apollo.io/reference/people-api-search",
            "description": "Search by company and title. Revealing a profile may use credits.",
        },
        {
            "id": "hunter",
            "name": "Hunter",
            "configured": bool(config.hunter_api_key.get_secret_value()),
            "setup_variable": "HUNTER_API_KEY",
            "documentation_url": "https://hunter.io/api-documentation/v2",
            "description": "Find published work emails. Credits and plan limits apply.",
        },
    ]


@router.get("/recent", response_model=list[DiscoveryRead])
def recent(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    _human(identity)
    rows = db.scalars(
        select(ArtifactVersion)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(
            Artifact.owner_id == identity.id,
            Artifact.archived_at.is_(None),
            ArtifactVersion.schema_key == SCHEMA,
        )
        .order_by(ArtifactVersion.created_at.desc())
        .limit(10)
    )
    return [ContactDiscoveryEvidence.read_snapshot(row) for row in rows]


async def _discover(
    request: Request,
    identity: CurrentIdentity,
    key: UUID,
    *,
    query: dict[str, Any],
    operation: Literal["search", "reveal"],
    external_id: str | None = None,
) -> dict[str, Any]:
    provider = query["provider"]
    config = request.app.state.settings
    provider_key = getattr(config, f"{provider}_api_key").get_secret_value()
    if not provider_key:
        raise HTTPException(409, f"Configure {provider.title()} in Connected apps before searching")
    payload = {**query, "credential_revision": hashlib.sha256(provider_key.encode()).hexdigest()}
    operation_key = f"POST:contact-discovery/{operation}"
    cache_key = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    claim_id, replay = _claim_connected(
        request, actor_id=identity.id, key=key, operation=operation_key, payload=payload
    )
    if replay is not None:
        return replay
    with Session(request.app.state.engine) as db:
        cached = ContactDiscoveryEvidence.cached(db, owner_id=identity.id, cache_key=cache_key)
    if cached is not None:
        return _finalize_connected(
            request,
            claim_id=claim_id,
            actor_id=identity.id,
            key=key,
            operation=operation_key,
            payload=payload,
            change=lambda db, record_id: cached,
        )
    adapter: ContactDiscoveryClient = request.app.state.contact_discovery
    try:
        if operation == "search":
            result = await adapter.search(
                provider, domain=query["domain"], title=query.get("title", ""), page=query["page"]
            )
        else:
            person = await adapter.reveal_apollo(external_id or "")
            result = ProspectPage(
                items=[person] if person else [],
                total=int(person is not None),
                page=1,
                has_more=False,
            )
    except ContactProviderError as exc:
        _fail_connected(request, claim_id, exc.code, unknown=exc.uncertain)
        raise HTTPException(
            502 if exc.uncertain else 409,
            {"code": exc.code, "message": str(exc), "outcome_unknown": exc.uncertain},
        ) from None
    except Exception:
        _fail_connected(request, claim_id, "outcome_unknown", unknown=True)
        raise HTTPException(
            502,
            {
                "code": "outcome_unknown",
                "message": "Outcome unknown. This request will not be repeated automatically.",
                "outcome_unknown": True,
            },
        ) from None
    return _finalize_connected(
        request,
        claim_id=claim_id,
        actor_id=identity.id,
        key=key,
        operation=operation_key,
        payload=payload,
        change=lambda db, record_id: ContactDiscoveryEvidence.snapshot(
            db,
            owner_id=identity.id,
            record_id=record_id,
            request_id=UUID(request.state.request_id),
            query=query,
            cache_key=cache_key,
            result=result,
        ),
    )


@router.post("/search", response_model=DiscoveryRead)
async def search(
    body: DiscoveryQuery, identity: CurrentIdentity, request: Request, key: WriteKey
) -> dict[str, Any]:
    _human(identity)
    if body.provider == "hunter" and body.title:
        raise HTTPException(422, "Title filtering is available for Apollo search")
    return await _discover(
        request,
        identity,
        key,
        query={**body.model_dump(mode="json"), "operation": "search"},
        operation="search",
    )


@router.post("/reveal", response_model=DiscoveryRead)
async def reveal(
    body: ProspectSelection, identity: CurrentIdentity, request: Request, key: WriteKey
) -> dict[str, Any]:
    _human(identity)
    with Session(request.app.state.engine) as db:
        version, prospect = ContactDiscoveryEvidence.prospect(
            db,
            owner_id=identity.id,
            version_id=body.source_version_id,
            external_id=body.external_id,
        )
        if prospect.provider != "apollo" or prospect.name_complete:
            raise HTTPException(422, "Choose an unrevealed Apollo search result")
        query = {
            "provider": "apollo",
            "operation": "reveal",
            "domain": prospect.domain or "",
            "external_id": prospect.external_id,
        }
    return await _discover(
        request, identity, key, query=query, operation="reveal", external_id=prospect.external_id
    )


@router.post("/import", response_model=ImportRead)
def import_contact(
    body: ProspectImport, identity: CurrentIdentity, db: Database, request: Request, key: WriteKey
) -> dict[str, Any]:
    _human(identity)

    def change(record_id: UUID) -> dict[str, Any]:
        contact, created = ContactDiscoveryEvidence.import_contact(
            db,
            owner_id=identity.id,
            version_id=body.source_version_id,
            external_id=body.external_id,
            record_id=record_id,
            request_id=UUID(request.state.request_id),
            company_id=body.company_id,
        )
        return {"contact": serialize(contact), "created": created}

    return write(db, identity.id, key, "POST:contact-discovery/import", body, change)
