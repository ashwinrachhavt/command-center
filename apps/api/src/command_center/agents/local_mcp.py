"""Authenticated stdio bridge. No database, provider keys or API admin token needed."""

import argparse
import getpass
import os
import stat
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_TOKEN_FILE = Path.home() / ".config" / "command-center" / "mcp-token"


def configure(path: Path) -> None:
    token = getpass.getpass("Paste your Command Center client token (hidden): ").strip()
    if not token.startswith("cc_local."):
        raise ValueError("Expected a local MCP client token from Command Center Settings")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(token + "\n")
    print(f"Saved client credential to {path}. Treat this file as a secret.")


def serve(url: str, path: Path) -> None:
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.server import create_proxy
    from fastmcp.server.providers.proxy import ProxyClient

    target = urlparse(url)
    if target.username or target.password or target.query or target.fragment:
        raise ValueError("MCP URL must not contain credentials, query parameters or fragments")
    if target.scheme != "https" and not (
        target.scheme == "http" and target.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("Use HTTPS, or HTTP on localhost only")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("Client credential file must be a private regular file (chmod 600)")
    token = path.read_text().strip()
    if not token.startswith("cc_local."):
        raise ValueError("Expected an actor-bound local MCP client token")
    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
    server = create_proxy(ProxyClient(transport), name="command-center-local")
    server.run(transport="stdio", show_banner=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure", help="Save a client token using a hidden prompt")
    setup.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    launch = sub.add_parser("serve", help="Run the authenticated stdio MCP bridge")
    launch.add_argument("--url", default="http://localhost:8000/mcp/")
    launch.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    args = parser.parse_args()
    if args.command == "configure":
        configure(args.token_file.expanduser())
    else:
        serve(args.url, args.token_file.expanduser())


if __name__ == "__main__":
    main()
