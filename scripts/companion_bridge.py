"""Local native-messaging bridge: a fixed, read-only AgentBrowser page inspection.

Chrome launches this helper for a single extension request. No HTTP listener, arbitrary
commands, cookies, page values or agent instructions are exposed by the protocol.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local" / "companion"
EXTENSION = ROOT / "apps" / "extension"
HOST = "com.commandcenter.agent_browser"
TASK = "command-center-copilot"


def extension_origin() -> str:
    key = json.loads((EXTENSION / "manifest.json").read_text())["key"]
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "chrome-extension://" + "".join(chr(97 + int(c, 16)) for c in digest) + "/"


def cli(*args: str) -> dict:
    wrapper = shutil.which("ab")
    if not wrapper:
        raise ValueError(
            "Install AgentBrowser and the ab launcher, then run make companion-setup."
        )
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    (LOCAL / "bridge-health.json").write_text(
        json.dumps({"operation": args[0], "state": "started"})
    )
    result = subprocess.run(
        [wrapper, "clean", *args, "--json"],
        cwd=ROOT,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if not key.startswith("AGENT_BROWSER_")
            },
            "BROWSER_TASK": TASK,
        },
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=20,
        check=False,
    )
    (LOCAL / "bridge-health.json").write_text(
        json.dumps(
            {
                "operation": args[0],
                "state": "returned",
                "code": result.returncode,
                "bytes": len(result.stdout),
            }
        )
    )
    if result.returncode:
        raise ValueError(
            "AgentBrowser is unavailable. Run make companion-browser and use that window."
        )
    response = json.loads(result.stdout)
    if not response.get("success"):
        raise ValueError(
            "AgentBrowser could not inspect this tab. Open it in the companion browser."
        )
    return response.get("data", {})


def inspect(request: dict) -> dict:
    if set(request) != {"action", "url", "nonce"} or request["action"] != "inspect":
        raise ValueError("Unsupported inspection request.")
    url, nonce = request["url"], request["nonce"]
    if not isinstance(url, str) or len(url) > 10000:
        raise ValueError("Invalid tab URL.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Open a regular job application page.")
    if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9-]{36}", nonce):
        raise ValueError("Invalid tab binding.")
    # Fixed JS plus JSON literals only; page text cannot become executable instructions.
    matches = cli("tab", "list").get("tabs", [])
    candidates = [tab for tab in matches if tab.get("url") == url]
    if not candidates:
        raise ValueError(
            "This tab is outside AgentBrowser. Run make companion-browser and open the job there, or select Direct browser."
        )
    probe = (
        "location.href === "
        + json.dumps(url)
        + " && document.documentElement.getAttribute('data-command-center-inspection') === "
        + json.dumps(nonce)
    )
    structure = (EXTENSION / "page-structure.js").read_text()
    for tab in candidates:
        cli("tab", str(tab["tabId"]))
        result = cli(
            "eval", "(" + probe + ") ? (" + structure.rstrip().rstrip(";") + ") : null"
        )
        value = result.get("result")
        if isinstance(value, dict) and value.get("engine") == "agent-browser":
            return {"ok": True, "structure": value}
    raise ValueError(
        "The tab changed during inspection. Click Autofill again on the intended page."
    )


def native() -> None:
    # Chrome supplies the calling extension origin as argv[1].
    if len(sys.argv) < 2 or sys.argv[1] != extension_origin():
        raise ValueError("Only the Command Center extension can use this native host.")
    header = sys.stdin.buffer.read(4)
    if len(header) != 4:
        return
    size = struct.unpack("=I", header)[0]
    try:
        if size > 16000:
            raise ValueError("Inspection request is too large.")
        payload = sys.stdin.buffer.read(size)
        if len(payload) != size:
            raise ValueError("Incomplete inspection request.")
        request = json.loads(payload)
        if not isinstance(request, dict):
            raise TypeError("Invalid inspection request.")
        LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (LOCAL / "inspection.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError(
                    "Another inspection is running. Try again shortly."
                ) from exc
            response = inspect(request)
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
        response = {
            "ok": False,
            "error": str(exc)
            if isinstance(exc, ValueError)
            else "Inspection interrupted. Try again in the companion browser.",
        }
    encoded = json.dumps(response).encode()
    sys.stdout.buffer.write(struct.pack("=I", len(encoded)) + encoded)
    sys.stdout.buffer.flush()


def install() -> None:
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    launcher = LOCAL / "native-host"
    # Chrome provides a minimal PATH. Resolve the user's existing ab installation once.
    executable = shutil.which("ab")
    if not executable:
        raise ValueError("The ab launcher is required.")
    path = str(Path(executable).parent) + os.pathsep + os.environ.get("PATH", "")
    launcher.write_text(
        "#!/bin/sh\nexport PATH="
        + shlex.quote(path)
        + "\nexec "
        + shlex.quote(sys.executable)
        + " "
        + shlex.quote(str(Path(__file__).resolve()))
        + ' "$@"\n'
    )
    launcher.chmod(0o700)
    manifest = {
        "name": HOST,
        "description": "Command Center AgentBrowser form inspection",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [extension_origin()],
    }
    if sys.platform == "darwin":
        roots = [
            Path.home() / "Library/Application Support" / browser
            for browser in ("Google/Chrome", "Google/Chrome for Testing", "Chromium")
        ]
    elif sys.platform.startswith("linux"):
        roots = [
            Path.home() / ".config" / browser
            for browser in ("google-chrome", "google-chrome-for-testing", "chromium")
        ]
    else:
        raise ValueError("The local helper currently supports macOS and Linux.")
    roots.append(LOCAL / "browser-profile")
    for root in roots:
        directory = root / "NativeMessagingHosts"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (HOST + ".json")).write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        "AgentBrowser helper installed. Run make companion-browser to open the dedicated browser."
    )


def launch() -> None:
    install()
    cli(
        "--profile",
        str(LOCAL / "browser-profile"),
        "--headed",
        "--extension",
        str(EXTENSION),
        "open",
        "http://localhost:3001/browser",
    )
    print(
        "Companion browser opened. Pair the extension once, then visit a job and click Autofill."
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].startswith("chrome-extension://"):
        native()
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("action", choices=("install", "launch"))
        options = parser.parse_args()
        install() if options.action == "install" else launch()
