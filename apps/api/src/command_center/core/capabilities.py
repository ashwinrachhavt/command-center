"""Server-enforced capabilities for one leased agent run. Never given to the model."""

import re
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now
from command_center.db.models import Actor

CAPABILITIES = {
    "workspace_summary": [("GET", r"/api/v1/dashboard"), ("GET", r"/api/v1/companies")],
    "research_search": [("POST", r"/api/v1/research/search")],
    "capture_lead": [("POST", r"/api/v1/leads/capture")],
    "enrich_lead": [("POST", r"/api/v1/opportunities/[0-9a-f-]+/enrich")],
    "lead_evidence": [("GET", r"/api/v1/opportunities/[0-9a-f-]+/research")],
    "document_read": [("GET", r"/api/v1/documents/versions/[0-9a-f-]+/text")],
    "propose_profile_fact": [("POST", r"/api/v1/profile/facts")],
    "approved_profile": [("GET", r"/api/v1/profile/facts/approved")],
    "application_context": [("GET", r"/api/v1/browser/preparations/[0-9a-f-]+/context")],
    "suggest_application_answers": [
        ("POST", r"/api/v1/browser/preparations/[0-9a-f-]+/suggestions")
    ],
    "create_task": [("POST", r"/api/v1/tasks")],
    "draft_artifact": [("POST", r"/api/v1/artifacts")],
    "memory_read": [("GET", r"/api/v1/memories/retrieve")],
    "memory_append": [("POST", r"/api/v1/memories")],
    "connected_accounts": [("GET", r"/api/v1/integrations/composio/accounts")],
    "gmail_search": [("POST", r"/api/v1/gmail/search")],
    "propose_connected_action": [("POST", r"/api/v1/reviewed-actions")],
    "reviewed_action": [("GET", r"/api/v1/reviewed-actions/[0-9a-f-]+")],
    "capture_research_source": [("POST", r"/api/v1/tasks/[0-9a-f-]+/research-sources")],
    "run_research_script": [("POST", r"/api/v1/tasks/[0-9a-f-]+/research-executions")],
    "research_execution": [("GET", r"/api/v1/research-executions/[0-9a-f-]+")],
}


def issue_run_token(
    settings: Settings,
    run_id: UUID,
    lease_id: UUID,
    *,
    audience: str = "command-center-api",
    role: str | None = None,
) -> str:
    now = utc_now()
    return "cc_agent." + jwt.encode(
        {
            "iss": "command-center",
            "aud": audience,
            "sub": str(run_id),
            "lease": str(lease_id),
            "role": role,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=20),
        },
        settings.api_token.get_secret_value(),
        algorithm="HS256",
    )


def role_profile(snapshot: dict[str, Any], role: str | None) -> dict[str, Any]:
    """Only the host-issued role can narrow a pinned root capability."""
    root: dict[str, Any] = snapshot["profile"]
    if role is None:
        return root
    specialists = root.get("specialists", {})
    if not isinstance(role, str) or role not in specialists:
        raise HTTPException(403, "This specialist is not granted to the agent run")
    child: dict[str, Any] = specialists[role]
    if set(child["tools"]) - set(root["tools"]):
        raise HTTPException(403, "Specialist capabilities exceed the root grant")
    return child


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
        capability_expires_at = int(claims["exp"])
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
        role = claims.get("role")
        granted = role_profile(run.config_snapshot, role)["tools"]
        request.state.agent_role = role
        request.state.agent_lease_id = lease_id
        request.state.agent_capability_expires_at = capability_expires_at
        allowed = any(
            method == request.method and re.fullmatch(path, request.url.path)
            for tool in granted
            for method, path in CAPABILITIES.get(tool, [])
        )
        if check_scope and not allowed:
            raise HTTPException(403, "This tool is not granted to the agent run")
        return run.owner_id, run.id


def fence_agent_write(request: Request, session: Session) -> None:
    """Hold the authenticated lease through a write transaction after external I/O."""
    run_id = getattr(request.state, "agent_run_id", None)
    if run_id is None:
        return
    run = session.scalar(
        select(AgentRun).where(AgentRun.id == run_id).with_for_update(key_share=True)
    )
    now = utc_now()
    if (
        run is None
        or run.state != "running"
        or run.lease_id != getattr(request.state, "agent_lease_id", None)
        or run.lease_expires_at is None
        or run.lease_expires_at <= now
        or getattr(request.state, "agent_capability_expires_at", 0) <= now.timestamp()
    ):
        raise HTTPException(401, "Agent lease expired or cancelled")
