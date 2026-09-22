from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

from command_center.api import schemas as s
from command_center.api.browser_contracts import (
    ClaimResult,
    FillCreate,
    FillResult,
    PairCreate,
    PairCredentials,
    PairExchange,
    PendingCommand,
    SnapshotCreate,
)
from command_center.api.workspace import Database, WriteKey, serialize, write
from command_center.core.auth import bearer
from command_center.core.identity import CurrentIdentity
from command_center.db.base import utc_now
from command_center.db.browser import BrowserCommand, BrowserDevice, BrowserSnapshot, digest

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])


def device_identity(
    db: Database, credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> BrowserDevice:
    if credential is None:
        raise HTTPException(401, "Pair this browser first")
    device = db.scalar(
        select(BrowserDevice).where(
            BrowserDevice.token_digest == digest(credential.credentials),
            BrowserDevice.revoked_at.is_(None),
        )
    )
    if device is None:
        raise HTTPException(401, "Browser credential is invalid or revoked")
    device.last_seen_at = utc_now()
    return device


Device = Annotated[BrowserDevice, Depends(device_identity)]


def device_data(device: BrowserDevice) -> dict[str, Any]:
    return {
        "id": str(device.id),
        "name": device.name,
        "paired_at": device.paired_at,
        "last_seen_at": device.last_seen_at,
        "revoked_at": device.revoked_at,
    }


@router.get("/devices")
def devices(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    return [
        device_data(d)
        for d in db.scalars(
            select(BrowserDevice)
            .where(BrowserDevice.owner_id == identity.id)
            .order_by(BrowserDevice.created_at.desc())
            .limit(100)
        )
    ]


@router.post("/pairings", status_code=201)
def pair(
    body: PairCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(device_id: UUID) -> dict[str, Any]:
        device, code = BrowserDevice.pair(
            db,
            device_id=device_id,
            owner_id=identity.id,
            name=body.name,
            request_id=UUID(request.state.request_id),
        )
        return {
            "device_id": str(device_id),
            "code": code,
            "expires_at": device.pairing_expires_at.isoformat(),
        }

    return write(db, identity.id, key, "POST:browser-pairing", body, change)


@router.post("/pairings/exchange", response_model=PairCredentials)
def exchange(body: PairExchange, db: Database, request: Request) -> dict[str, str]:
    try:
        device, token = BrowserDevice.redeem(
            db, body.code, request_id=UUID(request.state.request_id)
        )
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return {"device_id": str(device.id), "token": token}


@router.post("/devices/{device_id}/revoke")
def revoke(
    device_id: UUID, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(_: UUID) -> dict[str, Any]:
        device = db.scalar(
            select(BrowserDevice)
            .where(BrowserDevice.id == device_id, BrowserDevice.owner_id == identity.id)
            .with_for_update()
        )
        if device is None:
            raise HTTPException(404, "Browser not found")
        device.revoke(request_id=UUID(request.state.request_id))
        return {"revoked": True}

    return write(db, identity.id, key, f"REVOKE:browser:{device_id}", s.Contract(), change)


@router.post("/snapshots", status_code=201)
def capture(body: SnapshotCreate, device: Device, db: Database, request: Request) -> dict[str, Any]:
    snapshot = BrowserSnapshot.capture(
        db,
        device,
        snapshot_id=body.id,
        page_url=str(body.page_url),
        title=body.title,
        fields=[field.model_dump() for field in body.fields],
        request_id=UUID(request.state.request_id),
    )
    db.flush()
    return serialize(snapshot)


@router.get("/snapshots")
def snapshots(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    return [
        serialize(row)
        for row in db.scalars(
            select(BrowserSnapshot)
            .where(BrowserSnapshot.owner_id == identity.id)
            .order_by(BrowserSnapshot.created_at.desc())
            .limit(20)
        )
    ]


@router.post("/commands", status_code=201)
def propose_fill(
    body: FillCreate, identity: CurrentIdentity, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(command_id: UUID) -> dict[str, Any]:
        snapshot = db.scalar(
            select(BrowserSnapshot).where(
                BrowserSnapshot.id == body.snapshot_id, BrowserSnapshot.owner_id == identity.id
            )
        )
        if snapshot is None:
            raise HTTPException(404, "Form snapshot not found")
        command = snapshot.propose_fill(
            command_id=command_id,
            fields=body.fields,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return serialize(command)

    return write(db, identity.id, key, "POST:browser-command", body, change)


@router.get("/commands")
def commands(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    return [
        serialize(row)
        for row in db.scalars(
            select(BrowserCommand)
            .where(BrowserCommand.owner_id == identity.id)
            .order_by(BrowserCommand.created_at.desc())
            .limit(30)
        )
    ]


@router.get("/device/commands", response_model=list[PendingCommand])
def pending_commands(device: Device, db: Database, request: Request) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(BrowserCommand)
        .where(
            BrowserCommand.device_id == device.id, BrowserCommand.state.in_(["pending", "claimed"])
        )
        .order_by(BrowserCommand.created_at)
        .with_for_update()
    ).all()
    results = []
    for command in rows:
        command.expire(request_id=UUID(request.state.request_id))
        if command.state == "pending":
            snapshot = db.get(BrowserSnapshot, command.snapshot_id)
            assert snapshot
            results.append(
                {
                    **serialize(command),
                    "page_url": snapshot.page_url,
                    "form_fields": snapshot.fields,
                }
            )
    return results


@router.post("/device/commands/{command_id}/claim", response_model=ClaimResult)
def claim(command_id: UUID, device: Device, db: Database, request: Request) -> dict[str, str]:
    command = db.scalar(
        select(BrowserCommand)
        .where(BrowserCommand.id == command_id, BrowserCommand.device_id == device.id)
        .with_for_update()
    )
    if command is None:
        raise HTTPException(404, "Command not found")
    command.claim(request_id=UUID(request.state.request_id))
    return {"state": "claimed"}


@router.post("/device/commands/{command_id}/result", response_model=FillResult)
def result(
    command_id: UUID, body: FillResult, device: Device, db: Database, request: Request
) -> dict[str, str]:
    command = db.scalar(
        select(BrowserCommand)
        .where(BrowserCommand.id == command_id, BrowserCommand.device_id == device.id)
        .with_for_update()
    )
    if command is None:
        raise HTTPException(404, "Command not found")
    command.report(body.state, request_id=UUID(request.state.request_id))
    return {"state": body.state}
