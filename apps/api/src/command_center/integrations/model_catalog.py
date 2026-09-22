"""Read provider catalogs using server-held credentials; never perform generation."""

import re
from typing import Any

import httpx
from pydantic import BaseModel

from command_center.agents.config import ModelProvider
from command_center.agents.models import provider_secret
from command_center.core.config import Settings


class DiscoveredModel(BaseModel):
    id: str
    name: str
    selectable: bool
    description: str


class ModelCatalogUnavailable(Exception):
    """Safe public error, without upstream URLs, keys or response bodies."""


ENDPOINTS = {
    "openai": "https://api.openai.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "cohere": "https://api.cohere.com/v1/models",
}


def chat_compatible(provider: ModelProvider, row: dict[str, Any], model: str) -> bool:
    if provider == "mistral":
        capabilities = row.get("capabilities", {})
        return bool(capabilities.get("completion_chat") and capabilities.get("function_calling"))
    if provider == "cohere":
        return "chat" in row.get("endpoints", [])
    if provider == "gemini":
        return (
            "generateContent" in row.get("supportedGenerationMethods", [])
            and model.startswith("gemini-")
            and not any(
                part in model
                for part in (
                    "tts",
                    "image",
                    "audio",
                    "transcribe",
                    "robotics",
                    "computer-use",
                    "live",
                )
            )
        )
    # OpenAI's list API exposes IDs rather than capability metadata. Exclude known
    # dedicated endpoint families and Responses-only models from Chat Completions.
    return bool(re.match(r"^(gpt-|chatgpt-|chat-latest$|o[134](?:-|$))", model)) and not any(
        part in model
        for part in (
            "audio",
            "realtime",
            "transcribe",
            "tts",
            "image",
            "instruct",
            "search",
            "deep-research",
            "codex",
            "-pro",
            "live",
        )
    )


async def discover_models(
    settings: Settings, provider: ModelProvider, http: httpx.AsyncClient
) -> list[DiscoveredModel]:
    secret = provider_secret(settings, provider).get_secret_value()
    if not secret:
        raise ModelCatalogUnavailable("Add this provider's API key in Settings to list its models.")
    headers = (
        {"x-goog-api-key": secret}
        if provider == "gemini"
        else {"Authorization": f"Bearer {secret}"}
    )
    params = (
        {"pageSize": "1000"}
        if provider == "gemini"
        else ({"page_size": "1000"} if provider == "cohere" else {})
    )
    models: dict[str, DiscoveredModel] = {}
    try:
        for _ in range(20):
            response = await http.get(
                ENDPOINTS[provider], headers=headers, params=params, timeout=10
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", payload.get("models", []))
            for row in rows:
                model = str(row.get("id") or row.get("name", "")).removeprefix("models/")
                if not model:
                    continue
                compatible = chat_compatible(provider, row, model)
                models[model] = DiscoveredModel(
                    id=model,
                    name=str(row.get("displayName") or row.get("name") or model).removeprefix(
                        "models/"
                    ),
                    selectable=compatible,
                    description="Available for agent chat"
                    if compatible
                    else "Not supported by this agent chat flow",
                )
            token = payload.get("nextPageToken") or payload.get("next_page_token")
            if not token:
                return sorted(models.values(), key=lambda item: (not item.selectable, item.id))
            params["pageToken" if provider == "gemini" else "page_token"] = token
        raise ModelCatalogUnavailable("Provider returned too many catalog pages. Try refreshing.")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403, 498):
            message = "Provider rejected the API key or model-list permission. Check Settings."
        elif exc.response.status_code == 429:
            message = "Provider rate limit reached. Try refreshing shortly."
        else:
            message = "Provider model list is unavailable. Try refreshing."
        raise ModelCatalogUnavailable(message) from None
    except (httpx.RequestError, ValueError, TypeError, AttributeError):
        raise ModelCatalogUnavailable(
            "Could not load the provider model list. Try refreshing."
        ) from None
