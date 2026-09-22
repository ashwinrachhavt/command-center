"""Native LangChain chat-model construction for pinned agent profiles."""

from typing import Any

from langchain_cohere import ChatCohere
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


def create_chat_model(settings: Settings, profile: AgentProfile) -> BaseChatModel:
    api_key = provider_secret(settings, profile.provider)
    if not api_key.get_secret_value():
        raise ValueError(f"{PROVIDER_ENV[profile.provider]} is not configured")
    if profile.provider == "openai":
        return ChatOpenAI(
            model=profile.model,
            api_key=api_key,
            timeout=60,
            max_retries=0,
            max_completion_tokens=profile.max_output_tokens,
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
