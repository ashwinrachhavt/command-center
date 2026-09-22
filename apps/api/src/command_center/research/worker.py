"""Fenced research sandbox execution with exact immutable inputs."""

import json
import logging
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.core.storage import BlobStore
from command_center.db.artifacts import ArtifactVersion
from command_center.db.research_executions import ResearchExecution, ResearchExecutionInput
from command_center.integrations.sandbox import (
    MAX_INPUT_BYTES,
    DockerScriptRunner,
    SandboxError,
    SandboxInput,
    ScriptRunner,
    ScriptRunRequest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedResearch:
    id: UUID
    lease_id: UUID
    script: str
    image: str
    inputs: tuple[tuple[ResearchExecutionInput, ArtifactVersion], ...]


def claim(engine: Engine, execution_id: UUID) -> ClaimedResearch | None:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        execution = ResearchExecution.claim(db, execution_id)
        if execution is None:
            return None
        script_version = db.get(ArtifactVersion, execution.script_version_id)
        source = (
            script_version.payload.get("source")
            if script_version and script_version.payload
            else None
        )
        image = execution.policy_snapshot.get("image")
        if not isinstance(source, str) or not isinstance(image, str) or not image:
            raise ValueError("Research execution snapshot is invalid")
        pairs = tuple(
            (row[0], row[1])
            for row in db.execute(
                select(ResearchExecutionInput, ArtifactVersion)
                .join(ArtifactVersion, ArtifactVersion.id == ResearchExecutionInput.version_id)
                .where(ResearchExecutionInput.execution_id == execution.id)
                .order_by(ResearchExecutionInput.version_id)
            )
        )
        db.flush()
        assert execution.lease_id is not None
        return ClaimedResearch(execution.id, execution.lease_id, source, image, pairs)


def _input_bytes(settings: Settings, version: ArtifactVersion) -> bytes:
    if version.payload is not None:
        return json.dumps(
            version.payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    return BlobStore(settings.blob_store_path).read(version.content_sha256)


class LeasePulse:
    def __init__(self, engine: Engine, execution_id: UUID, lease_id: UUID):
        self.engine, self.execution_id, self.lease_id = engine, execution_id, lease_id
        self.next_check = 0.0

    def cancelled(self) -> bool:
        now = time.monotonic()
        if now < self.next_check:
            return False
        self.next_check = now + 5
        with Session(self.engine) as db, db.begin():
            execution = db.scalar(
                select(ResearchExecution)
                .where(ResearchExecution.id == self.execution_id)
                .with_for_update(key_share=True)
            )
            if execution is None or not execution.accepts(self.lease_id):
                return True
            execution.renew(self.lease_id)
        return False


def _mark_cleanup(engine: Engine, claimed: ClaimedResearch) -> None:
    with Session(engine) as db, db.begin():
        execution = db.get(ResearchExecution, claimed.id)
        if execution is not None:
            execution.mark_cleanup_confirmed(claimed.lease_id)


def _fail(engine: Engine, claimed: ClaimedResearch, code: str, *, cleanup_confirmed: bool) -> None:
    with Session(engine) as db, db.begin():
        execution = db.scalar(
            select(ResearchExecution).where(ResearchExecution.id == claimed.id).with_for_update()
        )
        if execution is not None:
            execution.fail(claimed.lease_id, code, cleanup=cleanup_confirmed)


def perform_research_execution(
    engine: Engine,
    settings: Settings,
    execution_id: UUID | str,
    runner: ScriptRunner | None = None,
) -> bool:
    claimed = claim(engine, UUID(str(execution_id)))
    if claimed is None:
        return False
    adapter = runner or DockerScriptRunner()
    pulse = LeasePulse(engine, claimed.id, claimed.lease_id)
    try:
        prepared: list[SandboxInput] = []
        input_bytes = 0
        for item, version in claimed.inputs:
            data = _input_bytes(settings, version)
            input_bytes += len(data)
            if input_bytes > MAX_INPUT_BYTES:
                raise SandboxError("resource_limit")
            prepared.append(
                SandboxInput(
                    version_id=item.version_id,
                    artifact_id=item.artifact_id,
                    role=item.role,
                    media_type=version.media_type,
                    content_sha256=version.content_sha256,
                    data=data,
                )
            )
        result = adapter.run(
            ScriptRunRequest(
                execution_id=claimed.id,
                lease_id=claimed.lease_id,
                image=claimed.image,
                script=claimed.script,
                inputs=tuple(prepared),
            ),
            cancelled=pulse.cancelled,
        )
        _mark_cleanup(engine, claimed)
        with Session(engine) as db, db.begin():
            execution = db.scalar(
                select(ResearchExecution)
                .where(ResearchExecution.id == claimed.id)
                .with_for_update()
            )
            if execution is None or not execution.accepts(claimed.lease_id):
                return True
            execution.complete(
                claimed.lease_id,
                text=result.text,
                citations=result.citations,
                request_id=uuid4(),
            )
        return True
    except SandboxError as exc:
        if exc.cleanup_confirmed:
            _mark_cleanup(engine, claimed)
        if exc.code != "cancelled":
            _fail(
                engine,
                claimed,
                exc.code,
                cleanup_confirmed=exc.cleanup_confirmed,
            )
        return True
    except Exception:
        logger.warning("Research execution %s failed; content suppressed", claimed.id)
        cleanup_confirmed = adapter.prove_stopped(claimed.id, claimed.lease_id)
        if cleanup_confirmed:
            _mark_cleanup(engine, claimed)
        _fail(
            engine,
            claimed,
            "execution_failed",
            cleanup_confirmed=cleanup_confirmed,
        )
        return True


def reap_research_sandboxes(
    engine: Engine, runner: ScriptRunner | None = None, *, limit: int = 20
) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Cleanup limit must be between 1 and 100")
    adapter = runner or DockerScriptRunner()
    with Session(engine) as db:
        rows = list(
            db.execute(
                select(ResearchExecution.id, ResearchExecution.container_lease_id)
                .where(
                    ResearchExecution.state.in_(["failed", "cancelled"]),
                    ResearchExecution.cleanup_confirmed_at.is_(None),
                    ResearchExecution.container_lease_id.is_not(None),
                )
                .order_by(ResearchExecution.updated_at, ResearchExecution.id)
                .limit(limit)
            ).all()
        )
    cleaned = 0
    for execution_id, lease_id in rows:
        assert lease_id is not None
        if not adapter.prove_stopped(execution_id, lease_id):
            continue
        with Session(engine) as db, db.begin():
            execution = db.scalar(
                select(ResearchExecution)
                .where(ResearchExecution.id == execution_id)
                .with_for_update()
            )
            if execution and execution.mark_cleanup_confirmed(lease_id):
                cleaned += 1
    return cleaned
