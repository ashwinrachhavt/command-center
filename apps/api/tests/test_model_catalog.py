"""Synthetic provider model discovery contracts."""

import asyncio

import httpx
import pytest
from pydantic import SecretStr

from command_center.integrations.model_catalog import ModelCatalogUnavailable, discover_models


def test_aya_chat_models_are_not_selectable_for_tool_using_agents():
    from command_center.integrations.model_catalog import chat_compatible

    assert not chat_compatible("cohere", {"endpoints": ["chat"]}, "c4ai-aya-expanse-32b")
    assert chat_compatible("cohere", {"endpoints": ["chat"]}, "command-a-03-2025")


def test_gemini_discovery_paginates_and_disables_non_chat_models(settings):
    settings = settings.model_copy(update={"gemini_api_key": SecretStr("synthetic-key")})

    def respond(request):
        assert request.headers["x-goog-api-key"] == "synthetic-key"
        if request.url.params.get("pageToken") == "next":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-synthetic-pro",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "nextPageToken": "next",
                "models": [
                    {
                        "name": "models/gemini-synthetic-flash",
                        "displayName": "Synthetic Flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-synthetic",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                    {
                        "name": "models/gemini-synthetic-tts",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                ],
            },
        )

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await discover_models(settings, "gemini", http)

    models = asyncio.run(check())
    assert {m.id for m in models if m.selectable} == {
        "gemini-synthetic-flash",
        "gemini-synthetic-pro",
    }
    assert len(models) == 4


def test_other_catalogs_include_all_models_and_flag_agent_compatibility(settings):
    fixtures = {
        "openai": {"data": [{"id": "gpt-5-mini"}, {"id": "text-embedding-3-small"}]},
        "mistral": {
            "data": [
                {
                    "id": "synthetic-chat",
                    "capabilities": {"completion_chat": True, "function_calling": True},
                },
                {"id": "synthetic-embed", "capabilities": {"completion_chat": False}},
            ]
        },
        "cohere": {
            "models": [
                {"name": "command-r-synthetic", "endpoints": ["chat"]},
                {"name": "synthetic-embed", "endpoints": ["embed"]},
            ]
        },
    }

    async def check():
        for provider, payload in fixtures.items():
            configured = settings.model_copy(update={f"{provider}_api_key": SecretStr("synthetic")})
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request, payload=payload: httpx.Response(200, json=payload)
                )
            ) as http:
                models = await discover_models(configured, provider, http)
            assert len(models) == 2
            assert [model.selectable for model in models] == [True, False]

    asyncio.run(check())


def test_cohere_catalog_follows_pagination(settings):
    configured = settings.model_copy(update={"cohere_api_key": SecretStr("synthetic")})

    def respond(request):
        if request.url.params.get("page_token") == "next":
            return httpx.Response(200, json={"models": [{"name": "second", "endpoints": ["chat"]}]})
        return httpx.Response(
            200,
            json={"next_page_token": "next", "models": [{"name": "first", "endpoints": ["chat"]}]},
        )

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await discover_models(configured, "cohere", http)

    assert [model.id for model in asyncio.run(check())] == ["first", "second"]


def test_catalog_errors_never_expose_credentials_or_upstream_bodies(settings):
    configured = settings.model_copy(update={"openai_api_key": SecretStr("synthetic-private-key")})

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="synthetic-private-key")
            )
        ) as http:
            with pytest.raises(ModelCatalogUnavailable) as error:
                await discover_models(configured, "openai", http)
            assert "synthetic-private-key" not in str(error.value)
            assert "API key" in str(error.value)

    asyncio.run(check())
