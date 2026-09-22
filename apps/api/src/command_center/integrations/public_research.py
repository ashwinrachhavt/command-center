import asyncio
import ipaddress
import socket
import ssl
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from command_center.core.public_urls import normalize_public_url
from command_center.integrations.clients import ConnectionState, FirecrawlClient, ProviderError

_MAX_BODY_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5
_TOTAL_TIMEOUT_SECONDS = 20
_REQUEST_TIMEOUT = httpx.Timeout(15, connect=10)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_USER_AGENT = "CommandCenter-PublicResearch/1.0"
_IPV4_COMPATIBLE = ipaddress.IPv6Network("::/96")
_NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")

Resolver = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True, slots=True)
class PublicPage:
    url: str
    title: str
    markdown: str
    provider: str = "public_http"
    extraction_method: str = "html_text"


async def scrape_public(client: FirecrawlClient, url: str) -> PublicPage:
    """Fetch a public page with pinned DNS and bounded redirect/body/time work.

    ``client`` keeps the stable integration boundary but its Firecrawl credentials and
    transport are deliberately not used: Firecrawl cannot give this caller control of
    DNS resolution or validate each redirect before the provider follows it.
    """
    del client
    target = normalize_public_url(url)
    try:
        async with asyncio.timeout(_TOTAL_TIMEOUT_SECONDS):
            return await _fetch_public(target)
    except ValueError:
        raise
    except (TimeoutError, httpx.HTTPError, OSError, UnicodeError) as exc:
        raise ProviderError("public_http", ConnectionState.UNAVAILABLE) from exc


async def _fetch_public(url: str) -> PublicPage:
    transport = _make_public_transport()
    async with httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        timeout=_REQUEST_TIMEOUT,
        trust_env=False,
        headers={
            "Accept": "text/html,text/plain;q=0.9",
            "Accept-Encoding": "identity",
            "User-Agent": _USER_AGENT,
        },
    ) as http:
        target = url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            async with http.stream("GET", target, headers={"Connection": "close"}) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location or redirect_count == _MAX_REDIRECTS:
                        raise ProviderError("public_http", ConnectionState.ERROR)
                    target = normalize_public_url(urljoin(target, location))
                    continue
                if not response.is_success:
                    raise ProviderError("public_http", ConnectionState.ERROR)

                content_encodings = {
                    encoding.strip().lower()
                    for encoding in response.headers.get("content-encoding", "").split(",")
                    if encoding.strip()
                }
                if content_encodings - {"identity"}:
                    raise ProviderError("public_http", ConnectionState.ERROR)
                content_type = response.headers.get("content-type", "").lower()
                if content_type and not (
                    content_type.startswith("text/html")
                    or content_type.startswith("text/plain")
                    or content_type.startswith("application/xhtml+xml")
                ):
                    raise ProviderError("public_http", ConnectionState.ERROR)
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > _MAX_BODY_BYTES:
                            raise ProviderError("public_http", ConnectionState.ERROR)
                    except ValueError as exc:
                        raise ProviderError("public_http", ConnectionState.ERROR) from exc

                body = bytearray()
                async for chunk in response.aiter_raw():
                    body.extend(chunk)
                    if len(body) > _MAX_BODY_BYTES:
                        raise ProviderError("public_http", ConnectionState.ERROR)

                text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                final_url = normalize_public_url(str(response.url))
                title, markdown = _extract_page(text, content_type, final_url)
                return PublicPage(url=final_url, title=title, markdown=markdown)

    raise ProviderError("public_http", ConnectionState.ERROR)  # pragma: no cover


def _make_public_transport() -> httpx.AsyncBaseTransport:
    transport = httpx.AsyncHTTPTransport(
        verify=True,
        trust_env=False,
        http1=True,
        http2=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        retries=0,
    )
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl.create_default_context(),
        max_connections=1,
        max_keepalive_connections=0,
        http1=True,
        http2=False,
        retries=0,
        network_backend=_PublicNetworkBackend(_resolve_public_addresses),
    )
    return transport


class _PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await self._resolver(host, port)
        return await self._backend.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise OSError("Unix sockets are not valid public targets")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


async def _resolve_public_addresses(host: str, port: int) -> list[str]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(host, port, type=socket.SOCK_STREAM),
        )
        addresses = list({ipaddress.ip_address(result[4][0]) for result in results})
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise ValueError("Target DNS must resolve only to public addresses")
    return [str(address) for address in addresses]


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not address.is_global:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return True
    if address.is_site_local:
        return False
    return all(embedded.is_global for embedded in _embedded_ipv4_addresses(address))


def _embedded_ipv4_addresses(address: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    embedded = [
        candidate for candidate in (address.ipv4_mapped, address.sixtofour) if candidate is not None
    ]
    if address.teredo is not None:
        embedded.extend(address.teredo)
    if address in _IPV4_COMPATIBLE or address in _NAT64_WELL_KNOWN:
        embedded.append(ipaddress.IPv4Address(address.packed[-4:]))
    if address.packed[8:12] in {b"\x00\x00\x5e\xfe", b"\x02\x00\x5e\xfe"}:
        embedded.append(ipaddress.IPv4Address(address.packed[-4:]))
    return embedded


class _PageTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "table",
        "tr",
    }
    _IGNORED_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "title":
            self._in_title = True
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif tag in self._BLOCK_TAGS and not self._ignored_depth:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in self._BLOCK_TAGS and not self._ignored_depth:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if not self._ignored_depth and not self._in_title:
            self.text_parts.append(data)


def _extract_page(text: str, content_type: str, url: str) -> tuple[str, str]:
    if content_type.startswith("text/plain"):
        return urlsplit(url).hostname or url, _normalize_text(text)
    parser = _PageTextParser()
    parser.feed(text)
    title = _normalize_inline(" ".join(parser.title_parts)) or (urlsplit(url).hostname or url)
    return title, _normalize_text("".join(parser.text_parts))


def _normalize_inline(value: str) -> str:
    return " ".join(value.split())


def _normalize_text(value: str) -> str:
    lines = [_normalize_inline(line) for line in value.splitlines()]
    return "\n\n".join(line for line in lines if line)
