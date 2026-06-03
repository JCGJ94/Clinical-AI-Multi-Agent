"""
Tests for retriever.py — PGVectorStore singleton (langchain-postgres >= 0.0.14 API).

API contract:
  - PGEngine.from_connection_string(url=asyncpg_url) — connection pool
  - engine.init_vectorstore_table(table_name, vector_size) — idempotent table creation
  - await PGVectorStore.create(engine, table_name, embedding_service) — store
  - Singleton: create called exactly once regardless of concurrency
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


DB_URL_ASYNCPG = "postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"

FAKE_SETTINGS = SimpleNamespace(
    database_url=DB_URL_ASYNCPG,
    embedding_dimensions=1024,
)


def _make_fake_engine():
    engine = MagicMock()
    engine.init_vectorstore_table = MagicMock()
    return engine


def _make_fake_store():
    store = MagicMock()
    store.as_retriever = MagicMock(return_value=object())
    return store


# ─── Engine uses asyncpg URL ──────────────────────────────────────────────────

async def test_pg_engine_receives_asyncpg_url():
    """PGEngine.from_connection_string must receive the original asyncpg URL."""
    import app.rag.retriever as retriever_module

    retriever_module._store = None
    retriever_module._engine = None

    fake_engine = _make_fake_engine()
    fake_store = _make_fake_store()

    with (
        patch("app.rag.retriever.get_settings", return_value=FAKE_SETTINGS),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGEngine") as MockPGEngine,
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
        patch("app.rag.retriever.asyncio.to_thread", new_callable=AsyncMock),
    ):
        MockPGEngine.from_connection_string.return_value = fake_engine
        MockPGVectorStore.create = AsyncMock(return_value=fake_store)

        await retriever_module.get_vector_store()

        MockPGEngine.from_connection_string.assert_called_once_with(url=DB_URL_ASYNCPG)

    retriever_module._store = None
    retriever_module._engine = None


# ─── Singleton: create called exactly once ───────────────────────────────────

async def test_get_vector_store_singleton_calls_create_once():
    """Two sequential calls must reuse the same instance — create called once."""
    import app.rag.retriever as retriever_module

    retriever_module._store = None
    retriever_module._engine = None

    fake_engine = _make_fake_engine()
    fake_store = _make_fake_store()

    with (
        patch("app.rag.retriever.get_settings", return_value=FAKE_SETTINGS),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGEngine") as MockPGEngine,
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
        patch("app.rag.retriever.asyncio.to_thread", new_callable=AsyncMock),
    ):
        MockPGEngine.from_connection_string.return_value = fake_engine
        MockPGVectorStore.create = AsyncMock(return_value=fake_store)

        store1 = await retriever_module.get_vector_store()
        store2 = await retriever_module.get_vector_store()

    assert store1 is store2, "must return the same singleton instance"
    MockPGVectorStore.create.assert_called_once()

    retriever_module._store = None
    retriever_module._engine = None


# ─── Concurrency: 3 concurrent callers → create called exactly once ──────────

async def test_get_vector_store_concurrent_calls_create_exactly_once():
    """Three concurrent callers via asyncio.gather must trigger create exactly once."""
    import app.rag.retriever as retriever_module

    retriever_module._store = None
    retriever_module._engine = None

    fake_engine = _make_fake_engine()
    fake_store = _make_fake_store()

    with (
        patch("app.rag.retriever.get_settings", return_value=FAKE_SETTINGS),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGEngine") as MockPGEngine,
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
        patch("app.rag.retriever.asyncio.to_thread", new_callable=AsyncMock),
    ):
        MockPGEngine.from_connection_string.return_value = fake_engine
        MockPGVectorStore.create = AsyncMock(return_value=fake_store)

        results = await asyncio.gather(
            retriever_module.get_vector_store(),
            retriever_module.get_vector_store(),
            retriever_module.get_vector_store(),
        )

    assert all(r is fake_store for r in results), "all callers must get the same instance"
    assert MockPGVectorStore.create.call_count == 1, (
        f"create must be called exactly once, got {MockPGVectorStore.create.call_count}"
    )

    retriever_module._store = None
    retriever_module._engine = None


# ─── init_vectorstore_table uses correct args ─────────────────────────────────

async def test_init_vectorstore_table_called_with_correct_args():
    """init_vectorstore_table must receive table name and embedding_dimensions from settings."""
    import app.rag.retriever as retriever_module

    retriever_module._store = None
    retriever_module._engine = None

    fake_engine = _make_fake_engine()
    fake_store = _make_fake_store()
    captured = {}

    async def fake_to_thread(fn, *args, **kwargs):
        captured["fn"] = fn
        captured["args"] = args
        captured["kwargs"] = kwargs
        fn(*args, **kwargs)

    with (
        patch("app.rag.retriever.get_settings", return_value=FAKE_SETTINGS),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGEngine") as MockPGEngine,
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
        patch("app.rag.retriever.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        MockPGEngine.from_connection_string.return_value = fake_engine
        MockPGVectorStore.create = AsyncMock(return_value=fake_store)

        await retriever_module.get_vector_store()

    fake_engine.init_vectorstore_table.assert_called_once_with(
        table_name="clinical_docs",
        vector_size=1024,
    )

    retriever_module._store = None
    retriever_module._engine = None


# ─── get_retriever is async ───────────────────────────────────────────────────

async def test_get_retriever_is_async_and_returns_retriever():
    """get_retriever() must be async and return store.as_retriever(k=...)."""
    import app.rag.retriever as retriever_module
    import inspect

    assert inspect.iscoroutinefunction(retriever_module.get_retriever), (
        "get_retriever must be async"
    )

    retriever_module._store = None
    retriever_module._engine = None

    fake_engine = _make_fake_engine()
    fake_retriever = object()
    fake_store = MagicMock()
    fake_store.as_retriever = MagicMock(return_value=fake_retriever)

    with (
        patch("app.rag.retriever.get_settings", return_value=FAKE_SETTINGS),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGEngine") as MockPGEngine,
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
        patch("app.rag.retriever.asyncio.to_thread", new_callable=AsyncMock),
    ):
        MockPGEngine.from_connection_string.return_value = fake_engine
        MockPGVectorStore.create = AsyncMock(return_value=fake_store)

        result = await retriever_module.get_retriever(k=5)

    assert result is fake_retriever
    fake_store.as_retriever.assert_called_once_with(search_kwargs={"k": 5})

    retriever_module._store = None
    retriever_module._engine = None
