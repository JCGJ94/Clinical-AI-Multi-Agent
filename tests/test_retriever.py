"""
Tests for retriever.py — updated for PGVectorStore singleton migration.

Covers:
- psycopg3 connection string derivation
- async singleton get_vector_store() — single init regardless of concurrency
- concurrency safety: 3 concurrent callers → acreate called exactly once
- get_retriever() async wrapper
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call


DB_URL_ASYNCPG = "postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"
DB_URL_PSYCOPG = "postgresql+psycopg://postgres:postgres@localhost:5432/clinical_ai"


# ─── Connection string helpers ─────────────────────────────────────────────────

def test_psycopg_url_derived_from_asyncpg_url():
    """
    get_vector_store() must derive postgresql+psycopg:// from the configured URL.
    The module-level helper _get_sync_connection_string (or equivalent logic inside
    get_vector_store) MUST replace +asyncpg with +psycopg.
    """
    from app.rag import retriever

    settings = SimpleNamespace(database_url=DB_URL_ASYNCPG)
    with patch("app.rag.retriever.get_settings", return_value=settings):
        # The function was renamed — call the actual helper that still exists
        result = retriever._get_sync_connection_string()

    assert result == DB_URL_PSYCOPG


# ─── RED: async singleton — acreate called exactly once ───────────────────────

async def test_get_vector_store_singleton_calls_acreate_once():
    """
    Two sequential calls to get_vector_store() must reuse the same instance.
    PGVectorStore.acreate must be called exactly once (singleton guarantee).
    """
    import importlib
    import app.rag.retriever as retriever_module

    # Reset module singleton state before test
    retriever_module._store = None

    fake_store = MagicMock()
    fake_store.as_retriever = MagicMock(return_value=object())

    settings = SimpleNamespace(database_url=DB_URL_ASYNCPG)

    with (
        patch("app.rag.retriever.get_settings", return_value=settings),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
    ):
        MockPGVectorStore.acreate = AsyncMock(return_value=fake_store)

        store1 = await retriever_module.get_vector_store()
        store2 = await retriever_module.get_vector_store()

    assert store1 is store2, "get_vector_store() must return the same singleton instance"
    MockPGVectorStore.acreate.assert_called_once(), "acreate must be called exactly once"

    # Cleanup
    retriever_module._store = None


async def test_get_vector_store_concurrent_calls_acreate_exactly_once():
    """
    Three concurrent callers via asyncio.gather must trigger acreate exactly once.
    This is the core race-condition guard from the spec.
    """
    import app.rag.retriever as retriever_module

    # Reset module singleton state before test
    retriever_module._store = None

    fake_store = MagicMock()

    settings = SimpleNamespace(database_url=DB_URL_ASYNCPG)

    with (
        patch("app.rag.retriever.get_settings", return_value=settings),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
    ):
        MockPGVectorStore.acreate = AsyncMock(return_value=fake_store)

        results = await asyncio.gather(
            retriever_module.get_vector_store(),
            retriever_module.get_vector_store(),
            retriever_module.get_vector_store(),
        )

    assert all(r is fake_store for r in results), "All callers must get the same instance"
    assert MockPGVectorStore.acreate.call_count == 1, (
        f"acreate must be called exactly once, got {MockPGVectorStore.acreate.call_count}"
    )

    # Cleanup
    retriever_module._store = None


async def test_get_vector_store_uses_psycopg_connection_string():
    """
    get_vector_store() must pass a postgresql+psycopg:// URL to PGVectorStore.acreate,
    NOT postgresql+asyncpg://.
    """
    import app.rag.retriever as retriever_module

    retriever_module._store = None

    fake_store = MagicMock()
    settings = SimpleNamespace(database_url=DB_URL_ASYNCPG)

    with (
        patch("app.rag.retriever.get_settings", return_value=settings),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
    ):
        MockPGVectorStore.acreate = AsyncMock(return_value=fake_store)
        await retriever_module.get_vector_store()

        call_kwargs = MockPGVectorStore.acreate.call_args.kwargs
        connection = call_kwargs.get("connection", "")

    assert "+asyncpg" not in connection, "Must NOT use asyncpg driver for PGVectorStore"
    assert "+psycopg" in connection, "Must use psycopg3 driver for PGVectorStore"
    assert connection == DB_URL_PSYCOPG

    # Cleanup
    retriever_module._store = None


# ─── RED: async get_retriever() ───────────────────────────────────────────────

async def test_get_retriever_is_async_and_returns_retriever():
    """
    get_retriever() must be an async function that awaits get_vector_store()
    and returns store.as_retriever(...).
    """
    import app.rag.retriever as retriever_module
    import inspect

    assert inspect.iscoroutinefunction(retriever_module.get_retriever), (
        "get_retriever must be async"
    )

    retriever_module._store = None

    fake_store = MagicMock()
    fake_retriever = object()
    fake_store.as_retriever = MagicMock(return_value=fake_retriever)

    settings = SimpleNamespace(database_url=DB_URL_ASYNCPG)

    with (
        patch("app.rag.retriever.get_settings", return_value=settings),
        patch("app.rag.retriever.get_embeddings", return_value=object()),
        patch("app.rag.retriever.PGVectorStore") as MockPGVectorStore,
    ):
        MockPGVectorStore.acreate = AsyncMock(return_value=fake_store)
        result = await retriever_module.get_retriever(k=5)

    assert result is fake_retriever
    fake_store.as_retriever.assert_called_once_with(search_kwargs={"k": 5})

    # Cleanup
    retriever_module._store = None
