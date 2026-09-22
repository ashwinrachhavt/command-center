"""Fixed stdin-tar/stdout-JSON protocol for one generated Python script."""

import io
import json
import os
import pathlib
import resource
import selectors
import signal
import struct
import subprocess
import sys
import tarfile
import time

WORK = pathlib.Path(os.environ.get("COMMAND_CENTER_SANDBOX_WORK", "/work"))
MAX_ARCHIVE_BYTES = 21 * 1024 * 1024
MAX_FILES = 22
MAX_STDOUT = 1024 * 1024
MAX_STDERR = 256 * 1024


def fail() -> "NoReturn":
    raise SystemExit(2)


def extract() -> None:
    count = total = 0
    allowed_top = {"main.py", "manifest.json", "inputs"}
    length_bytes = sys.stdin.buffer.read(8)
    if len(length_bytes) != 8:
        fail()
    length = struct.unpack(">Q", length_bytes)[0]
    if length > MAX_ARCHIVE_BYTES + 1024 * 1024:
        fail()
    payload = sys.stdin.buffer.read(length)
    if len(payload) != length:
        fail()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        for member in archive:
            count += 1
            parts = pathlib.PurePosixPath(member.name).parts
            if (
                count > MAX_FILES
                or not member.isreg()
                or not parts
                or parts[0] not in allowed_top
                or member.name.startswith("/")
                or ".." in parts
                or len(parts) > 2
                or member.size < 0
            ):
                fail()
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                fail()
            source = archive.extractfile(member)
            if source is None:
                fail()
            target = WORK.joinpath(*parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o400,
            )
            with os.fdopen(descriptor, "wb") as output:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        fail()
                    output.write(chunk)
                    remaining -= len(chunk)
    if not (WORK / "main.py").is_file() or not (WORK / "manifest.json").is_file():
        fail()


def limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_STDOUT, MAX_STDOUT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run() -> bytes:
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", str(WORK / "main.py"), str(WORK / "manifest.json")],
        cwd=WORK,
        env={
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        preexec_fn=limits,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output, diagnostics = bytearray(), bytearray()
    deadline = time.monotonic() + 75
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                fail()
            for key, _ in selector.select(timeout=0.25):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = output if key.data == "stdout" else diagnostics
                target.extend(chunk)
                if len(output) > MAX_STDOUT or len(diagnostics) > MAX_STDERR:
                    fail()
        if process.wait(timeout=1) != 0:
            fail()
        return bytes(output)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def validate(raw: bytes) -> bytes:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        fail()
    if not isinstance(value, dict) or not isinstance(value.get("text"), str):
        fail()
    if not value["text"].strip() or len(value["text"]) > 100_000:
        fail()
    citations = value.get("citations", [])
    if not isinstance(citations, list) or len(citations) > 50:
        fail()
    normalized = []
    for citation in citations:
        if not isinstance(citation, dict):
            fail()
        version_id = citation.get("source_version_id")
        label = citation.get("label")
        if not isinstance(version_id, str) or not isinstance(label, str) or not 0 < len(label) <= 300:
            fail()
        normalized.append({"source_version_id": version_id, "label": label})
    return json.dumps(
        {"text": value["text"], "citations": normalized},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


extract()
sys.stdout.buffer.write(validate(run()))
