"""
app.core — Infraestructura transversal del sistema clínico.

Exporta las clases y funciones más usadas para simplificar los imports:

  from app.core import ClinicalBaseError, AgentExecutionError
  from app.core import async_retry
  from app.core import get_settings

En lugar de:
  from app.core.exceptions import ClinicalBaseError, AgentExecutionError
  from app.core.retry import async_retry
  from app.core.config import get_settings
"""

from app.core.config import get_settings, Settings
from app.core.exceptions import (
    ClinicalBaseError,
    AgentExecutionError,
    AllAgentsFailedError,
    LLMProviderError,
    RAGRetrievalError,
    TriageError,
)
from app.core.retry import async_retry

__all__ = [
    # Config
    "get_settings",
    "Settings",
    # Exceptions
    "ClinicalBaseError",
    "AgentExecutionError",
    "AllAgentsFailedError",
    "LLMProviderError",
    "RAGRetrievalError",
    "TriageError",
    # Retry
    "async_retry",
]
