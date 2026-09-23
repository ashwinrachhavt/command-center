import re
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="CC_", extra="ignore", hide_input_in_errors=True
    )

    api_token: SecretStr = Field(min_length=32)
    database_url: str = Field(repr=False)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "api"]
    firecrawl_url: str = "http://127.0.0.1:3002"
    firecrawl_api_key: SecretStr = SecretStr("")
    searxng_url: str = "http://127.0.0.1:8081"
    docling_url: str = "http://127.0.0.1:5001"
    docling_api_key: SecretStr = SecretStr("")
    blob_store_path: Path = Path(".local/blobs")
    research_sandbox_image: str = ""
    pdf_renderer_image: str = ""
    connector_timeout_seconds: float = Field(default=5, gt=0, le=30)
    auth_mode: Literal["clerk", "local"] = "clerk"
    environment: Literal["development", "test", "production"] = "development"
    clerk_issuer: str = ""
    clerk_authorized_parties: list[str] = ["http://localhost:3001", "http://127.0.0.1:3001"]
    migration_database_url: str | None = Field(default=None, repr=False)
    database_pool_mode: Literal["session", "transaction"] = "session"
    openai_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("OPENAI_API_KEY", "CC_OPENAI_API_KEY")
    )
    gemini_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("GEMINI_API_KEY", "CC_GEMINI_API_KEY"),
    )
    google_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("GOOGLE_API_KEY", "CC_GOOGLE_API_KEY"),
    )
    mistral_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("MISTRAL_API_KEY", "CC_MISTRAL_API_KEY"),
    )
    cohere_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("COHERE_API_KEY", "CC_COHERE_API_KEY"),
    )
    composio_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("COMPOSIO_API_KEY", "CC_COMPOSIO_API_KEY"),
    )
    apollo_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("APOLLO_API_KEY", "CC_APOLLO_API_KEY")
    )
    hunter_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("HUNTER_API_KEY", "CC_HUNTER_API_KEY")
    )
    composio_auth_configs: dict[str, str] = {}
    composio_action_timeout_seconds: float = Field(default=30, gt=0, le=60)
    redis_url: str = Field(default="redis://127.0.0.1:56379/0", repr=False)
    internal_api_url: str = "http://127.0.0.1:8000"
    agent_skills_dir: str = "agents/skills"
    agent_config: str = "agents/profiles.toml"
    agent_checkpoint_database_url: str | None = Field(default=None, repr=False)
    agent_dependency_urls: list[str] = []
    web_origin: str = "http://localhost:3001"

    @model_validator(mode="after")
    def validate_auth_mode(self) -> "Settings":
        if not self.gemini_api_key.get_secret_value() and self.google_api_key.get_secret_value():
            self.gemini_api_key = self.google_api_key
        if self.environment == "production" and (
            self.auth_mode != "clerk" or not self.clerk_issuer
        ):
            raise ValueError("Production requires configured Clerk authentication")
        if self.clerk_issuer and not self.clerk_issuer.startswith("https://"):
            raise ValueError("Clerk issuer must use HTTPS")
        return self

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("Use a postgresql+psycopg:// database URL")
        return value

    @field_validator("research_sandbox_image", "pdf_renderer_image")
    @classmethod
    def immutable_execution_image(cls, value: str) -> str:
        if value and not re.fullmatch(r"(?:[a-zA-Z0-9._:/-]+@)?sha256:[0-9a-f]{64}", value):
            raise ValueError("Execution images require an immutable SHA-256 image reference")
        return value

    @field_validator("firecrawl_url", "searxng_url", "docling_url")
    @classmethod
    def validate_provider_url(cls, value: str) -> str:
        # These are operator-controlled service addresses, never scraped target URLs.
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Provider URL must be an absolute HTTP(S) address")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Provider URL must not contain credentials, query or fragment")
        return value.rstrip("/")
