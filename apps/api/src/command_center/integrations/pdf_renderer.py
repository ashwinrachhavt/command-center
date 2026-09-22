"""Fixed-image PDF rendering adapter over the networkless Docker controller."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from command_center.integrations.sandbox import DockerContainerRunner, SandboxError

MAX_PDF_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PdfRenderRequest:
    export_id: UUID
    lease_id: UUID
    image: str
    title: str
    markdown: str


@dataclass(frozen=True, slots=True)
class PdfResult:
    data: bytes


class PdfRenderer(Protocol):
    def render(self, request: PdfRenderRequest, *, cancelled: Callable[[], bool]) -> PdfResult: ...

    def prove_stopped(self, export_id: UUID, lease_id: UUID) -> bool: ...


class DockerWeasyPrintRenderer:
    def __init__(self, controller: DockerContainerRunner | None = None):
        self.controller = controller or DockerContainerRunner()

    def render(self, request: PdfRenderRequest, *, cancelled: Callable[[], bool]) -> PdfResult:
        if not request.title.strip() or len(request.title) > 300 or len(request.markdown) > 100_000:
            raise SandboxError("validation_failed")
        payload = json.dumps(
            {"version": 1, "title": request.title, "markdown": request.markdown},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > 1024 * 1024:
            raise SandboxError("resource_limit")
        output = self.controller.invoke(
            image=request.image,
            payload=payload,
            execution_id=request.export_id,
            lease_id=request.lease_id,
            kind="pdf",
            memory_bytes=512 * 1024 * 1024,
            pids=128,
            wall_seconds=60,
            work_tmpfs="rw,noexec,nosuid,nodev,size=64m,mode=0700,uid=65532,gid=65532",
            max_output_bytes=MAX_PDF_BYTES,
            cancelled=cancelled,
        )
        if len(output) <= 4 or len(output) > MAX_PDF_BYTES or not output.startswith(b"%PDF-"):
            raise SandboxError("validation_failed")
        return PdfResult(output)

    def prove_stopped(self, export_id: UUID, lease_id: UUID) -> bool:
        return self.controller.prove_stopped(export_id, lease_id)
