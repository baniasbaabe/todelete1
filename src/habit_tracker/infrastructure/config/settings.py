from __future__ import annotations

from typing import Any
import urllib.parse

from langchain_community.embeddings import JinaEmbeddings
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Schema that mem0's pgvector store owns. It is created, and owned by the
# habit_app role, in scripts/bootstrap-db-roles.sh.
MEM0_SCHEMA = "mem0"
MEM0_CUSTOM_INSTRUCTIONS = (
    "Store only durable habit-tracking facts: dated completion or skip events, habit names, quantities, "
    "obstacles or reasons, stated preferences or routines, and meaningful changes. Do not store greetings, "
    "generic coaching text, or duplicate restatements."
)


class DatabaseSettings(BaseSettings):
    """Database-only settings used by migration entry points."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(min_length=1)


class Settings(DatabaseSettings):
    """Typed application configuration loaded from constructor values or environment."""

    telegram_bot_token: str = Field(min_length=1)
    groq_api_key: str = Field(min_length=1)
    jina_api_key: str = Field(min_length=1)
    llm_model: str = "qwen/qwen3.6-27b"
    llm_temperature: float = 0.2
    jina_embedding_model: str = "jina-embeddings-v5-text-small"
    mem0_embedding_dims: int = Field(default=1024, gt=0)
    mem0_collection_name: str = "mem0_jina"
    mem0_telemetry: bool = False
    collector_endpoint: str | None = None
    enable_tracing: bool = False
    webhook_url: str | None = None
    webhook_secret: str | None = None
    phoenix_api_key: str | None = None

    @field_validator("llm_model")
    @classmethod
    def validate_native_groq_model(cls, value: str) -> str:
        """Reject LiteLLM-prefixed model IDs unsupported by the native SDK."""
        if not value or value.startswith("groq/"):
            raise ValueError("LLM_MODEL must be a native Groq model ID without the groq/ prefix")
        return value

    @field_validator("collector_endpoint", "webhook_url", "webhook_secret", "phoenix_api_key", mode="before")
    @classmethod
    def normalize_optional_string(cls, value: object) -> object:
        """Treat blank optional environment variables as unset."""
        return None if value == "" else value

    @model_validator(mode="after")
    def require_webhook_secret(self) -> Settings:
        """Fail closed when webhook mode lacks Telegram's verification secret."""
        if self.webhook_url and not self.webhook_secret:
            raise ValueError(
                "WEBHOOK_SECRET is required when WEBHOOK_URL is set: without it "
                "the webhook endpoint accepts unauthenticated requests."
            )
        return self

    def get_mem0_config(self) -> dict:
        """Build Mem0's provider, embedder, and pgvector configuration."""
        url = self.database_url
        # Normalize the scheme for libpq
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        elif url.startswith("postgresql+psycopg2://"):
            url = url.replace("postgresql+psycopg2://", "postgresql://", 1)

        # Drop any inherited query string: libpq options such as sslmode are
        # supplied through the PGSSLMODE and PGSSLROOTCERT environment
        # variables (set in the Dockerfile) so that this connection is verified
        # rather than opportunistic, and the only parameter we want on the URI
        # is the search_path below.
        url = url.split("?", 1)[0]

        # mem0's pgvector store issues unqualified CREATE TABLE on first use
        # and has no migration story, so it needs DDL rights somewhere.
        # Confining it to the mem0 schema — where habit_app is granted CREATE,
        # without owning the schema itself — is what lets the public schema
        # stay DDL-free for the runtime role. public remains
        # on the path because the pgvector extension, and therefore the
        # `vector` type, is installed there.
        #
        # This is a search_path rather than a "schema" config key because
        # mem0's PGVectorConfig rejects unknown fields outright. quote, not
        # quote_plus: libpq percent-decodes URI query values but does not read
        # "+" as a space, so the option would arrive mangled.
        options = "options=" + urllib.parse.quote(f"-c search_path={MEM0_SCHEMA},public", safe="")
        config: dict[str, Any] = {
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "connection_string": f"{url}?{options}",
                    "collection_name": self.mem0_collection_name,
                    "embedding_model_dims": self.mem0_embedding_dims,
                },
            }
        }
        config["embedder"] = {"provider": "langchain", "config": self._mem0_embedder_config()}
        config["llm"] = self._mem0_llm_config()
        config["custom_instructions"] = MEM0_CUSTOM_INSTRUCTIONS

        return config

    def _mem0_embedder_config(self) -> dict:
        """Build Mem0's fixed LangChain Jina embedding configuration."""
        return {
            # JinaEmbeddings' Pydantic validator creates the required session.
            "model": JinaEmbeddings(  # pyrefly: ignore [missing-argument]
                jina_api_key=self.jina_api_key,
                model_name=self.jina_embedding_model,
            )
        }

    def _mem0_llm_config(self) -> dict:
        """Use the same Groq model for Mem0's memory extraction calls."""
        return {
            "provider": "groq",
            "config": {
                "api_key": self.groq_api_key,
                "model": self.llm_model,
                "temperature": self.llm_temperature,
                "max_tokens": 512,
            },
        }
