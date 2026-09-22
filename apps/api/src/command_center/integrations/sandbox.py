"""Fixed-policy Docker adapter for generated research code; no host mounts or network."""

import io
import json
import re
import struct
import tarfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_INPUT_FILES = 20
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 256 * 1024
IMMUTABLE_IMAGE = re.compile(r"(?:[a-zA-Z0-9._:/-]+@)?sha256:[0-9a-f]{64}")


class SandboxError(Exception):
    def __init__(self, code: str, *, cleanup_confirmed: bool = True):
        super().__init__(code)
        self.code = code
        self.cleanup_confirmed = cleanup_confirmed


@dataclass(frozen=True, slots=True)
class SandboxInput:
    version_id: UUID
    artifact_id: UUID
    role: str
    media_type: str
    content_sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ScriptRunRequest:
    execution_id: UUID
    lease_id: UUID
    image: str
    script: str
    inputs: tuple[SandboxInput, ...]


@dataclass(frozen=True, slots=True)
class ScriptResult:
    text: str
    citations: list[dict[str, str]]
    duration_ms: int


class ScriptRunner(Protocol):
    def run(self, request: ScriptRunRequest, *, cancelled: Callable[[], bool]) -> ScriptResult: ...

    def prove_stopped(self, execution_id: UUID, lease_id: UUID) -> bool: ...


def _tar_request(request: ScriptRunRequest) -> bytes:
    if not request.script.strip() or len(request.script.encode()) > 50 * 1024:
        raise SandboxError("validation_failed")
    if not 1 <= len(request.inputs) <= MAX_INPUT_FILES:
        raise SandboxError("validation_failed")
    total = sum(len(item.data) for item in request.inputs)
    if total > MAX_INPUT_BYTES:
        raise SandboxError("resource_limit")
    manifest: dict[str, Any] = {"version": 1, "inputs": []}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        _add_tar_file(archive, "main.py", request.script.encode("utf-8"))
        for index, item in enumerate(request.inputs):
            suffix = "json" if item.media_type == "application/json" else "bin"
            name = f"inputs/{index:02d}-{item.version_id}.{suffix}"
            _add_tar_file(archive, name, item.data)
            manifest["inputs"].append(
                {
                    "artifact_id": str(item.artifact_id),
                    "version_id": str(item.version_id),
                    "role": item.role,
                    "media_type": item.media_type,
                    "content_sha256": item.content_sha256,
                    "path": name,
                }
            )
        _add_tar_file(
            archive,
            "manifest.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
        )
    payload = output.getvalue()
    if len(payload) > MAX_INPUT_BYTES + 1024 * 1024:
        raise SandboxError("resource_limit")
    return payload


