from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_get_sync_connection_string_uses_psycopg_driver():
    from app.rag import retriever

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"
    )

    with patch("app.rag.retriever.get_settings", return_value=settings):
        assert retriever._get_sync_connection_string() == (
            "postgresql+psycopg://postgres:postgres@localhost:5432/clinical_ai"
        )


def test_get_async_connection_string_preserves_asyncpg_driver():
    from app.rag import retriever

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"
    )

    with patch("app.rag.retriever.get_settings", return_value=settings):
        assert retriever._get_async_connection_string() == settings.database_url


@patch("app.rag.retriever.get_embeddings", return_value=object())
@patch("app.rag.retriever.PGVector")
def test_get_vector_store_disables_runtime_extension_creation(
    MockPGVector, _mock_get_embeddings
):
    from app.rag import retriever

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"
    )
    fake_store = MagicMock()
    MockPGVector.return_value = fake_store

    with patch("app.rag.retriever.get_settings", return_value=settings):
        result = retriever.get_vector_store()

    assert result is fake_store
    MockPGVector.assert_called_once()
    assert MockPGVector.call_args.kwargs["connection"] == (
        "postgresql+psycopg://postgres:postgres@localhost:5432/clinical_ai"
    )
    assert MockPGVector.call_args.kwargs["create_extension"] is False
    assert MockPGVector.call_args.kwargs["use_jsonb"] is True


@patch("app.rag.retriever.get_embeddings", return_value=object())
@patch("app.rag.retriever.PGVector")
def test_get_retriever_builds_async_pgvector(MockPGVector, _mock_get_embeddings):
    from app.rag import retriever

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"
    )
    fake_store = MagicMock()
    fake_retriever = object()
    fake_store.as_retriever.return_value = fake_retriever
    MockPGVector.return_value = fake_store

    with patch("app.rag.retriever.get_settings", return_value=settings):
        result = retriever.get_retriever(k=5)

    assert result is fake_retriever
    MockPGVector.assert_called_once()
    assert MockPGVector.call_args.kwargs["connection"] == settings.database_url
    assert MockPGVector.call_args.kwargs["async_mode"] is True
    assert MockPGVector.call_args.kwargs["create_extension"] is False
    fake_store.as_retriever.assert_called_once_with(search_kwargs={"k": 5})


@patch("app.rag.retriever.get_embeddings", return_value=object())
@patch("app.rag.retriever.PGVector")
def test_get_async_vector_store_disables_runtime_extension_creation(
    MockPGVector, _mock_get_embeddings
):
    from app.rag import retriever

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"
    )
    fake_store = MagicMock()
    MockPGVector.return_value = fake_store

    with patch("app.rag.retriever.get_settings", return_value=settings):
        result = retriever.get_async_vector_store()

    assert result is fake_store
    MockPGVector.assert_called_once()
    assert MockPGVector.call_args.kwargs["connection"] == settings.database_url
    assert MockPGVector.call_args.kwargs["async_mode"] is True
    assert MockPGVector.call_args.kwargs["create_extension"] is False
    assert MockPGVector.call_args.kwargs["use_jsonb"] is True
