"""
Retriever — búsqueda semántica con PostgreSQL + pgvector.

¿Qué es pgvector?
Una extensión de PostgreSQL que agrega un nuevo tipo de dato: VECTOR.
Y permite hacer búsquedas por similitud entre vectores.

¿Por qué PostgreSQL y no Pinecone, Chroma, Weaviate?
Porque ya tenés PostgreSQL corriendo en Docker para los datos del sistema.
Una sola base de datos para TODO:
  - datos relacionales (casos clínicos, logs, usuarios)
  - vectores (embeddings de guías y prompts clínicos)

No necesitás mantener dos servicios. No pagás por Pinecone. Es así de simple.

¿Cómo funciona PGVectorStore?
  1. Indexación (se hace UNA VEZ al cargar docs):
     texto del chunk → embedding → vector → INSERT en tabla pgvector

  2. Búsqueda (se hace en cada request del agente):
     query del agente → embedding → buscar los K vectores más cercanos
     → devuelve los chunks de texto más relevantes

Singleton pattern (async-safe):
  _store es un módulo-global. La primera llamada a get_vector_store() adquiere
  _store_lock, llama a PGVectorStore.acreate() UNA VEZ, y cachea el resultado.
  Todas las llamadas concurrentes (asyncio.gather) esperan al mismo lock —
  la tabla se crea exactamente una vez, eliminando UniqueViolationError.

Para usar esto necesitás:
  1. PostgreSQL corriendo: docker compose up
  2. API key en .env (para generar embeddings)
  3. Correr el script de indexación (ver app/rag/index.py)
"""

import asyncio

from langchain_postgres import PGVectorStore
from langchain_core.vectorstores import VectorStoreRetriever

from app.rag.embeddings import get_embeddings
from app.core.config import get_settings


# Nombre de la colección en pgvector.
# Una "colección" en PGVectorStore es como una tabla separada de vectores.
# Podríamos tener colecciones distintas para distintos dominios clínicos.
COLLECTION_NAME = "clinical_docs"

# Singleton — creado una sola vez, compartido por todos los agentes.
# None hasta la primera llamada a get_vector_store().
_store: PGVectorStore | None = None

# Lock async para garantizar que solo UN caller ejecuta acreate() bajo concurrencia.
# asyncio.Lock() es liviano y no bloquea el event loop.
_store_lock = asyncio.Lock()


def _get_sync_connection_string() -> str:
    """
    PGVectorStore usa psycopg (psycopg3 sync), no asyncpg.
    La URL de la config tiene +asyncpg — la reemplazamos aquí.

    asyncpg: driver async de Python para PostgreSQL (para SQLAlchemy async)
    psycopg:  driver psycopg3 de Python para PostgreSQL (para PGVectorStore/LangChain)

    Son dos drivers distintos para el mismo PostgreSQL.
    """
    settings = get_settings()
    return settings.database_url.replace("+asyncpg", "+psycopg")


async def get_vector_store() -> PGVectorStore:
    """
    Devuelve el singleton PGVectorStore, inicializando en la primera llamada.

    Double-checked locking pattern:
      1. Chequeo rápido sin lock (fast path — la mayoría de llamadas)
      2. Si _store es None, adquiere el lock y revalida antes de crear
      3. Solo la primera goroutine ejecuta acreate(); las demás esperan y reutilizan

    acreate() ejecuta CREATE TABLE IF NOT EXISTS — safe bajo concurrencia,
    pero con el singleton evitamos incluso esa redundancia.

    PREREQUISITO: PostgreSQL debe estar corriendo.
    Iniciarlo con: docker compose up
    """
    global _store

    # Fast path — singleton ya inicializado
    if _store is not None:
        return _store

    async with _store_lock:
        # Revalidar dentro del lock — otra goroutine pudo haber inicializado ya
        if _store is None:
            psycopg_url = _get_sync_connection_string()
            _store = await PGVectorStore.acreate(
                embeddings=get_embeddings(),
                collection_name=COLLECTION_NAME,
                connection=psycopg_url,
                use_jsonb=True,  # metadata guardada como JSONB — permite filtrar por categoría
            )

    return _store


async def get_retriever(k: int = 3) -> VectorStoreRetriever:
    """
    Devuelve un Retriever listo para usar en una chain LCEL.

    k=3: devuelve los 3 chunks más relevantes para la query.
    Podés aumentar k si querés más contexto, pero más tokens = más costo.

    El Retriever es un Runnable — puede ser parte de una chain:
      retriever | prompt | llm | parser

    Ahora es async porque get_vector_store() es async (inicialización lazy).
    """
    store = await get_vector_store()
    return store.as_retriever(
        search_kwargs={"k": k},
    )


async def index_documents_async(documents: list) -> None:
    """
    Indexa documentos en el vector store de forma asíncrona.

    Cada documento se convierte en un embedding y se guarda en pgvector.
    Esta operación llama a la API de embeddings para generar los vectores.

    Solo necesitás correr esto UNA VEZ (o cuando actualicés los documentos).
    """
    store = await get_vector_store()
    await store.aadd_documents(documents)