def _add_tar_file(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o444
    info.mtime = 0
    info.uid = 65532
    info.gid = 65532
    archive.addfile(info, io.BytesIO(data))


class DockerContainerRunner:
    """Trusted controller for one fixed image entrypoint and byte-stream protocol."""

    def invoke(
        self,
        *,
        image: str,
        payload: bytes,
        execution_id: UUID,
        lease_id: UUID,
        kind: str,
        memory_bytes: int,
        pids: int,
        wall_seconds: int,
        work_tmpfs: str,
        max_output_bytes: int,
        cancelled: Callable[[], bool],
    ) -> bytes:
        if IMMUTABLE_IMAGE.fullmatch(image) is None:
            raise SandboxError("sandbox_unavailable")
        try:
            import docker  # type: ignore[import-untyped]
            from docker.types import LogConfig, Ulimit  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - executor image owns the dependency
            raise SandboxError("sandbox_unavailable") from exc
        client = docker.from_env(timeout=10)
        container = None
        input_attached = None
        output_attached = None
        output: bytes | None = None
        pending_error: SandboxError | None = None
        cleanup_confirmed = True
        started = time.monotonic()
        labels = {
            "command-center.execution-id": str(execution_id),
            "command-center.lease-id": str(lease_id),
            "command-center.kind": kind,
        }
        try:
            client.images.get(image)  # Never pull at execution time.
            container = client.containers.create(
                image=image,
                detach=True,
                stdin_open=True,
                tty=False,
                user="65532:65532",
                environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
                network_mode="none",
                read_only=True,
                tmpfs={
                    "/work": work_tmpfs,
                    "/tmp": "rw,noexec,nosuid,nodev,size=8m,mode=0700,uid=65532,gid=65532",
                },
                mem_limit=memory_bytes,
                memswap_limit=memory_bytes,
                nano_cpus=1_000_000_000,
                pids_limit=pids,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                init=True,
                ulimits=[
                    Ulimit(name="nofile", soft=64, hard=64),
                    Ulimit(name="fsize", soft=max_output_bytes, hard=max_output_bytes),
                    Ulimit(name="core", soft=0, hard=0),
                ],
                labels=labels,
                log_config=LogConfig(type=LogConfig.types.NONE),
            )
            self._verify_config(container, memory_bytes=memory_bytes, pids=pids)
            output_attached = client.api.attach_socket(
                container.id,
                params={"stdin": 0, "stdout": 1, "stderr": 1, "stream": 1},
            )
            input_attached = client.api.attach_socket(
                container.id,
                params={"stdin": 1, "stdout": 1, "stderr": 0, "stream": 1},
            )
            output_raw = getattr(output_attached, "_sock", output_attached)
            input_raw = getattr(input_attached, "_sock", input_attached)
            output_raw.settimeout(0.25)
            input_raw.settimeout(0.25)
            container.start()
            framed_payload = struct.pack(">Q", len(payload)) + payload
            self._send(input_raw, framed_payload, cancelled, container, started, wall_seconds)
            stdout, stderr = self._receive(
                output_raw,
                cancelled=cancelled,
                container=container,
                started=started,
                wall_seconds=wall_seconds,
                max_output_bytes=max_output_bytes,
            )
            result = container.wait(timeout=5)
            if int(result.get("StatusCode", 1)) != 0:
                raise SandboxError("script_failed" if kind == "research" else "render_failed")
            if stderr:
                # Diagnostics are deliberately discarded; their byte budget was enforced.
                pass
            output = stdout
        except SandboxError as exc:
            pending_error = exc
        except Exception as exc:
            pending_error = SandboxError("sandbox_unavailable")
            pending_error.__cause__ = exc
        finally:
            if input_attached is not None:
                with suppress(Exception):
                    input_attached.close()
            if output_attached is not None:
                with suppress(Exception):
                    output_attached.close()
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    cleanup_confirmed = False
            with suppress(Exception):
                client.close()
        if not cleanup_confirmed:
            raise SandboxError(
                pending_error.code if pending_error else "cleanup_pending",
                cleanup_confirmed=False,
            ) from pending_error
        if pending_error is not None:
            raise pending_error
        assert output is not None
        return output

    def prove_stopped(self, execution_id: UUID, lease_id: UUID) -> bool:
        try:
            import docker
        except ImportError:
            return False
        client = docker.from_env(timeout=10)
        try:
            containers = client.containers.list(
                all=True,
                filters={
                    "label": [
                        f"command-center.execution-id={execution_id}",
                        f"command-center.lease-id={lease_id}",
                    ]
                },
            )
            for container in containers:
                container.remove(force=True)
            return not client.containers.list(
                all=True,
                filters={
                    "label": [
                        f"command-center.execution-id={execution_id}",
                        f"command-center.lease-id={lease_id}",
                    ]
                },
            )
        except Exception:
            return False
        finally:
            client.close()

    @staticmethod
    def _verify_config(container: Any, *, memory_bytes: int, pids: int) -> None:
        container.reload()
        config = container.attrs
        host = config.get("HostConfig", {})
        actual_cap_drop = {str(value).upper() for value in host.get("CapDrop") or []}
        security = {str(value).lower() for value in host.get("SecurityOpt") or []}
        if (
            config.get("Config", {}).get("User") != "65532:65532"
            or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or int(host.get("Memory") or 0) != memory_bytes
            or int(host.get("MemorySwap") or 0) != memory_bytes
            or int(host.get("NanoCpus") or 0) != 1_000_000_000
            or int(host.get("PidsLimit") or 0) != pids
            or "ALL" not in actual_cap_drop
            or not any(value.startswith("no-new-privileges") for value in security)
            or host.get("Binds")
            or config.get("Mounts")
        ):
            raise SandboxError("sandbox_unavailable")

    @staticmethod
    def _send(
        raw: Any,
        payload: bytes,
        cancelled: Callable[[], bool],
        container: Any,
        started: float,
        wall_seconds: int,
    ) -> None:
        view = memoryview(payload)
        while view:
            if cancelled():
                container.kill()
                raise SandboxError("cancelled")
            if time.monotonic() - started > wall_seconds:
                container.kill()
                raise SandboxError("timed_out")
            try:
                written = raw.send(view[:65536])
                if written == 0:
                    raise SandboxError("sandbox_unavailable")
                view = view[written:]
            except TimeoutError:
                continue

    @staticmethod
    def _receive(
        raw: Any,
        *,
        cancelled: Callable[[], bool],
        container: Any,
        started: float,
        wall_seconds: int,
        max_output_bytes: int,
    ) -> tuple[bytes, bytes]:
        buffer = bytearray()
        stdout = bytearray()
        stderr = bytearray()
        while True:
            if cancelled():
                container.kill()
                raise SandboxError("cancelled")
            if time.monotonic() - started > wall_seconds:
                container.kill()
                raise SandboxError("timed_out")
            try:
                chunk = raw.recv(65536)
            except TimeoutError:
                continue
            if not chunk:
                break
            buffer.extend(chunk)
            while len(buffer) >= 8:
                stream, length = buffer[0], struct.unpack(">I", buffer[4:8])[0]
                if len(buffer) < 8 + length:
                    break
                data = buffer[8 : 8 + length]
                del buffer[: 8 + length]
                target = stdout if stream == 1 else stderr
                target.extend(data)
                limit = max_output_bytes if stream == 1 else MAX_DIAGNOSTIC_BYTES
                if len(target) > limit:
                    container.kill()
                    raise SandboxError("output_limit")
        if buffer:
            raise SandboxError("script_failed")
        return bytes(stdout), bytes(stderr)


class DockerScriptRunner:
    def __init__(self, controller: DockerContainerRunner | None = None):
        self.controller = controller or DockerContainerRunner()

    def run(self, request: ScriptRunRequest, *, cancelled: Callable[[], bool]) -> ScriptResult:
        payload = _tar_request(request)
        started = time.monotonic()
        output = self.controller.invoke(
            image=request.image,
            payload=payload,
            execution_id=request.execution_id,
            lease_id=request.lease_id,
            kind="research",
            memory_bytes=256 * 1024 * 1024,
            pids=64,
            wall_seconds=90,
            work_tmpfs="rw,noexec,nosuid,nodev,size=24m,mode=0700,uid=65532,gid=65532",
            max_output_bytes=MAX_OUTPUT_BYTES,
            cancelled=cancelled,
        )
        try:
            value = json.loads(output)
        except (ValueError, UnicodeError) as exc:
            raise SandboxError("validation_failed") from exc
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            raise SandboxError("validation_failed")
        citations = value.get("citations", [])
        if not isinstance(citations, list) or not all(isinstance(item, dict) for item in citations):
            raise SandboxError("validation_failed")
        return ScriptResult(
            text=value["text"],
            citations=[
                {
                    "source_version_id": str(item.get("source_version_id", "")),
                    "label": str(item.get("label", "")),
                }
                for item in citations
            ],
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def prove_stopped(self, execution_id: UUID, lease_id: UUID) -> bool:
        return self.controller.prove_stopped(execution_id, lease_id)
