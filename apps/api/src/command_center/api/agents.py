import asyncio
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select

from command_center.agents.config import AgentProfile, ModelProvider, load_profiles
from command_center.agents.models import missing_profile_credentials
from command_center.api import schemas as s
from command_center.api.workspace import (
    Database,
    Limit,
    Offset,
    WriteKey,
    check_version,
    listing,
    owned,
    serialize,
    write,
)
from command_center.core.identity import CurrentIdentity
from command_center.db.agents import AgentRun
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.models import AuditEvent
from command_center.integrations.model_catalog import (
    DiscoveredModel,
    ModelCatalogUnavailable,
    discover_models,
)

router = APIRouter(prefix="/api/v1", tags=["agents"])


class RunCreate(s.Contract):
    continue_run_id: UUID | None = None
    profile: str = Field(max_length=100)
    prompt: str = Field(min_length=1, max_length=20000)
    provider: Literal["openai", "gemini", "mistral", "cohere"] | None = None
    model: str | None = Field(default=None, max_length=100)


class RunRead(s.RecordRead):
    title: str
    prompt: str
    profile: str
    state: str
    output: str | None
    error_code: str | None
    completed_at: Any
    session_id: UUID | None
    input_sequence: int
    consumed_sequence: int


class RunStepRead(s.Contract):
    id: str
    name: str
    role: str = "assistant"
    specialist: str | None = None
    summary: str | None = None
    state: Literal["input-available", "output-available", "output-error"]
    output: str | None


class RunArtifactRead(s.Contract):
    id: UUID
    title: str
    kind: str
    version_id: UUID
    version: int


def missing_profile_configuration(request: Request, profile: AgentProfile) -> list[str]:
    settings = request.app.state.settings
    missing = list(missing_profile_credentials(settings, profile))
    if profile.composio_tools and not settings.composio_api_key.get_secret_value():
        missing.append("COMPOSIO_API_KEY")
    return missing


