"""
RAG Indexer — script one-shot que indexa docs/ en pgvector.

¿Por qué un script separado del API?
─────────────────────────────────────
El indexador hace un trabajo PUNTUAL: leer markdowns → chunkear → generar embeddings
con OpenAI → escribir vectores en pgvector. No es un servicio que corre todo el tiempo.

Meterlo dentro del API significaría:
  - Arrancar el FastAPI cada vez que querés reindexar (overhead inútil)
  - Mezclar código de aplicación con código de data pipeline
  - Dependencia obligatoria de OpenAI API key para levantar el API

Separarlo nos deja:
  - Imagen Docker dedicada con su propio entrypoint
  - Corre solo cuando hace falta (on-demand, via profile=tools en compose)
  - API puede levantar sin OPENAI_API_KEY si no se usa RAG todavía

Ejecución manual:
    python -m scripts.indexer

Ejecución en Docker:
    ./scripts/index-rag.sh
"""

import asyncio

from app.core.logging import setup_logging, get_logger
from app.rag.loader import load_and_split
from app.rag.retriever import index_documents_async


async def main() -> None:
    setup_logging(debug=False)
    logger = get_logger(__name__)

    logger.info("Indexer starting")

    chunks = load_and_split()
    logger.info(
        "Documents loaded and split",
        extra={"chunks": len(chunks)},
    )

    if not chunks:
        logger.warning("No documents found in docs/ — nothing to index")
        return

    await index_documents_async(chunks)

    logger.info(
        "Indexing completed",
        extra={"chunks_indexed": len(chunks)},
    )


if __name__ == "__main__":
    asyncio.run(main())
