"""Human-session provisioning. Tokens are returned once, never listed or audited."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from command_center.api.workspace import Database, owned
from command_center.core.identity import CurrentIdentity, Identity
from command_center.db.mcp_clients import MCPClientCredential

router = APIRouter(prefix="/api/v1/mcp-clients", tags=["local MCP"])


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default=90, ge=1, le=365)


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class ClientCreated(ClientRead):
    token: str


def require_human(identity: Identity) -> None:
    if not identity.is_human:
        raise HTTPException(403, "Manage local clients from an authenticated human session")


@router.get("", response_model=list[ClientRead])
def clients(identity: CurrentIdentity, db: Database) -> list[MCPClientCredential]:
    require_human(identity)
    return list(
        db.scalars(
            select(MCPClientCredential)
            .where(MCPClientCredential.owner_id == identity.id)
            .order_by(MCPClientCredential.created_at.desc())
            .limit(100)
        )
    )


@router.post("", response_model=ClientCreated, status_code=201)
def create_client(
    body: ClientCreate, request: Request, identity: CurrentIdentity, db: Database
) -> ClientCreated:
    require_human(identity)
    record, token = MCPClientCredential.provision(
        db, identity.id, body.name, body.expires_in_days, UUID(request.state.request_id)
    )
    return ClientCreated(**ClientRead.model_validate(record).model_dump(), token=token)


@router.post("/{client_id}/revoke", response_model=ClientRead)
def revoke_client(
    client_id: UUID, request: Request, identity: CurrentIdentity, db: Database
) -> MCPClientCredential:
    require_human(identity)
    record = owned(db, MCPClientCredential, client_id, identity.id, lock=True)
    record.revoke(db, UUID(request.state.request_id))
    return record
