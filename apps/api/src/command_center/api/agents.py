import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from command_center.agents.config import load_profiles
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

router = APIRouter(prefix="/api/v1", tags=["agents"])


class RunCreate(s.Contract):
    profile: str = Field(max_length=100)
    prompt: str = Field(min_length=1, max_length=20000)


class RunRead(s.RecordRead):
    title: str
    prompt: str
    profile: str
    state: str
    output: str | None
    error_code: str | None
    completed_at: Any


@router.get("/agents/profiles")
def profiles(identity: CurrentIdentity, request: Request) -> list[dict[str, Any]]:
    configured, revision = load_profiles(
        request.app.state.settings.agent_config, request.app.state.settings.agent_skills_dir
    )
    return [
        {
            "id": key,
            "name": p.name,
            "description": p.description,
            "model": p.model,
            "tools": p.tools + [t.slug for t in p.composio_tools],
            "revision": revision,
            "skills": p.skills,
        }
        for key, p in configured.items()
    ]


@router.get("/agent-runs", response_model=s.Page[RunRead])
def runs(
    identity: CurrentIdentity, db: Database, limit: Limit = 30, offset: Offset = 0
) -> dict[str, Any]:
    return listing(AgentRun, db, identity.id, "", limit, offset)


@router.get("/agent-runs/{record_id}", response_model=RunRead)
def run_detail(record_id: UUID, identity: CurrentIdentity, db: Database) -> AgentRun:
    return owned(db, AgentRun, record_id, identity.id)


@router.get("/agent-runs/{record_id}/steps")
def run_steps(record_id: UUID, identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    return owned(db, AgentRun, record_id, identity.id).tool_steps()


@router.post("/agent-runs", response_model=RunRead, status_code=201)
def queue_run(
    body: RunCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(record_id: UUID) -> dict[str, Any]:
        settings = request.app.state.settings
        if not settings.openai_api_key.get_secret_value():
            raise HTTPException(503, "Add OPENAI_API_KEY to the API environment to run an agent")
        configured, revision = load_profiles(settings.agent_config, settings.agent_skills_dir)
        if body.profile not in configured:
            raise HTTPException(422, "Unknown agent profile")
        profile = configured[body.profile]
        if profile.composio_tools and not settings.composio_api_key.get_secret_value():
            raise HTTPException(503, "This profile requires Composio configuration")
        run = AgentRun.enqueue(
            db,
            record_id=record_id,
            owner_id=identity.id,
            prompt=body.prompt,
            profile=body.profile,
            configuration=profile.model_dump(mode="json"),
            revision=revision,
            request_id=UUID(request.state.request_id),
        )
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
        connection = client.connected_accounts.initiate(
            user_id=str(identity.id),
            auth_config_id=config_id,
            callback_url=settings.web_origin + "/settings?connected=1",
        )
        return {"redirect_url": str(connection.redirect_url)}
    except Exception as exc:
        raise HTTPException(502, "Composio could not start the connection") from exc
