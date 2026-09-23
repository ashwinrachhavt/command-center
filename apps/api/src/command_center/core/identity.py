from dataclasses import dataclass
from functools import lru_cache
from hmac import compare_digest
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from command_center.core.auth import bearer
from command_center.db.models import Actor


@dataclass(frozen=True)
class Identity:
    id: UUID
    subject: str
    run_id: UUID | None = None
    client_id: UUID | None = None
    tool_grants: frozenset[str] = frozenset()

    @property
    def is_human(self) -> bool:
        return self.run_id is None and self.client_id is None


def require_workspace_tool(identity: Identity, *names: str) -> None:
    """An owned workspace read/write is broader than an arbitrary scoped run."""
    if identity.is_human or identity.client_id is not None:
        return
    if not identity.tool_grants.intersection({"catalog_execute", *names}):
        raise HTTPException(403, "This workspace operation requires an explicit tool grant")


@lru_cache(maxsize=8)
def jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        issuer.rstrip("/") + "/.well-known/jwks.json", cache_keys=True, lifespan=300, timeout=5
    )


def authenticate(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Identity:
    if credentials is None:
        raise HTTPException(
            401, "Sign in to access your workspace", headers={"WWW-Authenticate": "Bearer"}
        )
    settings = request.app.state.settings
    token = credentials.credentials
    if token.startswith(("cc_local.", "cc_client.")):
        from command_center.core.local_credentials import authenticate_client_api

        actor_id, client_id = authenticate_client_api(request, token)
        request.state.mcp_client_id = client_id
        return Identity(id=actor_id, subject=f"mcp-client:{client_id}", client_id=client_id)
    if token.startswith("cc_agent."):
        from command_center.core.capabilities import authenticate_run

        actor_id, run_id = authenticate_run(request, token)
        request.state.agent_run_id = run_id
        return Identity(
            id=actor_id,
            subject=f"agent:{run_id}",
            run_id=run_id,
            tool_grants=frozenset(request.state.agent_tools),
        )
    if settings.auth_mode == "local":
        if not compare_digest(token.encode(), settings.api_token.get_secret_value().encode()):
            raise HTTPException(401, "Invalid local credential")
        subject = "local:development"
    else:
        if not settings.clerk_issuer:
            raise HTTPException(503, "Clerk authentication is not configured")
        try:
            key = jwks_client(settings.clerk_issuer).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=settings.clerk_issuer,
                options={
                    "verify_aud": False,
                    "require": ["exp", "iat", "nbf", "sub", "iss", "sid"],
                },
                leeway=5,
            )
            if (
                claims.get("azp") not in settings.clerk_authorized_parties
                or claims.get("sts") == "pending"
            ):
                raise jwt.InvalidTokenError("Invalid session origin or status")
            if not isinstance(claims["sub"], str) or not claims["sub"].startswith("user_"):
                raise jwt.InvalidTokenError("Invalid subject")
            subject = settings.clerk_issuer + "|" + claims["sub"]
        except jwt.PyJWTError as exc:
            raise HTTPException(
                401, "Session is invalid or expired", headers={"WWW-Authenticate": "Bearer"}
            ) from exc
    actor_id = uuid5(NAMESPACE_URL, "command-center:identity:" + subject)
    with Session(request.app.state.engine) as session, session.begin():
        session.execute(
            insert(Actor)
            .values(
                id=actor_id,
                auth_subject=subject,
                kind="human",
                display_name="My workspace",
                active=True,
            )
            .on_conflict_do_nothing(index_elements=[Actor.id])
        )
        actor = session.get(Actor, actor_id)
        if actor is None or not actor.active:
            raise HTTPException(403, "This workspace is inactive")
    return Identity(id=actor_id, subject=subject)


CurrentIdentity = Annotated[Identity, Depends(authenticate)]
