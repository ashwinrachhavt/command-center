from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel


class ConnectionState(StrEnum):
    ONLINE = "online"
    UNAVAILABLE = "unavailable"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class ConnectionStatus(BaseModel):
    name: str
    state: ConnectionState


class ProviderError(Exception):
    """Safe provider failure: never expose response bodies, credentials or URLs."""

    def __init__(self, provider: str, state: ConnectionState) -> None:
        self.provider = provider
        self.state = state
        super().__init__(f"{provider}: {state.value}")


def error_state(status: int) -> ConnectionState:
    if status in {401, 403}:
        return ConnectionState.AUTH_REQUIRED
    if status == 429:
        return ConnectionState.RATE_LIMITED
    return ConnectionState.ERROR


class ProviderClient:
    def __init__(self, name: str, http: httpx.AsyncClient, base_url: str) -> None:
        self.name = name
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.http.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.RequestError as exc:
            raise ProviderError(self.name, ConnectionState.UNAVAILABLE) from exc
        if not response.is_success:
            raise ProviderError(self.name, error_state(response.status_code))
        return response

    async def json_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.request(method, path, **kwargs)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Expected object")
            return payload
        except ValueError as exc:
            raise ProviderError(self.name, ConnectionState.ERROR) from exc

    async def health(self, path: str) -> ConnectionStatus:
        try:
            await self.request("GET", path)
        except ProviderError as exc:
            return ConnectionStatus(name=self.name, state=exc.state)
        return ConnectionStatus(name=self.name, state=ConnectionState.ONLINE)


class FirecrawlClient(ProviderClient):
    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str = "") -> None:
        super().__init__("Firecrawl", http, base_url)
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def status(self) -> ConnectionStatus:
        return await self.health("/v0/health/readiness")

    async def scrape(self, url: str) -> dict[str, Any]:
        """Internal adapter only. Callers must validate target policy before use."""
        payload = await self.json_request(
            "POST",
            "/v2/scrape",
            headers=self.headers,
            json={"url": url, "formats": ["markdown"], "timeout": 60000},
            timeout=65,
        )
        data = payload.get("data")
        if payload.get("success") is not True or not isinstance(data, dict):
            raise ProviderError(self.name, ConnectionState.ERROR)
        return data


class SearxngClient(ProviderClient):
    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        super().__init__("SearXNG", http, base_url)

    async def status(self) -> ConnectionStatus:
        return await self.health("/healthz")

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not query.strip() or not 1 <= limit <= 20:
            raise ValueError("Use a non-empty query and limit between 1 and 20")
        payload = await self.json_request(
            "GET", "/search", params={"q": query, "format": "json"}, timeout=30
        )
        results = payload.get("results")
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise ProviderError(self.name, ConnectionState.ERROR)
        return results[:limit]
