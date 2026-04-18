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

Fase 9: Resiliencia ante fallos parciales
─────────────────────────────────────────
Problema original: asyncio.gather(*tasks) explota si CUALQUIER agente falla.
Si EmergencyAgent lanza una excepción, perdemos los resultados de ClinicalAgent
y DifferentialDiagnosisAgent aunque estos hayan respondido correctamente.

Solución: asyncio.gather(*tasks, return_exceptions=True)
Con este flag, en lugar de propagar la primera excepción, gather DEVUELVE
los resultados mezclados: AgentOutput donde funcionó, Exception donde falló.

Luego procesamos la lista:
  - AgentOutput → resultado válido, lo incluimos en la combinación
  - Exception   → lo envolvemos en AgentExecutionError con el nombre del agente

Escenarios posibles:
  1. TODOS exitosos     → comportamiento original, sin cambios
  2. ALGUNOS fallidos   → resultado parcial con warnings + failed_agents poblado
  3. TODOS fallidos     → raise AllAgentsFailedError (no hay nada que combinar)

Timeout por agente:
  asyncio.wait_for(coroutine, timeout=AGENT_TIMEOUT) envuelve cada coroutine
  con un deadline. Si el agente no responde en ese tiempo → asyncio.TimeoutError.
  El TimeoutError se trata igual que cualquier otro fallo del agente.
  Default: 30 segundos (configurable via AGENT_TIMEOUT).
