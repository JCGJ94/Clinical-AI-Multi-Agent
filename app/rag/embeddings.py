"""
Embeddings — convertir texto en vectores numéricos.

¿Qué es un embedding?
Un embedding es una LISTA DE NÚMEROS que representa el "significado" del texto.

Ejemplo con texto médico:
  "dolor torácico"  → [0.23, -0.41, 0.87, 0.12, ...]  (1536 números)
  "angina de pecho" → [0.24, -0.40, 0.85, 0.13, ...]  ← casi idéntico
  "dolor de cabeza" → [-0.91, 0.12, -0.33, 0.55, ...]  ← muy diferente

¿Por qué importa? Porque nos permite buscar por SIGNIFICADO, no por palabras exactas.
Si el médico escribe "molestia retroesternal", el sistema encuentra documentos
sobre "dolor torácico" aunque no comparta ninguna palabra.

Eso es imposible con un buscador tradicional (LIKE, ILIKE, FTS).
Con embeddings, es trivial — solo calculás la distancia entre vectores.

Modelo que usamos:
  text-embedding-3-small (OpenAI)
  - 1536 dimensiones
  - Muy buena relación calidad/precio
  - ~$0.02 por millón de tokens (prácticamente gratis)
  - Funciona excelente para español clínico

Alternativa local (sin internet, 100% privada):
  nomic-embed-text (LM Studio)
  - Cambiar a: OpenAIEmbeddings(base_url=lmstudio_url, api_key="lm-studio", model="nomic-embed-text")
"""

from langchain_openai import OpenAIEmbeddings
from app.core.config import get_settings


def get_embeddings() -> OpenAIEmbeddings:
    """
    Devuelve el modelo de embeddings configurado.

    Necesitás tener OPENAI_API_KEY en tu .env para que funcione.
    Para los tests no es necesario — usamos FakeEmbeddings.
    """
    settings = get_settings()

    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,  # "text-embedding-3-small" por defecto
    )
