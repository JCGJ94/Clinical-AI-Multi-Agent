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

¿Cómo funciona PGVector?
  1. Indexación (se hace UNA VEZ al cargar docs):
     texto del chunk → embedding → vector → INSERT en tabla pgvector

  2. Búsqueda (se hace en cada request del agente):
     query del agente → embedding → buscar los K vectores más cercanos
     → devuelve los chunks de texto más relevantes

El concepto de "cercanía":
  Se mide con similitud de coseno (ángulo entre vectores).
  Valor entre 0 y 1. Cuanto más cerca de 1, más similar el significado.

Para usar esto necesitás:
  1. PostgreSQL corriendo: docker compose up
  2. OpenAI API key en .env (para generar embeddings)
  3. Correr el script de indexación (ver app/rag/index.py)
"""

from langchain_postgres.vectorstores import PGVector
from langchain_core.vectorstores import VectorStoreRetriever

from app.rag.embeddings import get_embeddings
from app.core.config import get_settings


# Nombre de la colección en pgvector.
# Una "colección" en PGVector es como una tabla separada de vectores.
# Podríamos tener colecciones distintas para distintos dominios clínicos.
COLLECTION_NAME = "clinical_docs"


def _get_sync_connection_string() -> str:
    """
    PGVector usa psycopg (sync), no asyncpg.
    La URL de la config tiene +asyncpg — la reemplazamos aquí.

    asyncpg: driver async de Python para PostgreSQL (para SQLAlchemy async)
    psycopg:  driver sync de Python para PostgreSQL (para PGVector/LangChain)

    Son dos drivers distintos para el mismo PostgreSQL.
    """
    settings = get_settings()
    return settings.database_url.replace("+asyncpg", "+psycopg")


def _get_async_connection_string() -> str:
    """
    Devuelve la URL async original para los paths que usan ainvoke()/async search.

    Los agentes RAG se ejecutan con chains async, así que el vector store también
    tiene que inicializarse en modo async para que LangChain cree _async_engine.
    """
    settings = get_settings()
    return settings.database_url


def get_vector_store() -> PGVector:
    """
    Crea y devuelve el vector store conectado a PostgreSQL.

    PGVector crea automáticamente las tablas necesarias si no existen.
    También habilita la extensión pgvector en la base de datos.

    PREREQUISITO: PostgreSQL debe estar corriendo.
    Iniciarlo con: docker compose up
    """
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=COLLECTION_NAME,
        connection=_get_sync_connection_string(),
        use_jsonb=True,  # metadata guardada como JSONB — permite filtrar por categoría
    )


def get_async_vector_store() -> PGVector:
    """
    Crea un PGVector en modo async para retrievers usados desde chains async.
    """
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=COLLECTION_NAME,
        connection=_get_async_connection_string(),
        use_jsonb=True,
        async_mode=True,
    )


def get_retriever(k: int = 3) -> VectorStoreRetriever:
    """
    Devuelve un Retriever listo para usar en una chain LCEL.

    k=3: devuelve los 3 chunks más relevantes para la query.
    Podés aumentar k si querés más contexto, pero más tokens = más costo.

    El Retriever es un Runnable — puede ser parte de una chain:
      retriever | prompt | llm | parser
    """
    return get_async_vector_store().as_retriever(
        search_kwargs={"k": k},
    )


async def index_documents_async(documents: list) -> None:
    """
    Indexa documentos en el vector store de forma asíncrona.

    Cada documento se convierte en un embedding y se guarda en pgvector.
    Esta operación llama a la API de OpenAI para generar los embeddings.

    Solo necesitás correr esto UNA VEZ (o cuando actualicés los documentos).
    """
    store = get_async_vector_store()
    await store.aadd_documents(documents)
