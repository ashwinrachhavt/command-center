"""Local bearer credentials have a distinct audience and explicit API policy."""

from datetime import timedelta
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.db.base import utc_now
from command_center.db.mcp_clients import MCPClientCredential


def issue_client_api_token(settings: Settings, client_id: UUID) -> str:
    now = utc_now()
    return "cc_client." + jwt.encode(
        {
            "iss": "command-center",
            "aud": "command-center-local-api",
            "sub": str(client_id),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.api_token.get_secret_value(),
        algorithm="HS256",
    )


def authenticate_client_api(request: Request, token: str) -> tuple[UUID, UUID]:
    from command_center.agents.mcp_policy import local_api_allowed

    try:
        if not token.startswith("cc_client."):
            raise ValueError("MCP credentials cannot be used as API credentials")
        claims = jwt.decode(
            token.removeprefix("cc_client."),
            request.app.state.settings.api_token.get_secret_value(),
            algorithms=["HS256"],
            issuer="command-center",
            audience="command-center-local-api",
            options={"require": ["exp", "iat", "nbf", "sub"]},
        )
        with Session(request.app.state.engine) as db:
            credential = MCPClientCredential.active(db, UUID(claims["sub"]))
            actor_id, client_id = credential.owner_id, credential.id
    except (ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(401, "Invalid or revoked local MCP capability") from exc
    if not local_api_allowed(request.method, request.url.path):
        raise HTTPException(403, "This action requires a human session or a scoped runtime")
    return actor_id, client_id
