import ipaddress
import re
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit

_LOCAL_HOST_SUFFIXES = (".internal", ".lan", ".local", ".localhost")
_NUMERIC_HOST = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+))*$")


def normalize_public_url(value: str) -> str:
    """Validate and canonicalize an HTTP(S) URL without doing network I/O."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Use a valid public URL")
    if len(value) > 2000 or "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError("Use a valid public URL")

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Use a valid public URL") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc or parsed.username is not None:
        raise ValueError("Use a valid public URL")
    if parsed.password is not None:
        raise ValueError("Use a valid public URL")

    raw_host = parsed.hostname
    if raw_host is None or "%" in raw_host:
        raise ValueError("Use a valid public URL")
    host = raw_host.rstrip(".").lower()
    if not host or host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
        raise ValueError("Use a valid public URL")

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Use a valid public URL") from exc

    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    try:
        address = ipaddress.ip_address(ascii_host)
    except ValueError:
        address = None

    if address is not None and not address.is_global:
        raise ValueError("Use a valid public URL")
    if address is None and _looks_like_encoded_ip(ascii_host):
        raise ValueError("Use a valid public URL")

    expected_port = 80 if scheme == "http" else 443
    if port not in {None, expected_port}:
        raise ValueError("Use a standard HTTP(S) port")

    host_for_url = f"[{ascii_host}]" if isinstance(address, ipaddress.IPv6Address) else ascii_host
    normalized = SplitResult(
        scheme=scheme,
        netloc=host_for_url,
        path=parsed.path,
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)


def _looks_like_encoded_ip(host: str) -> bool:
    if not _NUMERIC_HOST.fullmatch(host):
        return False
    try:
        socket.inet_aton(host)
    except OSError:
        return False
    return True