"""

import asyncio
import logging
import time
from app.agents.clinical import ClinicalAgent
from app.agents.emergency import EmergencyAgent
from app.agents.diagnosis import DifferentialDiagnosisAgent
from app.agents.cardiology import CardiologyAgent
from app.agents.pharmacology import PharmacologyAgent
from app.agents.radiology import RadiologyAgent
from app.agents.base import BaseAgent
from app.models.clinical import AgentOutput, AnalyzeOutput, NivelUrgencia
from app.core.exceptions import AgentExecutionError, AllAgentsFailedError
from app.core.logging import get_logger

logger: logging.Logger = get_logger(__name__)

# Timeout en segundos por agente.
# 30 segundos es generoso para llamadas LLM — ajustar según el provider.
# Groq es rápido (~3-5s), OpenAI puede tardar más en picos de carga.
AGENT_TIMEOUT: float = 30.0

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

    Nota: esta función trabaja solo con resultados exitosos (AgentOutput).
    Los fallos se manejan ANTES de llamar a esta función — _combine_results
    no conoce los agentes que fallaron.
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


async def _safe_run(agent: BaseAgent, agent_name: str, caso_clinico: str, timeout: float) -> AgentOutput:
    """
    Ejecuta un agente con timeout y convierte cualquier excepción en AgentExecutionError.

    ¿Por qué este wrapper?
    ───────────────────────
    asyncio.gather con return_exceptions=True ya captura excepciones, pero
    necesitamos DOS cosas extra:
      1. Agregar el nombre del agente al error (para saber QUÉ agente falló)
      2. Aplicar un timeout por agente (asyncio.wait_for)

    Este wrapper combina ambas responsabilidades en un solo lugar.

    Flujo:
      _safe_run(agent, "CardiologyAgent", caso, 30.0)
        → asyncio.wait_for(agent.run(caso), timeout=30.0)
        → Si responde en tiempo → devuelve AgentOutput
        → Si timeout           → asyncio.TimeoutError → AgentExecutionError("CardiologyAgent", ...)
        → Si otro error        → Exception cualquiera → AgentExecutionError("CardiologyAgent", ...)
    """
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(agent.run(caso_clinico), timeout=timeout)
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Agent completed",
            extra={
                "agent_name": agent_name,
                "duration_ms": duration_ms,
                "confidence": result.confidence,
            },
        )
        return result
    except asyncio.TimeoutError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "Agent failed",
            extra={
                "agent_name": agent_name,
                "error_type": "TimeoutError",
                "duration_ms": duration_ms,
            },
        )
        raise AgentExecutionError(
            agent_name=agent_name,
            cause=TimeoutError(f"Timeout después de {timeout}s"),
        ) from exc
    except AgentExecutionError:
        # Si ya es AgentExecutionError, re-lanzamos sin envolver de nuevo
        raise
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "Agent failed",
            extra={
                "agent_name": agent_name,
                "error_type": type(exc).__name__,
                "duration_ms": duration_ms,
            },
        )
        raise AgentExecutionError(agent_name=agent_name, cause=exc) from exc


class Integrator:
    """
    Integrator — Fase 9 (Resiliencia).

    Orquesta la ejecución paralela de agentes clínicos con tolerancia a fallos.

    Flujo con agentes_sugeridos (path normal — Fase 7):
      agentes_sugeridos=["EmergencyAgent", "CardiologyAgent"]
        → [AGENT_REGISTRY[name]() for name in agentes_sugeridos]
        → asyncio.gather(agent.run() for ..., return_exceptions=True)
        → separar successes de failures
        → si algunos fallan: resultado parcial + warnings
        → si todos fallan:   raise AllAgentsFailedError

    Flujo sin agentes_sugeridos (fallback — Fase 6 compatible):
      nivel_urgencia=CRITICO
        → AGENTS_BY_URGENCY[CRITICO] → ["EmergencyAgent", "ClinicalAgent", ...]
        → mismo proceso

    Diferencia clave vs Fase 6/7:
      Antes: asyncio.gather(*tasks)              → explota con el primer fallo
      Ahora: asyncio.gather(*tasks, return_exceptions=True) → recolecta todos
    """

    def __init__(self, agent_timeout: float = AGENT_TIMEOUT) -> None:
        """
        Inicializa el Integrator con un timeout configurable por agente.

        Inyectar el timeout como parámetro (en lugar de usar la constante global)
        hace al Integrator testeable: en tests podemos pasar timeout=0.1 para
        forzar timeouts rápidamente sin esperar los 30 segundos reales.
        """
        self.agent_timeout = agent_timeout

    async def analyze(
        self,
        caso_clinico: str,
        agentes_sugeridos: list[str] | None = None,
        nivel_urgencia: NivelUrgencia | None = None,
    ) -> AnalyzeOutput:
        """
        Analiza un caso clínico ejecutando múltiples agentes en paralelo.

        Retorna un AnalyzeOutput con:
          - agentes_activados: los que respondieron exitosamente
          - failed_agents: los que fallaron (vacío si todos exitosos)
          - warnings: mensajes sobre degradaciones (vacío si todos exitosos)

        Lanza AllAgentsFailedError si ningún agente pudo responder.
        """
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

        logger.info(
            "Starting analysis",
            extra={
                "agent_count": len(agent_names),
                "agents": agent_names,
                "urgencia": nivel_urgencia.value if nivel_urgencia else None,
            },
        )

        total_start = time.perf_counter()
        agents: list[BaseAgent] = [AGENT_REGISTRY[name]() for name in agent_names]

        # return_exceptions=True: en lugar de propagar el primer error,
        # gather devuelve una lista mixta de AgentOutput y Exception.
        # Esto nos permite procesar resultados parciales.
        raw_results: list[AgentOutput | BaseException] = list(
            await asyncio.gather(
                *[_safe_run(agent, name, caso_clinico, self.agent_timeout)
                  for agent, name in zip(agents, agent_names)],
                return_exceptions=True,
            )
        )

        # Separamos éxitos de fallos
        successes: list[AgentOutput] = []
        failures: list[tuple[str, Exception]] = []

        for agent_name, result in zip(agent_names, raw_results):
            if isinstance(result, AgentOutput):
                successes.append(result)
            else:
                # result es una excepción (BaseException subtype)
                exc = result if isinstance(result, Exception) else Exception(str(result))
                failures.append((agent_name, exc))
                logger.error(
                    "Agente '%s' falló: %s",
                    agent_name,
                    exc,
                )

        # Si TODOS fallaron, no podemos construir un resultado útil
        if not successes:
            failed_names = [name for name, _ in failures]
            failed_errors = [err for _, err in failures]
            logger.error(
                "All agents failed",
                extra={"failed_count": len(failed_names)},
            )
            raise AllAgentsFailedError(agent_names=failed_names, errors=failed_errors)

        # Construimos el resultado combinado con los agentes exitosos
        output = _combine_results(successes)

        # Si algunos fallaron, enriquecemos el output con la información de fallos
        if failures:
            output.failed_agents = [name for name, _ in failures]
            output.warnings = [
                f"Agente '{name}' no pudo completar el análisis: {err}"
                for name, err in failures
            ]
            logger.warning(
                "Resultado parcial: %d agentes exitosos, %d fallidos (%s)",
                len(successes),
                len(failures),
                ", ".join(output.failed_agents),
            )

        total_duration_ms = int((time.perf_counter() - total_start) * 1000)
        logger.info(
            "Analysis complete",
            extra={
                "confidence": output.confidence,
                "succeeded": len(successes),
                "failed": len(failures),
                "total_duration_ms": total_duration_ms,
            },
        )

        return output
