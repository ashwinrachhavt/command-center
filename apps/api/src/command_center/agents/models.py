"""Native LangChain chat-model construction for pinned agent profiles."""

from typing import Any

import httpx
from cohere.core.api_error import ApiError as CohereAPIError
from langchain_cohere import ChatCohere
from langchain_core.exceptions import (
    ContextOverflowError,
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelInvalidRequestError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr

from command_center.agents.config import AgentProfile, ModelProvider
from command_center.core.config import Settings

PROVIDER_ENV: dict[ModelProvider, str] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
}


class UnsupportedToolModel(ValueError):
    """The selected text model cannot participate in an agent tool graph."""


def cohere_tool_model(model: str) -> bool:
    return model.startswith(("command-r", "command-a")) and "translate" not in model


class BoundedChatCohere(ChatCohere):
    """Expose Cohere v2's output bound, which ChatCohere does not model yet."""

    max_tokens: int = Field(ge=1, le=8000)
    # Pass the bound to the SDK as request options; a model field alone has no effect.
    max_retries: int = Field(default=0, ge=0, le=0)

    @property
    def _default_params(self) -> dict[str, Any]:
        return {
            **super()._default_params,
            "max_tokens": self.max_tokens,
            "request_options": {"max_retries": self.max_retries, "timeout_in_seconds": 60},
        }


def provider_secret(settings: Settings, provider: ModelProvider) -> SecretStr:
    return {
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "mistral": settings.mistral_api_key,
        "cohere": settings.cohere_api_key,
    }[provider]


def missing_profile_credentials(settings: Settings, profile: AgentProfile) -> tuple[str, ...]:
    configured = [profile, *profile.specialists.values()]
    missing = {
        PROVIDER_ENV[selected.provider]
        for selected in configured
        if not provider_secret(settings, selected.provider).get_secret_value()
    }
    return tuple(name for name in PROVIDER_ENV.values() if name in missing)


def create_chat_model(
    settings: Settings, profile: AgentProfile, *, http_async_client: httpx.AsyncClient | None = None
) -> BaseChatModel:
    if profile.provider == "cohere" and not cohere_tool_model(profile.model):
        raise UnsupportedToolModel("Choose a Cohere Command model with tool support for agent chat")
    api_key = provider_secret(settings, profile.provider)
    if not api_key.get_secret_value():
        raise ValueError(f"{PROVIDER_ENV[profile.provider]} is not configured")
    if profile.provider == "openai":
        return ChatOpenAI(
            model=profile.model,
            api_key=api_key,
            http_async_client=http_async_client,
            timeout=60,
            max_retries=0,
            max_completion_tokens=profile.max_output_tokens,
            reasoning_effort=(
                profile.reasoning_effort
                if profile.model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))
                else None
            ),
            # GPT-6 reasoning with function tools requires Responses, not Chat Completions.
            use_responses_api=True if profile.model.startswith("gpt-6") else None,
            store=False,
        )
    if profile.provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=profile.model,
            api_key=api_key,
            vertexai=False,
            timeout=60,
            max_retries=0,
            max_output_tokens=profile.max_output_tokens,
        )
    if profile.provider == "mistral":
        return ChatMistralAI(
            model_name=profile.model,
            api_key=api_key,
            timeout=60,
            max_retries=0,
            max_tokens=profile.max_output_tokens,
        )
    return BoundedChatCohere(
        model=profile.model,
        cohere_api_key=api_key,
        timeout_seconds=60,
        max_tokens=profile.max_output_tokens,
    )


def model_failure_code(error: BaseException) -> str:
    """Classify provider failures without persisting their potentially private messages."""
    if isinstance(error, UnsupportedToolModel):
        return "model_tools_unsupported"
    if isinstance(error, CohereAPIError):
        return {
            400: "model_request_rejected",
            401: "model_authentication_failed",
            403: "model_access_denied",
            404: "model_not_found",
            422: "model_request_rejected",
            429: "model_rate_limited",
            498: "model_authentication_failed",
            504: "model_timeout",
        }.get(error.status_code or 0, "model_provider_unavailable")
    for kind, code in (
        (ContextOverflowError, "context_limit"),
        (ModelAuthenticationError, "model_authentication_failed"),
        (ModelPermissionDeniedError, "model_access_denied"),
        (ModelNotFoundError, "model_not_found"),
        (ModelRateLimitError, "model_rate_limited"),
        (ModelTimeoutError, "model_timeout"),
        (ModelConnectionError, "model_connection_failed"),
        (ModelInvalidRequestError, "model_request_rejected"),
        (ModelAPIError, "model_provider_unavailable"),
    ):
        if isinstance(error, kind):
            return code
    return "agent_execution_failed"
