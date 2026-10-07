"""Paired-browser HTTP boundary for reviewed, exact application assistance."""

import re
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

from command_center.api import schemas as s
from command_center.api.browser_contracts import (
    AutomationClaimResult,
    AutomationEvidenceReport,
    AutomationRunResult,
    ClaimResult,
    FillCreate,
    FillResult,
    PairCreate,
    PairCredentials,
    PairExchange,
    PendingAutomationCommand,
    PendingCommand,
    ResumeOptions,
    SnapshotCreate,
)
from command_center.api.workspace import Database, WriteKey, serialize, write
from command_center.core.auth import bearer
from command_center.core.identity import CurrentIdentity
from command_center.db.applications_automation import Application, AutomationRun
from command_center.db.base import utc_now
from command_center.db.browser import (
    BrowserCommand,
    BrowserDevice,
    BrowserSnapshot,
    application_file_options,
    digest,
    resume_options,
)
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])


def device_identity(
    db: Database, credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> BrowserDevice:
    if credential is None:
        raise HTTPException(401, "Pair this browser first")
    device = db.scalar(
        select(BrowserDevice)
        .join(Actor, Actor.id == BrowserDevice.owner_id)
        .where(
            BrowserDevice.token_digest == digest(credential.credentials),
            BrowserDevice.revoked_at.is_(None),
            Actor.active.is_(True),
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


def command_data(db: Database, command: BrowserCommand) -> dict[str, Any]:
    snapshot = db.get(BrowserSnapshot, command.snapshot_id)
    if snapshot is None:
        raise RecordConflict("Reshare this form before applying values")
    snapshot.require_current()
    data = serialize(command)
    data.pop("field_results", None)
    return {
        **data,
        "owner_id": str(command.owner_id),
        "page_url": snapshot.page_url,
        "form_fields": snapshot.fields,
    }


def create_command(
    db: Database,
    snapshot: BrowserSnapshot,
    body: FillCreate,
    *,
    command_id: UUID,
    request_id: UUID,
) -> dict[str, Any]:
    command = snapshot.propose_fill(
        command_id=command_id,
        fields=body.fields,
        uploads=body.uploads,
        replace_fields=body.replace_fields,
        preparation_version_id=body.preparation_version_id,
        request_id=request_id,
    )
    db.flush()
    return command_data(db, command)


@router.get("/devices")
def devices(identity: CurrentIdentity, db: Database) -> list[dict[str, Any]]:
    return [
        device_data(device)
        for device in db.scalars(
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
        protocol_version=body.protocol_version,
        page_url=str(body.page_url),
        title=body.title,
        # Keep pre-upgrade capture identities replayable: absent additive metadata
        # must not change their persisted JSON shape.
        fields=[
            field.model_dump(
                exclude={
                    name
                    for name in ("history", "temporal_constraints")
                    if getattr(field, name) is None
                }
            )
            for field in body.fields
        ],
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


@router.get("/resumes", response_model=ResumeOptions)
def resumes(identity: CurrentIdentity, db: Database) -> dict[str, object]:
    return resume_options(db, identity.id)


@router.get("/device/resumes", response_model=ResumeOptions)
def device_resumes(device: Device, db: Database) -> dict[str, object]:
    return resume_options(db, device.owner_id)


@router.get("/cover-letters", response_model=ResumeOptions)
def cover_letters(identity: CurrentIdentity, db: Database) -> dict[str, object]:
    return application_file_options(db, identity.id, kind="cover-letter")


@router.get("/device/cover-letters", response_model=ResumeOptions)
def device_cover_letters(device: Device, db: Database) -> dict[str, object]:
    return application_file_options(db, device.owner_id, kind="cover-letter")


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
        return create_command(
            db,
            snapshot,
            body,
            command_id=command_id,
            request_id=UUID(request.state.request_id),
        )

    return write(db, identity.id, key, "POST:browser-command", body, change)


@router.post("/device/commands", status_code=201)
def device_propose_fill(
    body: FillCreate, device: Device, db: Database, key: WriteKey, request: Request
) -> dict[str, Any]:
    def change(command_id: UUID) -> dict[str, Any]:
        snapshot = db.scalar(
            select(BrowserSnapshot).where(
                BrowserSnapshot.id == body.snapshot_id,
                BrowserSnapshot.device_id == device.id,
                BrowserSnapshot.owner_id == device.owner_id,
            )
        )
        if snapshot is None:
            raise HTTPException(404, "Form snapshot not found for this browser")
        return create_command(
            db,
            snapshot,
            body,
            command_id=command_id,
            request_id=UUID(request.state.request_id),
        )

    return write(
        db,
        device.owner_id,
        key,
        f"POST:browser-device-command:{device.id}",
        body,
        change,
    )


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
            BrowserCommand.device_id == device.id,
            BrowserCommand.owner_id == device.owner_id,
            BrowserCommand.state.in_(["pending", "claimed"]),
        )
        .order_by(BrowserCommand.created_at)
        .with_for_update()
    ).all()
    results = []
    for command in rows:
        command.expire(request_id=UUID(request.state.request_id))
        if command.state == "pending":
            results.append(command_data(db, command))
    return results


@router.post("/device/commands/{command_id}/claim", response_model=ClaimResult)
def claim(command_id: UUID, device: Device, db: Database, request: Request) -> dict[str, str]:
    command = db.scalar(
        select(BrowserCommand)
        .where(
            BrowserCommand.id == command_id,
            BrowserCommand.device_id == device.id,
            BrowserCommand.owner_id == device.owner_id,
        )
        .with_for_update()
    )
    if command is None:
        raise HTTPException(404, "Command not found")
    command.claim(request_id=UUID(request.state.request_id))
    return {"state": "claimed"}


@router.post("/device/commands/{command_id}/result", response_model=FillResult)
def result(
    command_id: UUID, body: FillResult, device: Device, db: Database, request: Request
) -> dict[str, Any]:
    command = db.scalar(
        select(BrowserCommand)
        .where(
            BrowserCommand.id == command_id,
            BrowserCommand.device_id == device.id,
            BrowserCommand.owner_id == device.owner_id,
        )
        .with_for_update()
    )
    if command is None:
        raise HTTPException(404, "Command not found")
    results = {
        field_id: field_result.model_dump() for field_id, field_result in body.field_results.items()
    }
    command.report(body.state, results, request_id=UUID(request.state.request_id))
    return body.model_dump()


@router.get("/device/commands/{command_id}/files/{field_id}")
def command_file(
    command_id: UUID,
    field_id: str,
    device: Device,
    db: Database,
    request: Request,
) -> Response:
    command = db.scalar(
        select(BrowserCommand)
        .where(
            BrowserCommand.id == command_id,
            BrowserCommand.device_id == device.id,
            BrowserCommand.owner_id == device.owner_id,
        )
        .with_for_update()
    )
    if command is None or command.state != "claimed":
        raise HTTPException(404, "Claimed upload not found")
    if command.expires_at <= utc_now():
        command.expire(request_id=UUID(request.state.request_id))
        raise HTTPException(409, "This command expired; prepare and apply it again")
    metadata = command.upload_files.get(field_id)
    if metadata is None:
        raise HTTPException(404, "Requested upload not found")
    from command_center.core.storage import BlobStore

    content = BlobStore(request.app.state.settings.blob_store_path).read(str(metadata["sha256"]))
    if len(content) != metadata["size_bytes"]:
        raise HTTPException(409, "Pinned upload failed its integrity check")
    filename = str(metadata["filename"])
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)
    return Response(
        content,
        media_type=str(metadata["media_type"]),
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/device/automation/commands", response_model=list[PendingAutomationCommand])
def automation_commands(device: Device, db: Database, request: Request) -> list[dict[str, Any]]:
    """Poll for one queued automation run. Claim is fenced and device-scoped.

    A retry after an expired token receives a recycled run with a fresh token;
    each claim is the only holder of its run_token.
    """
    run = AutomationRun.claim(db, device_id=device.id, owner_id=device.owner_id)
    if run is None:
        return []
    application = db.get(Application, run.application_id)
    if application is None:
        raise RecordConflict("The claimed application is unavailable")
    from command_center.db.adapters import load_adapter_definition

    try:
        adapter = load_adapter_definition(run.adapter_platform)
    except ValueError:
        run.fail(
            run.run_token,  # type: ignore[arg-type]
            error="adapter_unavailable",
            request_id=UUID(request.state.request_id),
        )
        return []
    return [
        {
            "run_id": str(run.id),
            "run_token": str(run.run_token),
            "expires_at": run.run_token_expires_at,
            "attempt": run.attempt,
            "mode": run.mode,
            "application": {
                "id": str(application.id),
                "company": application.company,
                "job_title": application.job_title,
                "job_url": application.job_url,
                "job_location": application.job_location,
                "mode": run.mode,
            },
            "adapter": adapter.model_dump(),
        }
    ]


@router.post("/device/automation/commands/{run_id}/claim", response_model=AutomationClaimResult)
def automation_claim(
    run_id: UUID, device: Device, db: Database, request: Request
) -> dict[str, Any]:
    run = db.scalar(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.device_id == device.id,
            AutomationRun.owner_id == device.owner_id,
        )
    )
    if run is None or run.run_token is None:
        raise HTTPException(404, "Automation run not found")
    return {
        "state": "claimed",
        "run_id": str(run.id),
        "run_token": str(run.run_token),
        "expires_at": run.run_token_expires_at,
    }


@router.post("/device/automation/commands/{run_id}/evidence")
def automation_evidence(
    run_id: UUID, body: AutomationEvidenceReport, device: Device, db: Database
) -> dict[str, str]:
    """Persist mid-run evidence; fenced by the claim's run_token."""
    run = db.scalar(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.device_id == device.id,
            AutomationRun.owner_id == device.owner_id,
        )
    )
    if run is None:
        raise HTTPException(404, "Automation run not found")
    try:
        run.report(
            UUID(body.run_token),
            field_evidence={key: value.model_dump() for key, value in body.field_evidence.items()},
            page_evidence=body.page_evidence,
            simplify_step=body.simplify_step,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"state": "recorded"}


@router.post("/device/automation/commands/{run_id}/result")
def automation_result(
    run_id: UUID, body: AutomationRunResult, device: Device, db: Database
) -> dict[str, str]:
    """Record one run's terminal state; dispatches by the reported state."""
    run = db.scalar(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.device_id == device.id,
            AutomationRun.owner_id == device.owner_id,
        )
    )
    if run is None:
        raise HTTPException(404, "Automation run not found")
    token = UUID(body.run_token)
    evidence = {key: value.model_dump() for key, value in body.field_evidence.items()}
    request_id = UUID(body.run_token)  # deterministic per attempt; token is the fence
    try:
        if body.state == "completed":
            run.complete(
                token,
                field_evidence=evidence,
                page_evidence=body.page_evidence,
                simplify_step=body.simplify_step,
                request_id=request_id,
            )
        elif body.state == "failed":
            run.fail(token, error=body.detail, field_evidence=evidence, request_id=request_id)
        else:
            run.mark_outcome_unknown(
                token, detail=body.detail, field_evidence=evidence, request_id=request_id
            )
    except RecordConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"state": "recorded"}


@router.get("/device/adapters")
def device_adapters(device: Device) -> list[dict[str, str]]:
    """Served adapter index: platform, revision, host match."""

    from command_center.db.adapters import ADAPTERS_DIR

    index = []
    for path in sorted(ADAPTERS_DIR.glob("*.yaml")):
        from command_center.db.adapters import load_adapter_definition

        try:
            adapter = load_adapter_definition(path.stem)
        except ValueError:
            continue
        index.append(
            {
                "platform": adapter.platform,
                "revision": adapter.revision,
                "match_host": adapter.match_host,
            }
        )
    return index


@router.get("/device/adapters/{platform}")
def device_adapter(platform: str, device: Device) -> dict[str, Any]:
    """One full served adapter definition."""
    from command_center.db.adapters import load_adapter_definition

    try:
        adapter = load_adapter_definition(platform)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return adapter.model_dump()
