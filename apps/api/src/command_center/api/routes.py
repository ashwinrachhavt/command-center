import asyncio

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from command_center.core.auth import require_api_token
from command_center.db.session import database_is_ready
from command_center.integrations.clients import ConnectionStatus

health_router = APIRouter(tags=["health"])
api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_token)])


class HealthStatus(BaseModel):
    status: str


class SystemStatus(BaseModel):
    database: str
    connections: list[ConnectionStatus]


@health_router.get("/health/live", response_model=HealthStatus)
def live() -> HealthStatus:
    return HealthStatus(status="ok")


@health_router.get("/health/ready", response_model=HealthStatus)
def ready(request: Request, response: Response) -> HealthStatus:
    is_ready = database_is_ready(request.app.state.engine)
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthStatus(status="ready" if is_ready else "not_ready")


@api_router.get("/system/status", response_model=SystemStatus, tags=["system"])
async def system_status(request: Request) -> SystemStatus:
    db_ready, firecrawl, searxng = await asyncio.gather(
        run_in_threadpool(database_is_ready, request.app.state.engine),
        request.app.state.firecrawl.status(),
        request.app.state.searxng.status(),
    )
    return SystemStatus(
        database="ready" if db_ready else "not_ready", connections=[firecrawl, searxng]
    )
