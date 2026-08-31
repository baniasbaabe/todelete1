"""Mem0, pgvector, Groq, and LangChain Jina exercised with VCR replay."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from urllib.parse import quote

from langchain_community.embeddings import JinaEmbeddings
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from vcr import VCR
from vcr.cassette import Cassette

from habit_tracker.infrastructure.config.settings import Settings
from habit_tracker.infrastructure.memory.mem0_store import Mem0MemoryStore


@pytest.fixture
def mem0_provider_cassette(vcr_config: VCR, integration_test_settings) -> Generator[Cassette]:
    """Replay the shared provider exchange used by Mem0 persistence tests.

    When ``record_cassettes`` is true (set via the ``RECORD_CASSETTES`` env var),
    the fixture records new HTTP interactions against the real Groq and Jina
    APIs and overwrites the committed cassette. Otherwise it replays the
    cassette without recording, which is the default for CI.
    """

    cassette_path = Path(__file__).parent / "cassettes/test_mem0_store/test_store_and_retrieve_real_memory.yaml"
    record_mode = "all" if integration_test_settings.record_cassettes else "none"
    with vcr_config.use_cassette(str(cassette_path), record_mode=record_mode) as recorded:
        yield recorded


@pytest_asyncio.fixture
async def memory_store(
    postgres_sync_url: str,
    test_engine: AsyncEngine,
    tmp_path: Path,
    app_settings: Settings,
) -> AsyncGenerator[Mem0MemoryStore]:
    async with test_engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS mem0 CASCADE"))
        await connection.execute(text("CREATE SCHEMA mem0"))

    postgres_url = postgres_sync_url.replace("postgresql+psycopg2://", "postgresql://").split("?", 1)[0]
    options = quote("-c search_path=mem0,public", safe="")
    config = {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "connection_string": f"{postgres_url}?options={options}",
                "collection_name": "mem0_integration",
                "embedding_model_dims": 1024,
            },
        },
        "llm": {
            "provider": "groq",
            "config": {
                "api_key": app_settings.groq_api_key,
                "model": "qwen/qwen3.6-27b",
                "temperature": 0.2,
            },
        },
        "embedder": {
            "provider": "langchain",
            "config": {
                "model": JinaEmbeddings(
                    jina_api_key=app_settings.jina_api_key,
                    model_name=app_settings.jina_embedding_model,
                )
            },
        },
        "history_db_path": str(tmp_path / "mem0-history.db"),
    }
    store = Mem0MemoryStore(config)
    try:
        yield store
    finally:
        async with test_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS mem0 CASCADE"))


async def test_store_and_retrieve_real_memory(memory_store: Mem0MemoryStore, cassette) -> None:
    await memory_store.store_insight(
        user_id=42,
        insight="I prefer doing my morning run before breakfast.",
        category="preference",
    )

    insights = await memory_store.get_insights(user_id=42)

    assert insights
    assert any("morning run" in insight.content.lower() for insight in insights)
    assert any(insight.category == "preference" for insight in insights)
    assert any("/embeddings" in request.uri for request in cassette.requests)
    assert any(request.uri.endswith("/chat/completions") for request in cassette.requests)


async def test_real_memory_is_isolated_by_user(
    memory_store: Mem0MemoryStore,
    mem0_provider_cassette: Cassette,
) -> None:
    await memory_store.store_insight(
        user_id=42,
        insight="I prefer doing my morning run before breakfast.",
        category="preference",
    )

    stored = await memory_store.get_insights(user_id=42)

    assert stored
    assert any("morning run" in insight.content.lower() for insight in stored)
    assert await memory_store.get_insights(user_id=202) == []
    assert any("/embeddings" in request.uri for request in mem0_provider_cassette.requests)
    assert any(request.uri.endswith("/chat/completions") for request in mem0_provider_cassette.requests)
