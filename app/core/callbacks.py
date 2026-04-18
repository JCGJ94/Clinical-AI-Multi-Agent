"""
LangChain Callback Handlers — Fase 10: observabilidad de llamadas LLM.

╔══════════════════════════════════════════════════════════════════════════════╗
║  ¿QUÉ SON LOS CALLBACKS EN LANGCHAIN?                                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Un callback handler es un observador que recibe notificaciones en cada     ║
║  punto del ciclo de vida de una chain o LLM.                                ║
║                                                                              ║
║  Sin callbacks:                                                              ║
║    chain.ainvoke(input) → resultado                                          ║
║    (no sabés cuánto tardó, qué prompt se envió, si hubo error)               ║
║                                                                              ║
║  Con callbacks:                                                              ║
║    chain.ainvoke(input)                                                      ║
║      → on_llm_start (se disparó, con el prompt)                             ║
║      → [LLM processing...]                                                   ║
║      → on_llm_end (terminó, con la respuesta y duración)                    ║
║      → resultado                                                              ║
║                                                                              ║
║  Es el PATRÓN OBSERVER aplicado al sistema de LangChain.                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PATRÓN OBSERVER — la base de los callbacks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

El Observer Pattern (GoF) define:
  - Subject (LangChain LLM): emite eventos
  - Observer (BaseCallbackHandler): recibe y procesa esos eventos

La ventaja fundamental: DESACOPLAMIENTO.
  El LLM no sabe nada del LoggingCallbackHandler.
  El LoggingCallbackHandler no modifica el flujo del LLM.
  Podés agregar 10 observers distintos (logging, métricas, trazado) sin
  tocar el código del LLM — simplemente los registrás como callbacks.

Esto es lo opuesto de envolver cada llamada manualmente:
  ❌ Sin callbacks:
     start = time.perf_counter()
     result = await llm.ainvoke(prompt)  # tenés que hacer esto en 8 agentes
     duration = (time.perf_counter() - start) * 1000
     logger.info("LLM completed", extra={"duration_ms": int(duration)})

  ✅ Con callbacks:
     # Se configura UNA vez en create_llm()
     # Los 8 agentes reciben el logging automáticamente

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CICLO DE VIDA DE UNA CHAIN LCEL CON CALLBACKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cuando ejecutás una chain como:
  prompt | llm | parser

LangChain dispara estos eventos en orden:
  on_chain_start(serialized, inputs)   ← toda la chain empieza
    on_llm_start(serialized, prompts)  ← el LLM recibe el prompt
    on_llm_end(response)               ← el LLM devuelve respuesta
  on_chain_end(outputs)                ← toda la chain termina

Si hay RAG con retriever:
  on_chain_start(serialized, inputs)
    on_retriever_start(serialized, query)
    on_retriever_end(documents)
    on_llm_start(serialized, prompts)
    on_llm_end(response)
  on_chain_end(outputs)

Nosotros implementamos solo los hooks de LLM — suficiente para medir
tiempo de respuesta del modelo y detectar errores de llamada.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
¿POR QUÉ UUID COMO CLAVE DE RUN_ID?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LangChain asigna un UUID único a cada "run" — una ejecución individual
de un componente. Cuando on_llm_start se dispara, recibís ese run_id.
El mismo run_id llega en on_llm_end y on_llm_error.

Esto permite correlacionar start y end de la MISMA llamada aunque se
ejecuten múltiples agentes en paralelo con asyncio.gather:

  ClinicalAgent  run_id=abc → on_llm_start → guarda start_time[abc]
  EmergencyAgent run_id=xyz → on_llm_start → guarda start_time[xyz]
  ClinicalAgent  run_id=abc → on_llm_end   → duration = now - start_time[abc]
  EmergencyAgent run_id=xyz → on_llm_end   → duration = now - start_time[xyz]

Sin UUID como clave no podrías rastrear duraciones con ejecución paralela.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SYNC VS ASYNC CALLBACKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BaseCallbackHandler puede ser sync o async. Si los métodos son sync,
LangChain los ejecuta en un thread pool para no bloquear el event loop.

Para nuestro caso (solo logging y dict operations), sync es perfectamente
apropiado — las operaciones son de microsegundos y no requieren I/O async.
Si necesitaras escribir a una base de datos o enviar métricas a un API,
usarías AsyncCallbackHandler en su lugar.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
¿POR QUÉ ESTO ES MEJOR QUE WRAPPERS MANUALES?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Wrapping manual: tendrías que modificar cada agente
  class ClinicalAgent:
      async def run(self, caso):
          start = time.perf_counter()
          try:
              result = await self.chain.ainvoke(caso)
              logger.info("LLM ok", extra={"duration_ms": ...})
              return result
          except Exception as e:
              logger.error("LLM failed", extra={"error": str(e)})
              raise

→ 8 agentes × código repetido = WET (We Enjoy Typing)

Callback: se configura UNA vez en create_llm(), aplica a todos
  → DRY, no tocás ningún agente
  → Podés agregar/quitar observabilidad sin cambiar lógica de negocio
  → Separación de concerns perfecta (SOLID — S y O)
"""

