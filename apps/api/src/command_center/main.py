from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from command_center.agents.mcp_server import AgentMCP
from command_center.api import agents, artifacts, browser, memory, workspace
from command_center.api.routes import api_router, health_router
from command_center.core.config import Settings
from command_center.db import browser as browser_models  # noqa: F401
from command_center.db.errors import RecordConflict, RecordNotFound
from command_center.db.idempotency import IdempotencyConflict
from command_center.db.session import create_database_engine
from command_center.integrations.clients import FirecrawlClient, SearxngClient


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    mcp = AgentMCP(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(config.database_url, config.database_pool_mode)
        app.state.engine = engine
        try:
            async with httpx.AsyncClient(
                timeout=config.connector_timeout_seconds, follow_redirects=False, trust_env=False
            ) as http:
                app.state.firecrawl = FirecrawlClient(
                    http, config.firecrawl_url, config.firecrawl_api_key.get_secret_value()
                )
                app.state.searxng = SearxngClient(http, config.searxng_url)
                async with mcp.manager.run():
                    yield
        finally:
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

    @app.middleware("http")
    async def request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(health_router)
    app.include_router(api_router)
    app.include_router(workspace.router)
    app.include_router(artifacts.router)
    app.include_router(agents.router)
    app.include_router(browser.router)
    app.include_router(memory.router)
    app.mount("/mcp", mcp)
    return app
