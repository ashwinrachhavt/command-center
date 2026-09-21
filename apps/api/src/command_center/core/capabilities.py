"""Server-enforced capabilities for one leased agent run. Never given to the model."""

import re
from datetime import timedelta
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.models import Actor

CAPABILITIES = {
    "workspace_summary": [("GET", r"/api/v1/dashboard"), ("GET", r"/api/v1/companies")],
    "research_search": [("POST", r"/api/v1/research/search")],
    "create_task": [("POST", r"/api/v1/tasks")],
    "draft_artifact": [("POST", r"/api/v1/artifacts")],
    "memory_read": [("GET", r"/api/v1/memories")],
    "memory_append": [("POST", r"/api/v1/memories")],
}


def issue_run_token(
    settings: Settings, run_id: UUID, lease_id: UUID, *, audience: str = "command-center-api"
) -> str:
    now = utc_now()
    return "cc_agent." + jwt.encode(
        {
            "iss": "command-center",
            "aud": audience,
            "sub": str(run_id),
            "lease": str(lease_id),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=20),
        },
        settings.api_token.get_secret_value(),
        algorithm="HS256",
    )


def authenticate_run(
    request: Request, token: str, *, audience: str = "command-center-api", check_scope: bool = True
) -> tuple[UUID, UUID]:
    settings: Settings = request.app.state.settings
    try:
        claims = jwt.decode(
            token.removeprefix("cc_agent."),
            settings.api_token.get_secret_value(),
            algorithms=["HS256"],
            issuer="command-center",
            audience=audience,
            options={"require": ["exp", "iat", "nbf", "sub", "lease"]},
        )
        run_id, lease_id = UUID(claims["sub"]), UUID(claims["lease"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(401, "Invalid agent capability") from exc
    with Session(request.app.state.engine) as db:
        run = db.get(AgentRun, run_id)
        if (
            not run
            or run.state != "running"
            or run.lease_id != lease_id
            or not run.lease_expires_at
            or run.lease_expires_at <= utc_now()
        ):
            raise HTTPException(401, "Agent lease expired or cancelled")
        actor = db.get(Actor, run.owner_id)
        if not actor or not actor.active:
            raise HTTPException(403, "Workspace is inactive")
        granted = run.config_snapshot["profile"]["tools"]
        allowed = any(
            method == request.method and re.fullmatch(path, request.url.path)
            for tool in granted
            for method, path in CAPABILITIES.get(tool, [])
        )
        if check_scope and not allowed:
            raise HTTPException(403, "This tool is not granted to the agent run")
        return run.owner_id, run.id
