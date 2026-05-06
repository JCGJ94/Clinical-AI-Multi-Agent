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

Proveedores soportados (EMBEDDING_PROVIDER en .env):
  "openai"   → text-embedding-3-small (OpenAI Cloud, requiere OPENAI_API_KEY)
               1536 dimensiones, buena relación calidad/precio
               ~$0.02 por millón de tokens (prácticamente gratis)

  "lmstudio"          → nomic-embed-text u otro modelo local (LM Studio)
                        100% privado, sin internet, sin costo de API
                        Requiere LM Studio corriendo en http://localhost:1234/v1
                        La API es compatible con OpenAI — usamos el mismo cliente.

  "openai_compatible" → cualquier API compatible con OpenAI (Nvidia NIM, etc.)
                        Reutiliza LLM_BASE_URL y LLM_API_KEY del .env.
                        Ejemplo: nvidia/llama-3.2-nemoretriever-300m-embed-v1

Patrón Factory (mismo que app.core.llm):
  get_embeddings() lee EMBEDDING_PROVIDER y devuelve el cliente correcto.
  El tipo de retorno es Embeddings (base de LangChain) — el caller no
  necesita saber qué proveedor se usa detrás.
"""

from enum import Enum

from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings


class EmbeddingProvider(str, Enum):
    """
    Enum de proveedores de embeddings soportados.

    str, Enum permite comparar directamente con strings de .env:
      EmbeddingProvider.OPENAI == "openai"  → True

    Agregar un proveedor nuevo = agregar un miembro acá + un branch en get_embeddings().
    """

    OPENAI = "openai"
    LMSTUDIO = "lmstudio"
    OPENAI_COMPATIBLE = "openai_compatible"


def get_embeddings() -> OpenAIEmbeddings:
    """
    Factory que devuelve el modelo de embeddings configurado en .env.

    Lee EMBEDDING_PROVIDER y construye la instancia correcta:
      - "openai"   → OpenAIEmbeddings con api.openai.com
      - "lmstudio" → OpenAIEmbeddings apuntando al servidor local de LM Studio

    Para los tests no es necesario llamar esta función — usamos FakeEmbeddings.
    """
    settings = get_settings()
    provider = settings.embedding_provider

    if provider == EmbeddingProvider.OPENAI_COMPATIBLE:
        # Nvidia NIM, Together.ai, u otra API compatible con OpenAI.
        # Reutiliza LLM_BASE_URL y LLM_API_KEY — misma key que el LLM.
        return OpenAIEmbeddings(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.embedding_model,
        )

    if provider == EmbeddingProvider.LMSTUDIO:
        # LM Studio expone una API compatible con OpenAI para embeddings.
        # api_key="lm-studio" es el placeholder que espera LM Studio.
        # El modelo por defecto es nomic-embed-text, pero puede configurarse.
        return OpenAIEmbeddings(
            base_url=settings.lmstudio_base_url,
            api_key="lm-studio",
            model=settings.embedding_model,
        )

    # Default: OpenAI Cloud
    # Si el proveedor es "openai" o cualquier otro valor no reconocido,
    # usamos el cliente estándar de OpenAI.
    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
    )
