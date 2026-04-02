"""
Integrator — Orquestador de ejecución paralela de agentes.

El concepto más importante de este archivo: asyncio.gather
──────────────────────────────────────────────────────────

Imaginá que tenés 3 agentes, cada uno tarda 2 segundos en responder el LLM.

SIN asyncio.gather (secuencial):
  agent1.run() → 2s → agent2.run() → 2s → agent3.run() → 2s
  Total: 6 segundos

CON asyncio.gather (paralelo):
  agent1.run() ─────────────────────── 2s
  agent2.run() ─────────────────────── 2s   } todos a la vez
  agent3.run() ─────────────────────── 2s
  Total: ~2 segundos (el tiempo del más lento)

asyncio.gather toma múltiples coroutines y las ejecuta concurrentemente.

¿Cómo se decide qué agentes activar?
─────────────────────────────────────
Fase 7 introduce TWO niveles de selección:

1. agentes_sugeridos (prioritario) — viene del AgentRouter.
   El LLM leyó el caso y decidió qué especialistas activar.
   CardiologyAgent, PharmacologyAgent, RadiologyAgent se activan POR CONTENIDO.

2. AGENTS_BY_URGENCY (fallback) — cuando no hay sugerencias del router.
   Activación por nivel de urgencia, solo agentes generalistas.

¿Por qué este diseño?
  CardiologyAgent no se activa porque el caso sea CRITICO.
  Se activa porque hay datos de ECG o sospecha de arritmia.
  Esa decisión semántica la hace el LLM del AgentRouter.
  AGENTS_BY_URGENCY es el net de seguridad cuando no hay router.

¿Cómo se combina el resultado?
────────────────────────────────
- summary:          del agente con mayor confidence
- findings:         UNIÓN de todos (sin duplicados, preservando orden)
- red_flags:        UNIÓN de todos — NUNCA se pierde una red_flag
- recommendations:  UNIÓN de todos
- confidence:       promedio
"""

import asyncio
from app.agents.clinical import ClinicalAgent
from app.agents.emergency import EmergencyAgent
from app.agents.diagnosis import DifferentialDiagnosisAgent
from app.agents.cardiology import CardiologyAgent
from app.agents.pharmacology import PharmacologyAgent
from app.agents.radiology import RadiologyAgent
from app.agents.base import BaseAgent
from app.models.clinical import AgentOutput, AnalyzeOutput, NivelUrgencia


# Fallback cuando no llegan agentes_sugeridos del router.
# Los agentes especialistas (Cardiology, Pharmacology, Radiology)
# NO están acá — se activan solo por contenido vía agentes_sugeridos.
AGENTS_BY_URGENCY: dict[NivelUrgencia, list[str]] = {
    NivelUrgencia.CRITICO:      ["EmergencyAgent", "ClinicalAgent", "DifferentialDiagnosisAgent"],
    NivelUrgencia.MUY_URGENTE:  ["EmergencyAgent", "ClinicalAgent"],
    NivelUrgencia.URGENTE:      ["ClinicalAgent", "DifferentialDiagnosisAgent"],
    NivelUrgencia.NO_URGENTE:   ["ClinicalAgent"],
}

# Registro de todos los agentes disponibles.
# Agregar un nuevo agente = una línea acá + reglas en el router.
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "ClinicalAgent":               ClinicalAgent,
    "EmergencyAgent":              EmergencyAgent,
    "DifferentialDiagnosisAgent":  DifferentialDiagnosisAgent,
    "CardiologyAgent":             CardiologyAgent,
    "PharmacologyAgent":           PharmacologyAgent,
    "RadiologyAgent":              RadiologyAgent,
}


def _combine_results(results: list[AgentOutput]) -> AnalyzeOutput:
    """
    Combina los outputs de múltiples agentes en un único AnalyzeOutput.

    Estrategia:
    - summary: del agente con mayor confidence
    - findings/red_flags/recommendations: unión ordenada sin duplicados
      dict.fromkeys() = forma idiomática en Python para deduplicar preservando orden
    - confidence: promedio de todos los agentes
    """
    best = max(results, key=lambda r: r.confidence)

    all_findings = list(dict.fromkeys(f for r in results for f in r.findings))
    all_red_flags = list(dict.fromkeys(f for r in results for f in r.red_flags))
    all_recs = list(dict.fromkeys(f for r in results for f in r.recommendations))
    avg_confidence = sum(r.confidence for r in results) / len(results)

    return AnalyzeOutput(
        summary=best.summary,
        findings=all_findings,
        red_flags=all_red_flags,
        recommendations=all_recs,
        confidence=round(avg_confidence, 4),
        agentes_activados=[r.agent_name for r in results],
        agent_outputs=list(results),
    )


class Integrator:
    """
    Integrator — Fase 7.

    Orquesta la ejecución paralela de agentes clínicos y combina sus resultados.

    Flujo con agentes_sugeridos (path normal — Fase 7):
      agentes_sugeridos=["EmergencyAgent", "CardiologyAgent"]
        → [AGENT_REGISTRY[name]() for name in agentes_sugeridos]
        → asyncio.gather(agent.run() for ...)
        → _combine_results(results)

    Flujo sin agentes_sugeridos (fallback — Fase 6 compatible):
      nivel_urgencia=CRITICO
        → AGENTS_BY_URGENCY[CRITICO] → ["EmergencyAgent", "ClinicalAgent", ...]
        → mismo proceso
    """

    async def analyze(
        self,
        caso_clinico: str,
        agentes_sugeridos: list[str] | None = None,
        nivel_urgencia: NivelUrgencia | None = None,
    ) -> AnalyzeOutput:
        if agentes_sugeridos:
            # Path principal: agentes decididos por el LLM del router
            # Filtramos nombres desconocidos para evitar KeyError si el router alucina
            agent_names = [name for name in agentes_sugeridos if name in AGENT_REGISTRY]
            if not agent_names:
                # Fallback de seguridad: si todos los nombres son inválidos
                agent_names = AGENTS_BY_URGENCY[nivel_urgencia or NivelUrgencia.URGENTE]
        else:
            # Fallback: activación por urgencia
            urgency = nivel_urgencia or NivelUrgencia.URGENTE
            agent_names = AGENTS_BY_URGENCY[urgency]

        agents: list[BaseAgent] = [AGENT_REGISTRY[name]() for name in agent_names]

        results: list[AgentOutput] = list(
            await asyncio.gather(*[agent.run(caso_clinico) for agent in agents])
        )

        return _combine_results(results)
