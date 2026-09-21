import asyncio
import json

import httpx
import pytest

from command_center.integrations.clients import (
    ConnectionState,
    FirecrawlClient,
    ProviderError,
    SearxngClient,
)


def test_firecrawl_v2_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/scrape"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        assert json.loads(request.content) == {
            "url": "https://example.com",
            "formats": ["markdown"],
            "timeout": 60000,
        }
        return httpx.Response(200, json={"success": True, "data": {"markdown": "Synthetic"}})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await FirecrawlClient(http, "http://firecrawl", "synthetic-key").scrape(
                "https://example.com"
            )
            assert result == {"markdown": "Synthetic"}

    asyncio.run(run())


def test_searxng_json_contract_and_result_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["format"] == "json"
        assert request.url.params["q"] == "synthetic query"
        return httpx.Response(200, json={"results": [{"title": str(i)} for i in range(5)]})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await SearxngClient(http, "http://searxng").search("synthetic query", limit=2)
            assert len(result) == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,state", [(401, "auth_required"), (429, "rate_limited"), (503, "error")]
)
def test_provider_failures_are_safe(status: int, state: str) -> None:
    async def run() -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(status, text="sensitive upstream body")
        )
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(ProviderError) as error:
                await SearxngClient(http, "http://searxng").search("synthetic")
            assert error.value.state.value == state
            assert "sensitive" not in str(error.value)

    asyncio.run(run())


def test_timeout_and_invalid_json_are_handled() -> None:
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
            status = await FirecrawlClient(http, "http://firecrawl").status()
            assert status.state == ConnectionState.UNAVAILABLE
        transport = httpx.MockTransport(lambda _: httpx.Response(200, text="not JSON"))
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(ProviderError):
                await SearxngClient(http, "http://searxng").search("synthetic")

    asyncio.run(run())
