from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración central de la aplicación cargada desde variables de entorno.

    ¿Por qué llm_provider usa str en lugar de LLMProvider directamente?
    ─────────────────────────────────────────────────────────────────────
    Hay una dependencia circular potencial: config.py importaría llm.py, y
    llm.py importa config.py. Para evitarlo, llm_provider sigue siendo `str`
    en el modelo de settings. La validación con el Enum ocurre en create_llm()
    dentro de llm.py, donde se compara el string contra LLMProvider.

    Esta separación es intencional: Settings sabe QUÉ está configurado,
    create_llm() sabe QUÉ HACER con esa configuración.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "Clinical AI Multi-Agent"
    app_version: str = "0.1.0"
    debug: bool = False

    # LLM Providers (todos opcionales — usás el que tengas)
    openai_api_key: str = ""
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    lmstudio_base_url: str = "http://localhost:1234/v1"

    # Provider activo: "openai" | "groq" | "lmstudio"
    # El tipo es str para evitar dependencia circular con app.core.llm.
    # La validación del valor ocurre en create_llm() usando LLMProvider enum.
    llm_provider: str = "groq"
    llm_model: str = "llama-3.3-70b-versatile"  # default para Groq

    # Embeddings (Fase 4: RAG)
    # text-embedding-3-small: modelo de OpenAI para generar embeddings
    # 1536 dimensiones, buena calidad/precio, compatible con pgvector
    embedding_model: str = "text-embedding-3-small"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
