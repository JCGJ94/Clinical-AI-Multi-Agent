from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
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
    llm_provider: str = "groq"
    llm_model: str = "llama-3.3-70b-versatile"  # default para Groq

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_ai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
