import io
import json
import struct
import subprocess
import sys
import tarfile
import types
from pathlib import Path
from uuid import uuid4

import pytest

from command_center.integrations.pdf_renderer import (
    DockerWeasyPrintRenderer,
    PdfRenderRequest,
)
from command_center.integrations.sandbox import (
    DockerContainerRunner,
    DockerScriptRunner,
    SandboxError,
    SandboxInput,
    ScriptRunRequest,
    _tar_request,
)


class FakeController:
    def __init__(self, output: bytes):
        self.output = output
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return self.output

    def prove_stopped(self, execution_id, lease_id):
        return True


def request() -> ScriptRunRequest:
    return ScriptRunRequest(
        execution_id=uuid4(),
        lease_id=uuid4(),
        image="sha256:" + "a" * 64,
        script="print('synthetic')",
        inputs=(
            SandboxInput(
                version_id=uuid4(),
                artifact_id=uuid4(),
                role="material",
                media_type="text/plain",
                content_sha256="b" * 64,
                data=b"synthetic input",
            ),
        ),
    )


def test_script_request_is_a_bounded_flat_archive() -> None:
    payload = _tar_request(request())

    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        names = archive.getnames()
        manifest = json.load(archive.extractfile("manifest.json"))

    assert names == ["main.py", names[1], "manifest.json"]
    assert names[1].startswith("inputs/00-")
    assert manifest["inputs"][0]["path"] == names[1]


def test_script_adapter_validates_result_and_enforces_networkless_policy() -> None:
    controller = FakeController(json.dumps({"text": "Synthetic brief", "citations": []}).encode())
    runner = DockerScriptRunner(controller)

    result = runner.run(request(), cancelled=lambda: False)

    assert result.text == "Synthetic brief"
    assert controller.calls[0]["kind"] == "research"
    assert controller.calls[0]["memory_bytes"] == 256 * 1024 * 1024
    assert controller.calls[0]["pids"] == 64


def test_script_adapter_rejects_unstructured_output() -> None:
    runner = DockerScriptRunner(FakeController(b"not json"))

    with pytest.raises(SandboxError, match="validation_failed"):
        runner.run(request(), cancelled=lambda: False)


def test_controller_rejects_mutable_image_reference() -> None:
    with pytest.raises(SandboxError, match="sandbox_unavailable"):
        DockerContainerRunner().invoke(
            image="research-sandbox:latest",
            payload=b"synthetic",
            execution_id=uuid4(),
            lease_id=uuid4(),
            kind="research",
            memory_bytes=256,
            pids=2,
            wall_seconds=5,
            work_tmpfs="rw,size=1m",
            max_output_bytes=1024,
            cancelled=lambda: False,
        )


def test_fixed_script_runner_drops_environment_and_validates_json(tmp_path: Path) -> None:
    source = """import json, os, sys
manifest = json.load(open(sys.argv[1]))
has_secret = "OPENAI_API_KEY" in os.environ
text = f"inputs={len(manifest['inputs'])};secret={has_secret}"
print(json.dumps({"text": text, "citations": []}))
"""
    value = request()
    archive = _tar_request(
        ScriptRunRequest(
            execution_id=value.execution_id,
            lease_id=value.lease_id,
            image=value.image,
            script=source,
            inputs=value.inputs,
        )
    )
    runner = Path(__file__).parents[2] / "research-sandbox" / "runner.py"
    completed = subprocess.run(
        [sys.executable, str(runner)],
        input=struct.pack(">Q", len(archive)) + archive,
        capture_output=True,
        timeout=5,
        check=True,
        env={
            "COMMAND_CENTER_SANDBOX_WORK": str(tmp_path),
            "OPENAI_API_KEY": "must-not-enter-child",
            "PATH": str(Path(sys.executable).parent),
        },
    )

    assert json.loads(completed.stdout)["text"] == "inputs=1;secret=False"


def test_pdf_adapter_accepts_only_bounded_pdf_bytes() -> None:
    controller = FakeController(b"%PDF-1.7\nsynthetic")
    renderer = DockerWeasyPrintRenderer(controller)
    request_value = PdfRenderRequest(
        export_id=uuid4(),
        lease_id=uuid4(),
        image="sha256:" + "a" * 64,
        title="Synthetic brief",
        markdown="# Safe",
    )

    assert renderer.render(request_value, cancelled=lambda: False).data.startswith(b"%PDF-")
    assert controller.calls[0]["memory_bytes"] == 512 * 1024 * 1024
    assert controller.calls[0]["pids"] == 128

    controller.output = b"not pdf"
    with pytest.raises(SandboxError, match="validation_failed"):
        renderer.render(request_value, cancelled=lambda: False)


def test_controller_does_not_claim_cleanup_when_container_removal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"text":"ok","citations":[]}'
    frame = bytes([1, 0, 0, 0]) + struct.pack(">I", len(payload)) + payload

    class Raw:
        def __init__(self, chunks: list[bytes]):
            self.chunks = chunks

        def settimeout(self, _: float) -> None:
            return None

        def recv(self, _: int) -> bytes:
            return self.chunks.pop(0)

        def send(self, value: bytes) -> int:
            return len(value)

        def shutdown(self, _: int) -> None:
            return None

    class Attached:
        def __init__(self, raw: Raw):
            self._sock = raw

        def close(self) -> None:
            return None

    class Container:
        id = "synthetic-container"
        attrs = {
            "Config": {"User": "65532:65532"},
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Memory": 256,
                "MemorySwap": 256,
                "NanoCpus": 1_000_000_000,
                "PidsLimit": 2,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Binds": None,
            },
            "Mounts": [],
        }

        def reload(self) -> None:
            return None

        def start(self) -> None:
            return None

        def wait(self, timeout: int) -> dict[str, int]:
            assert timeout == 5
            return {"StatusCode": 0}

        def remove(self, *, force: bool) -> None:
            assert force
            raise RuntimeError("synthetic daemon failure")

    container = Container()

    class Api:
        calls = 0

        def attach_socket(self, *_args, **_kwargs) -> Attached:
            self.calls += 1
            return Attached(Raw([frame, b""] if self.calls == 1 else []))

    class Client:
        images = types.SimpleNamespace(get=lambda _image: object())
        containers = types.SimpleNamespace(create=lambda **_kwargs: container)
        api = Api()

        def close(self) -> None:
            return None

    docker = types.ModuleType("docker")
    docker.from_env = lambda **_kwargs: Client()  # type: ignore[attr-defined]
    docker_types = types.ModuleType("docker.types")
    docker_types.LogConfig = type(
        "LogConfig",
        (),
        {
            "types": types.SimpleNamespace(NONE="none"),
            "__init__": lambda self, **kwargs: None,
        },
    )
    docker_types.Ulimit = type("Ulimit", (), {"__init__": lambda self, **kwargs: None})
    monkeypatch.setitem(sys.modules, "docker", docker)
    monkeypatch.setitem(sys.modules, "docker.types", docker_types)

    with pytest.raises(SandboxError) as caught:
        DockerContainerRunner().invoke(
            image="sha256:" + "a" * 64,
            payload=b"synthetic",
            execution_id=uuid4(),
            lease_id=uuid4(),
            kind="research",
            memory_bytes=256,
            pids=2,
            wall_seconds=5,
            work_tmpfs="rw,size=1m",
            max_output_bytes=1024,
            cancelled=lambda: False,
        )

    assert caught.value.cleanup_confirmed is False
