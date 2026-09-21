import httpx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from command_center.api import routes
from command_center.core.config import Settings
from command_center.integrations.clients import FirecrawlClient, SearxngClient
from command_center.main import create_app


def test_authentication_and_host_validation(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/api/v1/system/status").status_code == 401
        response = client.get("/health/live", headers={"Host": "untrusted.example"})
        assert response.status_code == 400


def test_liveness_does_not_claim_database_readiness(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr(routes, "database_is_ready", lambda _: False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}
        assert "x-request-id" in response.headers


def test_status_with_migrated_database_and_provider_failure(
    settings: Settings, engine: Engine
) -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.url.host == "firecrawl" else 503)

    app = create_app(settings)
    with TestClient(app) as client:
        http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
        app.state.firecrawl = FirecrawlClient(http, "http://firecrawl")
        app.state.searxng = SearxngClient(http, "http://searxng")
        response = client.get(
            "/api/v1/system/status",
            headers={"Authorization": f"Bearer {settings.api_token.get_secret_value()}"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "database": "ready",
            "connections": [
                {"name": "Firecrawl", "state": "online"},
                {"name": "SearXNG", "state": "error"},
            ],
        }
        assert client.get("/health/ready").status_code == 200
        assert settings.api_token.get_secret_value() not in response.text
