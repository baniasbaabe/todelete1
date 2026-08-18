from __future__ import annotations

from mem0.configs.base import MemoryConfig
from mem0.configs.vector_stores.pgvector import PGVectorConfig
from mem0.llms.groq import GroqLLM
from psycopg2.extensions import parse_dsn
from pydantic import ValidationError
from pydantic_settings import BaseSettings
import pytest

from habit_tracker.infrastructure.config.settings import MEM0_CUSTOM_INSTRUCTIONS, Settings

_BASE_SETTINGS: dict[str, object] = {
    "telegram_bot_token": "telegram-test",
    "database_url": "postgresql+asyncpg://u:p@host:5432/db",
    "groq_api_key": "groq-test",
    "jina_api_key": "jina-test",
    "llm_model": "qwen/qwen3.6-27b",
    "llm_temperature": 0.2,
    "jina_embedding_model": "jina-embeddings-v5-text-small",
    "mem0_embedding_dims": 1024,
    "mem0_collection_name": "mem0_jina",
    "mem0_telemetry": False,
    "collector_endpoint": None,
    "enable_tracing": False,
    "webhook_url": None,
    "webhook_secret": None,
    "phoenix_api_key": None,
}


def _settings(**overrides: object) -> Settings:
    return Settings(**(_BASE_SETTINGS | overrides))


def test_settings_is_a_pydantic_settings_model() -> None:
    assert issubclass(Settings, BaseSettings)


def test_settings_can_be_constructed_without_process_environment() -> None:
    settings = _settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_provider_stack_comes_from_typed_settings() -> None:
    settings = _settings()
    config = settings.get_mem0_config()
    embeddings = config["embedder"]["config"]["model"]
    parsed_config = MemoryConfig(**config)

    assert settings.llm_model == "qwen/qwen3.6-27b"
    assert settings.llm_temperature == 0.2
    assert config["llm"]["provider"] == "groq"
    assert config["llm"]["config"]["api_key"] == "groq-test"
    assert config["llm"]["config"]["model"] == "qwen/qwen3.6-27b"
    assert config["llm"]["config"]["max_tokens"] == 512
    assert config["embedder"]["provider"] == "langchain"
    assert embeddings.model_name == "jina-embeddings-v5-text-small"
    assert config["vector_store"]["config"]["embedding_model_dims"] == 1024
    assert config["vector_store"]["config"]["collection_name"] == "mem0_jina"
    assert config["custom_instructions"] == MEM0_CUSTOM_INSTRUCTIONS
    assert "habit-tracking" in config["custom_instructions"]
    assert parsed_config.custom_instructions == MEM0_CUSTOM_INSTRUCTIONS


def test_litellm_model_prefix_is_rejected() -> None:
    with pytest.raises(ValidationError, match="without the groq/ prefix"):
        _settings(llm_model="groq/qwen/qwen3.6-27b")


def test_configured_mem0_groq_adapter_is_importable() -> None:
    assert GroqLLM is not None


class TestWebhookSecretIsRequired:
    """Webhook mode must always authenticate Telegram requests."""

    def test_missing_secret_with_webhook_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="WEBHOOK_SECRET"):
            _settings(webhook_url="https://bot.example.com/webhook", webhook_secret=None)

    def test_empty_secret_with_webhook_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="WEBHOOK_SECRET"):
            _settings(webhook_url="https://bot.example.com/webhook", webhook_secret="")

    def test_both_set_is_accepted(self) -> None:
        settings = _settings(webhook_url="https://bot.example.com/webhook", webhook_secret="s3cret")

        assert settings.webhook_secret == "s3cret"  # noqa: S105

    def test_polling_mode_needs_no_secret(self) -> None:
        assert _settings(webhook_url=None, webhook_secret=None).webhook_url is None


def _conninfo(database_url: str) -> dict:
    """Return the mem0 connection string as libpq itself parses it."""
    config = _settings(database_url=database_url).get_mem0_config()["vector_store"]["config"]
    return parse_dsn(config["connection_string"])


class TestGetMem0Config:
    def test_inherited_query_string_is_dropped(self) -> None:
        """sslmode comes from PGSSLMODE, so it must not survive into the URI."""
        config = _settings(
            database_url="postgresql+asyncpg://u:p@srv.postgres.database.azure.com:5432/db?sslmode=require"
        ).get_mem0_config()["vector_store"]["config"]

        assert "sslmode" not in config["connection_string"]

        parsed = parse_dsn(config["connection_string"])
        assert parsed["dbname"] == "db"
        assert parsed["host"] == "srv.postgres.database.azure.com"
        assert parsed["port"] == "5432"

    def test_percent_encoded_password_survives_as_literal(self) -> None:
        """libpq percent-decodes URI credentials, so the encoded form is correct."""
        parsed = _conninfo("postgresql+asyncpg://user:p%40ss%2Fword@host:5432/db")

        assert parsed["password"] == "p@ss/word"  # noqa: S105
        assert parsed["user"] == "user"

    def test_asyncpg_scheme_is_normalized(self) -> None:
        store = _settings().get_mem0_config()["vector_store"]

        assert store["provider"] == "pgvector"
        assert store["config"]["connection_string"].startswith("postgresql://")


class TestMem0SchemaIsolation:
    """Mem0 tables must stay outside the Alembic-managed public schema."""

    def test_mem0_config_uses_mem0_schema(self) -> None:
        parsed = _conninfo("postgresql+asyncpg://u:p@host:5432/db")

        assert parsed["options"] == "-c search_path=mem0,public"

    def test_search_path_keeps_public_for_the_vector_type(self) -> None:
        parsed = _conninfo("postgresql+asyncpg://u:p@host:5432/db")

        assert parsed["options"].split("search_path=")[1].split(",") == ["mem0", "public"]

    def test_space_is_percent_encoded_not_plus(self) -> None:
        config = _settings().get_mem0_config()["vector_store"]["config"]

        assert "options=-c%20search_path" in config["connection_string"]

    def test_config_is_accepted_by_mem0(self) -> None:
        config = _settings().get_mem0_config()["vector_store"]["config"]

        assert PGVectorConfig(**config).connection_string == config["connection_string"]
