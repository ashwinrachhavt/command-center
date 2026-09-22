import asyncio
import socket
from collections.abc import AsyncIterator

import httpx
import pytest

from command_center.core.public_urls import normalize_public_url
from command_center.integrations import public_research
from command_center.integrations.clients import FirecrawlClient, ProviderError
from command_center.integrations.public_research import scrape_public


class AsyncChunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/job",
        "http://jobs.localhost/job",
        "http://127.0.0.1/job",
        "http://10.0.0.1/job",
        "http://[::1]/job",
        "http://2130706433/job",
        "http://0x7f000001/job",
        "http://0177.0.0.1/job",
        "https://user@example.com/job",
        "https://example.com:8443/job",
        "ftp://example.com/job",
        "https://127%2e0%2e0%2e1/job",
    ],
)
def test_normalize_public_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_public_url(url)


def test_normalize_public_url_canonicalizes_without_losing_path_or_query() -> None:
    assert (
        normalize_public_url("HTTPS://Jobs.Example.COM.:443/openings/1?ref=search#apply")
        == "https://jobs.example.com/openings/1?ref=search"
    )


def test_scrape_public_extracts_a_bounded_public_page(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert "authorization" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            stream=AsyncChunks(
                [
                    b"""
                <html><head><title> Synthetic Role </title><script>ignore me</script></head>
                <body><main><h1>Staff Engineer</h1><p>Build useful systems.</p></main></body></html>
                    """
                ]
            ),
        )

    monkeypatch.setattr(
        public_research, "_make_public_transport", lambda: httpx.MockTransport(handler)
    )

    async def run() -> None:
        async with httpx.AsyncClient() as provider_http:
            client = FirecrawlClient(provider_http, "http://firecrawl", "must-not-leak")
            page = await scrape_public(client, "https://jobs.example.com/role#apply")
        assert page.url == "https://jobs.example.com/role"
        assert page.title == "Synthetic Role"
        assert page.markdown == "Staff Engineer\n\nBuild useful systems."
        assert page.provider == "public_http"
        assert page.extraction_method == "html_text"

    asyncio.run(run())
    assert seen == ["https://jobs.example.com/role"]


def test_scrape_public_validates_each_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    monkeypatch.setattr(
        public_research, "_make_public_transport", lambda: httpx.MockTransport(handler)
    )

    async def run() -> None:
        async with httpx.AsyncClient() as provider_http:
            with pytest.raises(ValueError):
                await scrape_public(
                    FirecrawlClient(provider_http, "http://firecrawl"),
                    "https://jobs.example.com/role",
                )

    asyncio.run(run())
    assert requests == 1


@pytest.mark.parametrize("streamed", [False, True])
def test_scrape_public_rejects_oversize_responses(
    monkeypatch: pytest.MonkeyPatch, streamed: bool
) -> None:
    body = b"x" * (public_research._MAX_BODY_BYTES + 1)

    def handler(_: httpx.Request) -> httpx.Response:
        if streamed:
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                stream=AsyncChunks([body]),
            )
        return httpx.Response(
            200,
            headers={
                "content-type": "text/plain",
                "content-length": str(public_research._MAX_BODY_BYTES + 1),
            },
        )

    monkeypatch.setattr(
        public_research, "_make_public_transport", lambda: httpx.MockTransport(handler)
    )

    async def run() -> None:
        async with httpx.AsyncClient() as provider_http:
            with pytest.raises(ProviderError):
                await scrape_public(
                    FirecrawlClient(provider_http, "http://firecrawl"),
                    "https://jobs.example.com/role",
                )

    asyncio.run(run())


def test_scrape_public_rejects_encoded_response_without_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TrackingStream(httpx.AsyncByteStream):
        consumed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            self.consumed = True
            yield b"compressed"

    stream = TrackingStream()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": "gzip"},
            stream=stream,
        )

    monkeypatch.setattr(
        public_research, "_make_public_transport", lambda: httpx.MockTransport(handler)
    )

    async def run() -> None:
        async with httpx.AsyncClient() as provider_http:
            with pytest.raises(ProviderError):
                await scrape_public(
                    FirecrawlClient(provider_http, "http://firecrawl"),
                    "https://jobs.example.com/role",
                )

    asyncio.run(run())
    assert stream.consumed is False


def test_scrape_public_rejects_chunked_raw_body_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk_size = public_research._MAX_BODY_BYTES // 2

    class ChunkedStream(httpx.AsyncByteStream):
        chunks_read = 0

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(3):
                self.chunks_read += 1
                yield b"x" * chunk_size

    stream = ChunkedStream()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain", "transfer-encoding": "chunked"},
            stream=stream,
        )

    monkeypatch.setattr(
        public_research, "_make_public_transport", lambda: httpx.MockTransport(handler)
    )

    async def run() -> None:
        async with httpx.AsyncClient() as provider_http:
            with pytest.raises(ProviderError):
                await scrape_public(
                    FirecrawlClient(provider_http, "http://firecrawl"),
                    "https://jobs.example.com/role",
                )

    asyncio.run(run())
    assert stream.chunks_read == 3


@pytest.mark.parametrize("failure", ["transport", "provider"])
def test_scrape_public_maps_failures_to_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "transport":
            raise httpx.ReadTimeout("sensitive upstream detail", request=request)
        return httpx.Response(503, text="sensitive upstream detail")

    monkeypatch.setattr(
        public_research, "_make_public_transport", lambda: httpx.MockTransport(handler)
    )

    async def run() -> None:
        async with httpx.AsyncClient() as provider_http:
            with pytest.raises(ProviderError) as error:
                await scrape_public(
                    FirecrawlClient(provider_http, "http://firecrawl"),
                    "https://jobs.example.com/role",
                )
            assert "sensitive" not in str(error.value)

    asyncio.run(run())


def test_dns_resolution_rejects_any_private_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: answers)

    async def run() -> None:
        with pytest.raises(ValueError, match="public addresses"):
            await public_research._resolve_public_addresses("jobs.example.com", 443)

    asyncio.run(run())


def test_dns_resolution_returns_only_mocked_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: answers)

    assert asyncio.run(public_research._resolve_public_addresses("jobs.example.com", 443)) == [
        "93.184.216.34"
    ]


@pytest.mark.parametrize(
    "address",
    [
        "fec0::1",
        "64:ff9b::10.0.0.1",
        "2001:4860::5efe:10.0.0.1",
        "::10.0.0.1",
    ],
)
def test_ipv6_site_local_and_embedded_private_addresses_are_rejected(address: str) -> None:
    async def run() -> None:
        with pytest.raises(ValueError, match="public addresses"):
            await public_research._resolve_public_addresses(address, 443)

    asyncio.run(run())