def available_profile(
    request: Request,
    slug: str,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[AgentProfile, str]:
    """Load one runnable profile and enforce shared provider prerequisites."""
    settings = request.app.state.settings
    configured, revision = load_profiles(settings.agent_config, settings.agent_skills_dir)
    if slug not in configured:
        raise HTTPException(422, "Unknown agent profile")
    profile = configured[slug]
    if provider is not None or model is not None:
        updates: dict[str, Any] = {}
        if provider is not None:
            updates["provider"] = provider
        if model is not None:
            updates["model"] = model
        profile = profile.model_copy(update=updates)
    missing = missing_profile_configuration(request, profile)
    if missing:
        raise HTTPException(503, "Add " + ", ".join(missing) + " to run this profile")
    from command_center.agents.models import cohere_tool_model

    if any(
        selected.provider == "cohere" and not cohere_tool_model(selected.model)
        for selected in [profile, *profile.specialists.values()]
    ):
        raise HTTPException(
            422,
            "This Cohere model does not support agent tools. "
            "Choose a Command R or Command A model.",
        )
    return profile, revision


@router.get("/agents/models", response_model=list[DiscoveredModel])
async def models(
    provider: ModelProvider, identity: CurrentIdentity, request: Request
) -> list[DiscoveredModel]:
    try:
        async with httpx.AsyncClient() as http:
            return await discover_models(request.app.state.settings, provider, http)
    except ModelCatalogUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.get("/agents/profiles")
def profiles(identity: CurrentIdentity, request: Request) -> list[dict[str, Any]]:
    configured, revision = load_profiles(
        request.app.state.settings.agent_config, request.app.state.settings.agent_skills_dir
    )
    result = []
    for key, p in configured.items():
        missing = missing_profile_configuration(request, p)
        result.append(
            {
                "id": key,
                "name": p.name,
                "description": p.description,
                "provider": p.provider,
                "model": p.model,
                "ready": not missing,
                "missing_credentials": missing,
                "tools": p.tools + [t.slug for t in p.composio_tools],
                "revision": revision,
                "skills": p.skills,
            }
        )
    return result


@router.get("/agent-runs", response_model=s.Page[RunRead])
def runs(
    identity: CurrentIdentity, db: Database, limit: Limit = 30, offset: Offset = 0
) -> dict[str, Any]:
    return listing(AgentRun, db, identity.id, "", limit, offset)


@router.get("/agent-runs/{record_id}", response_model=RunRead)
def run_detail(record_id: UUID, identity: CurrentIdentity, db: Database) -> AgentRun:
    return owned(db, AgentRun, record_id, identity.id)


@router.get("/agent-runs/{record_id}/steps", response_model=list[RunStepRead])
def run_steps(record_id: UUID, identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    return owned(db, AgentRun, record_id, identity.id).tool_steps()


@router.get("/agent-runs/{record_id}/artifacts", response_model=s.Page[RunArtifactRead])
def run_artifacts(
    record_id: UUID, identity: CurrentIdentity, db: Database, limit: Limit = 30, offset: Offset = 0
) -> dict[str, Any]:
    """Link exact immutable output versions through the existing run audit provenance."""
    owned(db, AgentRun, record_id, identity.id)
    statement = (
        select(
            Artifact.id,
            Artifact.title,
            Artifact.kind,
            ArtifactVersion.id.label("version_id"),
            ArtifactVersion.version,
        )
        .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
        .join(
            AuditEvent,
            (AuditEvent.subject_id == Artifact.id)
            & (AuditEvent.details["version"].as_integer() == ArtifactVersion.version),
        )
        .where(
            Artifact.owner_id == identity.id,
            AuditEvent.actor_id == identity.id,
            AuditEvent.subject_type == "artifacts",
            AuditEvent.action == "artifact.version_created",
            AuditEvent.details["agent_run_id"].as_string() == str(record_id),
        )
    )
    return {
        "items": [
            dict(row)
            for row in db.execute(
                statement.order_by(ArtifactVersion.created_at.desc(), ArtifactVersion.id)
                .limit(limit)
                .offset(offset)
            ).mappings()
        ],
        "total": db.scalar(select(func.count()).select_from(statement.subquery())) or 0,
        "limit": limit,
        "offset": offset,
    }


@router.post("/agent-runs", response_model=RunRead, status_code=201)
def queue_run(
    body: RunCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        from command_center.db.conversations import AgentSession
        from command_center.db.spending import ensure_default_spending_policy

        ensure_default_spending_policy(db, identity.id)
        profile, revision = available_profile(
            request, body.profile, provider=body.provider, model=body.model
        )
        request_id = UUID(request.state.request_id)
        conversation = (
            AgentSession.for_run(
                db,
                run=owned(db, AgentRun, body.continue_run_id, identity.id),
                request_id=request_id,
            )
            if body.continue_run_id
            else AgentSession.open_chat(
                db,
                record_id=record_id,
                owner_id=identity.id,
                title=body.prompt,
                request_id=request_id,
            )
        )
        message = conversation.receive(
            content=body.prompt,
            profile=body.profile,
            configuration=profile.model_dump(mode="json"),
            revision=revision,
            request_id=request_id,
        )
        run = db.get(AgentRun, message.run_id)
        assert run is not None
        run.title = conversation.title
        db.flush()
        return serialize(run)

    return write(db, identity.id, key, "POST:agent-runs", body, change)


@router.post("/agent-runs/{record_id}/cancel", response_model=RunRead)
def cancel_run(
    record_id: UUID, body: s.Revision, identity: CurrentIdentity, db: Database, key: WriteKey
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        run = owned(db, AgentRun, record_id, identity.id, lock=True)
        check_version(run, body.expected_version)
        run.finish("cancelled")
        db.flush()
        return serialize(run)

    return write(db, identity.id, key, f"CANCEL:agent-runs:{record_id}", body, change)


@router.get("/integrations")
async def integrations(identity: CurrentIdentity, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    providers = await asyncio.gather(
        request.app.state.firecrawl.status(), request.app.state.searxng.status()
    )
    return {
        "services": [p.model_dump() for p in providers],
        "openai_configured": bool(settings.openai_api_key.get_secret_value()),
        "model_providers": {
            "openai": bool(settings.openai_api_key.get_secret_value()),
            "gemini": bool(settings.gemini_api_key.get_secret_value()),
            "mistral": bool(settings.mistral_api_key.get_secret_value()),
            "cohere": bool(settings.cohere_api_key.get_secret_value()),
        },
        "composio_configured": bool(settings.composio_api_key.get_secret_value()),
        "auth": settings.auth_mode,
        "composio_toolkits": sorted(settings.composio_auth_configs),
    }


class ConnectRequest(s.Contract):
    toolkit: str = Field(min_length=1, max_length=100)


class ResearchRequest(s.Contract):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)


@router.post("/research/search")
async def research_search(
    body: ResearchRequest, identity: CurrentIdentity, request: Request
) -> list[dict[str, Any]]:
    from command_center.integrations.clients import ProviderError

    try:
        results = await request.app.state.searxng.search(body.query, limit=body.limit)
        return [
            {key: str(result.get(key, ""))[:3000] for key in ["title", "url", "content"]}
            for result in results
        ]
    except ProviderError as exc:
        raise HTTPException(503, "Web research is temporarily unavailable") from exc


@router.post("/integrations/composio/connect")
def connect_composio(
    body: ConnectRequest, identity: CurrentIdentity, request: Request
) -> dict[str, str]:
    from composio import Composio

    settings = request.app.state.settings
    config_id = settings.composio_auth_configs.get(body.toolkit)
    if not config_id or not settings.composio_api_key.get_secret_value():
        raise HTTPException(422, "Configure this toolkit in CC_COMPOSIO_AUTH_CONFIGS first")
    try:
        client = Composio(api_key=settings.composio_api_key.get_secret_value())
        connection = client.connected_accounts.link(
            user_id=str(identity.id),
            auth_config_id=config_id,
            callback_url=(
                settings.web_origin
                + "/agent-settings?tab=connectors&connected=1&toolkit="
                + body.toolkit
            ),
            allow_multiple=True,
        )
        redirect_url = str(connection.redirect_url)
        parsed = urlsplit(redirect_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid provider connection URL")
        return {"redirect_url": redirect_url}
    except Exception as exc:
        raise HTTPException(502, "Composio could not start the connection") from exc
