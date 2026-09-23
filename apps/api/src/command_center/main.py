from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from command_center.agents.mcp_server import AgentMCP
from command_center.agents.spending import FixedCostReservationHandle, connected_tool_reserver
from command_center.api import (
    agent_events,
    agent_questions,
    agents,
    application_materials,
    application_preparations,
    applications,
    artifacts,
    browser,
    contact_discovery,
    conversations,
    correspondence,
    document_text,
    documents,
    leads,
    mcp_clients,
    memory,
    pdf_exports,
    profile_facts,
    record_work,
    research_executions,
    reviewed_actions,
    spending,
    work_queue,
    workspace,
    writing,
)
from command_center.api.routes import api_router, health_router
from command_center.core.config import Settings
from command_center.db import browser as browser_models  # noqa: F401
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.idempotency import IdempotencyConflict
from command_center.db.session import create_database_engine
from command_center.db.spending import SpendingDenied
from command_center.integrations.clients import FirecrawlClient, SearxngClient
from command_center.integrations.composio_actions import ComposioActionClient
from command_center.integrations.contact_discovery import ContactDiscoveryClient


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    mcp = AgentMCP(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(config.database_url, config.database_pool_mode)
        app.state.engine = engine
        action_client = (
            ComposioActionClient(
                api_key=config.composio_api_key.get_secret_value(),
                timeout_seconds=int(config.composio_action_timeout_seconds),
            )
            if config.composio_api_key.get_secret_value()
            else None
        )
        app.state.composio_actions = action_client

        def reserve_action_budget(
            owner_id: UUID,
            task_id: UUID | None,
            opportunity_id: UUID | None,
            request_scope_id: UUID | None = None,
            agent_run_id: UUID | None = None,
            agent_lease_id: UUID | None = None,
        ) -> Callable[[str, UUID], FixedCostReservationHandle]:
            if agent_run_id is not None:
                return connected_tool_reserver(
                    engine, owner_id=owner_id, run_id=agent_run_id, lease_id=agent_lease_id
                )
            return connected_tool_reserver(
                engine,
                owner_id=owner_id,
                task_id=task_id,
                opportunity_id=opportunity_id,
                request_scope_id=(
                    request_scope_id if task_id is None and opportunity_id is None else None
                ),
            )

        app.state.reviewed_action_budget = reserve_action_budget
        try:
            async with httpx.AsyncClient(
                timeout=config.connector_timeout_seconds, follow_redirects=False, trust_env=False
            ) as http:
                app.state.firecrawl = FirecrawlClient(
                    http, config.firecrawl_url, config.firecrawl_api_key.get_secret_value()
                )
                app.state.searxng = SearxngClient(http, config.searxng_url)
                app.state.contact_discovery = ContactDiscoveryClient(
                    http,
                    apollo_key=config.apollo_api_key.get_secret_value(),
                    hunter_key=config.hunter_api_key.get_secret_value(),
                )
                async with mcp.http_app.lifespan(mcp.http_app):
                    yield
        finally:
            if action_client is not None:
                action_client.close()
            engine.dispose()

    app = FastAPI(title="Command Center API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)

    @app.exception_handler(RecordNotFound)
    async def not_found(request: Request, exc: RecordNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(RecordConflict)
    async def record_conflict(request: Request, exc: RecordConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": (
                    "This change conflicts with an existing or linked record. "
                    "Refresh and check your values."
                )
            },
        )

    @app.exception_handler(StaleDataError)
    @app.exception_handler(IdempotencyConflict)
    async def conflict(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": (
                    "This request conflicts with an earlier change. Refresh before trying again."
                )
            },
        )

    @app.exception_handler(ValueError)
    async def invalid_change(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "The requested change is not valid for this record."},
        )

    @app.exception_handler(SpendingDenied)
    async def spending_denied(request: Request, exc: SpendingDenied) -> JSONResponse:
        error = spending.denied(exc)
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    @app.middleware("http")
    async def request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(mcp_clients.router)
    app.include_router(health_router)
    app.include_router(api_router)
    app.include_router(workspace.router)
    app.include_router(work_queue.router)
    app.include_router(artifacts.router)
    app.include_router(agents.router)
    app.include_router(agent_questions.router)
    app.include_router(agent_events.router)
    app.include_router(conversations.router)
    app.include_router(correspondence.router)
    app.include_router(contact_discovery.router)
    app.include_router(record_work.router)
    app.include_router(leads.router)
    app.include_router(documents.router)
    app.include_router(document_text.router)
    app.include_router(profile_facts.router)
    app.include_router(browser.router)
    app.include_router(application_preparations.router)
    app.include_router(applications.router)
    app.include_router(application_materials.router)
    app.include_router(memory.router)
    app.include_router(reviewed_actions.router)
    app.include_router(writing.router)
    app.include_router(research_executions.router)
    app.include_router(pdf_exports.router)
    app.include_router(spending.router)
    mcp.openapi = app.openapi()
    app.mount("/mcp", mcp)
    return app
