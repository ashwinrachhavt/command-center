"""Connection initiation stays actor-scoped and returns to the app workspace."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from command_center.core.identity import Identity, authenticate
from command_center.main import create_app


@pytest.fixture
def connection_client(settings, mocker):
    actor_id = uuid4()
    settings.composio_api_key = SecretStr("synthetic-composio-key")
    settings.composio_auth_configs = {"gmail": "ac_synthetic"}
    initiate = mocker.Mock(
        return_value=SimpleNamespace(redirect_url="https://connect.example.test/authorize")
    )
    constructor = mocker.patch(
        "composio.Composio",
        return_value=SimpleNamespace(connected_accounts=SimpleNamespace(initiate=initiate)),
    )
    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: Identity(actor_id, "synthetic")
    # No lifespan/provider/database work is needed to test this HTTP boundary.
    return TestClient(app), settings, actor_id, initiate, constructor


def test_connect_uses_current_actor_and_returns_to_connections(connection_client):
    client, settings, actor_id, initiate, _ = connection_client
    response = client.post("/api/v1/integrations/composio/connect", json={"toolkit": "gmail"})
    assert response.status_code == 200, response.text
    assert response.json() == {"redirect_url": "https://connect.example.test/authorize"}
    initiate.assert_called_once_with(
        user_id=str(actor_id),
        auth_config_id="ac_synthetic",
        callback_url=settings.web_origin + "/connections?connected=1",
    )


def test_unconfigured_app_does_not_start_provider_connection(connection_client):
    client, _, _, initiate, constructor = connection_client
    response = client.post("/api/v1/integrations/composio/connect", json={"toolkit": "notion"})
    assert response.status_code == 422
    initiate.assert_not_called()
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        None,
        "/relative",
        "javascript:alert(1)",
        "http://connect.example.test",
        "https://x:y@connect.example.test",
    ],
)
def test_invalid_provider_redirect_does_not_reach_browser(connection_client, url):
    client, _, _, initiate, _ = connection_client
    initiate.return_value = SimpleNamespace(redirect_url=url)
    response = client.post("/api/v1/integrations/composio/connect", json={"toolkit": "gmail"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Composio could not start the connection"}


def test_provider_error_is_recoverable_and_does_not_leak_details(connection_client):
    client, _, _, initiate, _ = connection_client
    initiate.side_effect = RuntimeError("private provider debug body")
    response = client.post("/api/v1/integrations/composio/connect", json={"toolkit": "gmail"})
    assert response.status_code == 502
    assert "private" not in response.text
