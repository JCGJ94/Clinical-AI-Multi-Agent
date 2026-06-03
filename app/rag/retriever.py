"""
Retriever — búsqueda semántica con PostgreSQL + pgvector.

¿Por qué PostgreSQL y no Pinecone, Chroma, Weaviate?
Una sola base de datos para datos relacionales Y vectores.
No necesitás mantener dos servicios.

Singleton pattern (async-safe):
  _store es un módulo-global. La primera llamada a get_vector_store() adquiere
  _store_lock, llama a PGVectorStore.create() UNA VEZ, y cachea el resultado.
  Todas las llamadas concurrentes (asyncio.gather) esperan al mismo lock.

API de PGVectorStore (langchain-postgres >= 0.0.14):
  1. PGEngine.from_connection_string(url) — pool de conexiones (asyncpg)
  2. engine.init_vectorstore_table(table_name, vector_size) — crea tabla si no existe
  3. await PGVectorStore.create(engine, table_name, embedding_service) — store listo
"""

import asyncio

from langchain_postgres import PGEngine, PGVectorStore
from langchain_core.vectorstores import VectorStoreRetriever

from app.rag.embeddings import get_embeddings
from app.core.config import get_settings

TABLE_NAME = "clinical_docs"

_engine: PGEngine | None = None
_store: PGVectorStore | None = None
_store_lock = asyncio.Lock()


def _get_engine() -> PGEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        # PGEngine usa asyncpg — misma URL que SQLAlchemy, sin modificar
        _engine = PGEngine.from_connection_string(url=settings.database_url)
    return _engine


async def get_vector_store() -> PGVectorStore:
    """
    Singleton PGVectorStore — inicializado una sola vez por proceso.

    Double-checked locking:
      1. Fast path sin lock (mayoría de llamadas)
      2. Adquiere lock, revalida, crea solo si sigue siendo None
    """
    global _store

    if _store is not None:
        return _store

    async with _store_lock:
        if _store is None:
            settings = get_settings()
            engine = _get_engine()

            # Crea la tabla si no existe — init_vectorstore_table no usa IF NOT EXISTS,
            # así que capturamos DuplicateTableError cuando la tabla ya existe (restart, indexer previo)
            try:
                await asyncio.to_thread(
                    engine.init_vectorstore_table,
                    table_name=TABLE_NAME,
                    vector_size=settings.embedding_dimensions,
                )
            except Exception:
                pass  # tabla ya existe — continuar con la existente

            _store = await PGVectorStore.create(
                engine=engine,
                table_name=TABLE_NAME,
                embedding_service=get_embeddings(),
            )

    return _store


async def get_retriever(k: int = 3) -> VectorStoreRetriever:
    """Devuelve un Retriever listo para cadenas LCEL. k = chunks a recuperar."""
    store = await get_vector_store()
    return store.as_retriever(search_kwargs={"k": k})


async def index_documents_async(documents: list) -> None:
    """Indexa documentos en el vector store. Correr una sola vez (o al actualizar docs)."""
    store = await get_vector_store()
    await store.aadd_documents(documents)
