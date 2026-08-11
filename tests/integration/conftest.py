from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
import psycopg2
from psycopg2 import sql
import pytest
import pytest_asyncio
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer
import vcr as vcrpy
from vcr import VCR
from vcr.cassette import Cassette

from alembic import command
from habit_tracker.infrastructure.config.settings import Settings
from tests.settings import IntegrationTestSettings

PROJECT_ROOT = Path(__file__).parents[2]
CASSETTE_DIR = Path(__file__).parent / "cassettes"


@pytest.fixture(scope="session")
def app_settings(integration_test_settings: IntegrationTestSettings) -> Settings:
    return Settings(
        telegram_bot_token="telegram-test",
        database_url="postgresql+asyncpg://u:p@host:5432/db",
        groq_api_key=integration_test_settings.groq_api_key,
        jina_api_key=integration_test_settings.jina_api_key,
        llm_model="qwen/qwen3.6-27b",
        llm_temperature=0.2,
        jina_embedding_model="jina-embeddings-v5-text-small",
        mem0_embedding_dims=1024,
        mem0_collection_name="mem0_jina",
        mem0_telemetry=False,
        collector_endpoint=None,
        enable_tracing=False,
        webhook_url=None,
        webhook_secret=None,
        phoenix_api_key=None,
    )


@pytest.fixture(scope="session")
def integration_test_settings() -> IntegrationTestSettings:
    return IntegrationTestSettings()


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    """Run one real pgvector PostgreSQL instance for the integration suite."""
    with PostgresContainer("pgvector/pgvector:pg17") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_sync_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session")
def postgres_async_url(postgres_sync_url: str) -> str:
    return postgres_sync_url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture(scope="session")
def migrated_postgres(postgres_sync_url: str) -> None:
    """Apply the production Alembic migrations to the Testcontainer database."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.attributes["database_url"] = postgres_sync_url
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def test_engine(
    postgres_async_url: str,
    migrated_postgres: None,
) -> AsyncGenerator[AsyncEngine]:
    engine = create_async_engine(postgres_async_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Isolate repository tests while still allowing repository commits."""
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False, autoflush=False) as session:
            yield session
        if transaction.is_active:
            await transaction.rollback()


@pytest.fixture
def unmigrated_postgres_engine(postgres_sync_url: str) -> Generator[Engine]:
    """Create a clean PostgreSQL database with no Alembic metadata."""
    database_name = f"migration_check_{uuid4().hex}"
    admin_url = make_url(postgres_sync_url)
    psycopg_url = admin_url.set(drivername="postgresql")
    raw_connection = psycopg2.connect(psycopg_url.render_as_string(hide_password=False))
    raw_connection.autocommit = True
    try:
        with raw_connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    finally:
        raw_connection.close()

    database_url = admin_url.set(database=database_name)
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        raw_connection = psycopg2.connect(psycopg_url.render_as_string(hide_password=False))
        raw_connection.autocommit = True
        try:
            with raw_connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
        finally:
            raw_connection.close()


@pytest.fixture(scope="session")
def vcr_config() -> VCR:
    CASSETTE_DIR.mkdir(exist_ok=True)
    return vcrpy.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        filter_headers=[
            "authorization",
            "api-key",
            "x-api-key",
            "accept-encoding",
            "content-length",
            "user-agent",
            "x-stainless-arch",
            "x-stainless-async",
            "x-stainless-lang",
            "x-stainless-os",
            "x-stainless-package-version",
            "x-stainless-read-timeout",
            "x-stainless-retry-count",
            "x-stainless-runtime",
            "x-stainless-runtime-version",
        ],
        filter_query_parameters=["key", "api_key"],
        before_record_response=_scrub_provider_response,
        decode_compressed_response=True,
        ignore_hosts=["localhost", "127.0.0.1", "unix", "docker"],
        record_mode="none",
        match_on=["method", "scheme", "host", "port", "path", "body"],
    )


@pytest.fixture
def cassette(
    request: pytest.FixtureRequest,
    vcr_config: VCR,
    integration_test_settings: IntegrationTestSettings,
) -> Generator[Cassette]:
    """Replay a committed HTTP recording, or explicitly record a new one."""
    module_dir = CASSETTE_DIR / request.node.path.stem
    module_dir.mkdir(exist_ok=True)
    path = module_dir / f"{request.node.name}.yaml"
    recording = integration_test_settings.record_cassettes
    if not path.exists() and not recording:
        pytest.fail(
            f"Missing VCR cassette {path.relative_to(PROJECT_ROOT)}. "
            "Re-run with RECORD_CASSETTES=1 and the real provider API key."
        )

    relative_path = path.relative_to(CASSETTE_DIR)
    with vcr_config.use_cassette(str(relative_path), record_mode="once" if recording else "none") as recorded:
        yield recorded

    if recording:
        _discard_if_the_api_refused_us(path, recorded)


def _discard_if_the_api_refused_us(path: Path, recorded: Cassette) -> None:
    """Discard a new cassette when the provider returned an HTTP error."""
    failed = [response["status"]["code"] for response in recorded.responses if response["status"]["code"] >= 400]
    if not failed:
        return
    path.unlink(missing_ok=True)


def _scrub_provider_response(response: dict) -> dict:
    """Remove volatile provider metadata while preserving replay behavior."""
    response["headers"] = {
        name: value for name, value in response.get("headers", {}).items() if name.lower() == "content-type"
    }

    body = response.get("body", {})
    raw = body.get("string")
    if not isinstance(raw, (bytes, str)):
        return response

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response
    if not isinstance(payload, dict) or payload.get("object") != "chat.completion":
        return response

    payload["id"] = "chatcmpl-vcr"
    payload["created"] = 0
    payload["system_fingerprint"] = "fp_vcr"
    payload.pop("service_tier", None)

    groq_metadata = payload.get("x_groq")
    if isinstance(groq_metadata, dict):
        groq_metadata["id"] = "req_vcr"
        groq_metadata["seed"] = 0

    usage = payload.get("usage")
    if isinstance(usage, dict):
        for field in ("queue_time", "prompt_time", "completion_time", "total_time"):
            if field in usage:
                usage[field] = 0

    body["string"] = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return response