import time
import logging
from uuid import UUID
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.core.logging import get_logger


logger: logging.Logger = get_logger(__name__)


class LoggingCallbackHandler(BaseCallbackHandler):
    """
    Callback handler que registra el inicio, fin y errores de llamadas LLM.

    Implementa tres hooks del ciclo de vida:
      on_llm_start  → registra el prompt y guarda el tiempo de inicio
      on_llm_end    → calcula la duración y registra la respuesta
      on_llm_error  → registra el error y limpia el estado interno

    Estado interno:
      _start_times: dict[UUID, float] — mapea run_id → perf_counter al inicio
      La clave es el UUID que LangChain asigna a cada run.
      Se agrega en on_llm_start y se elimina en on_llm_end/on_llm_error.

    Thread safety:
    ─────────────
    En el contexto de asyncio (un solo thread event loop), las operaciones
    de dict son atómicas y no necesitan locks. Si usaras múltiples threads
    (ThreadPoolExecutor), necesitarías threading.Lock() — pero asyncio.gather
    corre coroutines en el MISMO thread, por lo que no hay riesgo aquí.

    ¿Por qué no hay estado de "últimas métricas"?
    ───────────────────────────────────────────────
    Este handler SOLO registra al logger. No acumula estadísticas — para eso
    existiría un MetricsCallbackHandler separado que empujara a Prometheus.
    Un handler = una responsabilidad. SRP al máximo.
    """

    def __init__(self) -> None:
        """
        Inicializa el handler con un diccionario de tiempos de inicio vacío.

        Llamamos a super().__init__() para que BaseCallbackHandler inicialice
        correctamente sus atributos internos (raise_error, etc.).
        """
        super().__init__()
        self._start_times: dict[UUID, float] = {}

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """
        Se dispara cuando el LLM recibe el prompt y está por hacer la llamada.

        ¿Qué es `serialized`?
        ─────────────────────
        Un dict con la representación serializable del LLM — nombre de clase,
        versión, parámetros. Útil si querés registrar qué modelo específico
        se usó (ej: "llama-3.3-70b-versatile" vs "gpt-4o").

        ¿Qué es `prompts`?
        ──────────────────
        Lista de strings — los prompts formateados que se enviarán al LLM.
        En chains con batch, puede haber múltiples prompts. En nuestro caso
        siempre hay uno solo (un caso clínico a la vez).

        Guardamos time.perf_counter() porque es el timer de alta resolución
        de Python — monotónico, no afectado por cambios de reloj del sistema.
        Ideal para medir duraciones cortas con precisión de microsegundos.
        """
        self._start_times[run_id] = time.perf_counter()
        logger.info(
            "LLM call started",
            extra={
                "run_id": str(run_id),
                "prompt_count": len(prompts),
            },
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """
        Se dispara cuando el LLM devuelve la respuesta exitosamente.

        ¿Qué es LLMResult?
        ──────────────────
        La clase LLMResult de LangChain contiene:
          - generations: lista de Generation objects (la respuesta del modelo)
          - llm_output: metadata del proveedor (tokens usados, model name, etc.)

        Calculamos duration_ms como int (no float) para que el JSON sea
        más limpio — un int como "1234" es más legible que "1234.56789".

        Usamos .pop() en lugar de del para ser defensive: si por algún
        bug on_llm_end se llama sin on_llm_start previo, .pop(key, None)
        no lanza KeyError.
        """
        start = self._start_times.pop(run_id, None)
        duration_ms = int((time.perf_counter() - start) * 1000) if start is not None else -1

        logger.info(
            "LLM call completed",
            extra={
                "run_id": str(run_id),
                "duration_ms": duration_ms,
            },
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """
        Se dispara cuando el LLM lanza una excepción durante la llamada.

        Errores comunes que llegan acá:
          - Timeout de la API (httpx.TimeoutError)
          - Rate limit superado (HTTPStatusError 429)
          - Error de autenticación (HTTPStatusError 401)
          - Respuesta malformada del modelo

        Limpiamos _start_times para evitar memory leaks — si no lo hacemos,
        cada error acumula una entrada en el dict que nunca se elimina.

        El tipo del error (error.__class__.__name__) es más útil que el
        mensaje en el campo de logging — permite filtrar por tipo de error
        en Datadog/ELK: "dame todos los HTTPStatusError de las últimas 24h".
        """
        self._start_times.pop(run_id, None)  # limpieza defensiva

        logger.error(
            "LLM call failed",
            extra={
                "run_id": str(run_id),
                "error_type": type(error).__name__,
            },
        )
