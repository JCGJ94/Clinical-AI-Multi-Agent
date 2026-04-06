"""
app.services — Capa de servicios del sistema clínico.

Exporta las clases y funciones más usadas para simplificar los imports:

  from app.services import Integrator

En lugar de:
  from app.services.integrator import Integrator
"""

from app.services.integrator import Integrator, AGENT_REGISTRY, AGENTS_BY_URGENCY

__all__ = [
    "Integrator",
    "AGENT_REGISTRY",
    "AGENTS_BY_URGENCY",
]
