"""
Tests de manejo de errores — Fase 9: Resiliencia.

¿Qué testeamos acá?
─────────────────────
La resiliencia del Integrator ante fallos parciales o totales de agentes,
y el comportamiento del decorator async_retry.

Patrón de mocks (igual que test_integrator.py):
  patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry)

  El AGENT_REGISTRY es un dict construido en tiempo de importación.
  Para reemplazar agentes específicos sin tocar los reales, usamos patch.dict.
  Esto garantiza que:
    - Los tests no tocan LLMs reales
    - Los tests no necesitan pgvector ni base de datos
    - Cada test es aislado y predecible

¿Cómo simulamos un agente que falla?
──────────────────────────────────────
instance.run = AsyncMock(side_effect=RuntimeError("LLM no disponible"))

AsyncMock con side_effect lanza la excepción cuando se llama a .run().
El Integrator llama a _safe_run → que captura la excepción → la convierte
en AgentExecutionError con el nombre del agente.

¿Cómo simulamos un timeout?
─────────────────────────────
instance.run = AsyncMock(side_effect=asyncio.TimeoutError())

O más elegante: un agente que "duerme" más que el timeout configurado:
  async def lento(caso): await asyncio.sleep(100)
  instance.run = lento

Pero en tests usamos side_effect=asyncio.TimeoutError() directamente
para que el test sea rápido (no espera 100 segundos reales).
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.integrator import Integrator, _combine_results
from app.models.clinical import AgentOutput, AnalyzeOutput, NivelUrgencia
from app.core.exceptions import (
    AgentExecutionError,
    AllAgentsFailedError,
    LLMProviderError,
)
from app.core.retry import async_retry


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_agent_output(agent_name: str, confidence: float = 0.8) -> AgentOutput:
    """Crea un AgentOutput de prueba con valores válidos."""
    return AgentOutput(
        agent_name=agent_name,
        summary=f"Análisis de {agent_name}.",
        findings=[f"hallazgo-{agent_name}"],
        red_flags=[f"flag-{agent_name}"],
        recommendations=[f"rec-{agent_name}"],
        confidence=confidence,
        context_sources=[],
    )


def make_successful_mock(output: AgentOutput) -> MagicMock:
    """Crea un mock de agente que retorna exitosamente."""
    instance = MagicMock()
    instance.run = AsyncMock(return_value=output)
    return instance


def make_failing_mock(error: Exception) -> MagicMock:
    """Crea un mock de agente que lanza una excepción."""
    instance = MagicMock()
    instance.run = AsyncMock(side_effect=error)
    return instance


def _make_registry(agents: dict[str, MagicMock]) -> dict:
    """
    Construye un AGENT_REGISTRY falso para patch.dict.

    ¿Por qué el lambda con _inst=instance?
    ─────────────────────────────────────────
    En Python, las closures capturan la variable por referencia, no por valor.
    Sin _inst=instance, al final del loop todos los lambdas apuntarían
    al mismo `instance` (el último del loop).

    Con _inst=instance capturamos el valor ACTUAL en cada iteración.
    Es el patrón estándar para closures en loops en Python.
    """
    return {
        name: (lambda _inst=mock: _inst)
        for name, mock in agents.items()
    }


# ─── Tests: Integrator resiliente ──────────────────────────────────────────────

async def test_integrator_handles_single_agent_failure():
    """
    Un agente falla → resultado parcial con los agentes exitosos.

    Escenario:
      - ClinicalAgent: responde bien
      - EmergencyAgent: lanza RuntimeError

    Esperamos:
      - AnalyzeOutput con solo ClinicalAgent en agentes_activados
      - EmergencyAgent en failed_agents
      - warnings con mensaje sobre EmergencyAgent
    """
    clinical_output = make_agent_output("ClinicalAgent", confidence=0.8)

    fake_registry = _make_registry({
        "ClinicalAgent": make_successful_mock(clinical_output),
        "EmergencyAgent": make_failing_mock(RuntimeError("LLM no disponible")),
    })

    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Paciente con dolor torácico.",
            agentes_sugeridos=["ClinicalAgent", "EmergencyAgent"],
        )

    assert isinstance(result, AnalyzeOutput)
    # Solo el agente exitoso está en agentes_activados
    assert "ClinicalAgent" in result.agentes_activados
    assert "EmergencyAgent" not in result.agentes_activados
    # El agente fallido está en failed_agents
    assert "EmergencyAgent" in result.failed_agents
    # Hay al menos un warning con información del fallo
    assert len(result.warnings) > 0
    assert any("EmergencyAgent" in w for w in result.warnings)


async def test_integrator_successful_results_preserved_on_partial_failure():
    """
    Los resultados de agentes exitosos se preservan intactos ante fallos parciales.

    Los findings, red_flags y confidence del agente exitoso deben aparecer
    en el output combinado — los fallos no deben "contaminar" los datos.
    """
    clinical_output = make_agent_output("ClinicalAgent", confidence=0.85)
    clinical_output.findings = ["dolor irradiado", "disnea de esfuerzo"]
    clinical_output.red_flags = ["posible IAM"]

    fake_registry = _make_registry({
        "ClinicalAgent": make_successful_mock(clinical_output),
        "CardiologyAgent": make_failing_mock(ConnectionError("pgvector no disponible")),
    })

    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Caso con ECG alterado.",
            agentes_sugeridos=["ClinicalAgent", "CardiologyAgent"],
        )

    # Los findings del agente exitoso deben estar presentes
    assert "dolor irradiado" in result.findings
    assert "disnea de esfuerzo" in result.findings
    # Las red_flags no se pierden
    assert "posible IAM" in result.red_flags
    # La confidence viene del agente exitoso
    assert result.confidence == pytest.approx(0.85)


async def test_integrator_handles_all_agents_failure():
    """
    Todos los agentes fallan → AllAgentsFailedError.

    Cuando no hay ningún resultado válido, no podemos construir
    un AnalyzeOutput útil — lanzamos AllAgentsFailedError.
    """
    fake_registry = _make_registry({
        "ClinicalAgent": make_failing_mock(RuntimeError("error 1")),
        "EmergencyAgent": make_failing_mock(ConnectionError("error 2")),
    })

    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        with pytest.raises(AllAgentsFailedError) as exc_info:
            await integrator.analyze(
                "Caso crítico.",
                agentes_sugeridos=["ClinicalAgent", "EmergencyAgent"],
            )

    error = exc_info.value
    assert "ClinicalAgent" in error.agent_names
    assert "EmergencyAgent" in error.agent_names
    assert len(error.errors) == 2


async def test_integrator_timeout_treated_as_failure():
    """
    Un agente que supera el timeout se trata como fallo.

    asyncio.TimeoutError → AgentExecutionError → agente en failed_agents.
    El agente que respondió a tiempo preserva su resultado.

    Usamos timeout=0.01 (10ms) y side_effect=asyncio.TimeoutError() para
    simular el timeout sin esperar segundos reales.
    """
    clinical_output = make_agent_output("ClinicalAgent")

    # Simulamos un agente que "tardó demasiado" usando side_effect de TimeoutError.
    # En producción, asyncio.wait_for() lanzaría esto si el agente supera el timeout.
    timeout_mock = MagicMock()
    timeout_mock.run = AsyncMock(side_effect=asyncio.TimeoutError())

    fake_registry = _make_registry({
        "ClinicalAgent": make_successful_mock(clinical_output),
        "EmergencyAgent": timeout_mock,
    })

    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        # timeout muy bajo para que el test sea rápido
        integrator = Integrator(agent_timeout=0.01)
        result = await integrator.analyze(
            "Caso urgente.",
            agentes_sugeridos=["ClinicalAgent", "EmergencyAgent"],
        )

    # El agente con timeout está en failed_agents, no en agentes_activados
    assert "EmergencyAgent" in result.failed_agents
    assert "EmergencyAgent" not in result.agentes_activados
    # El agente exitoso sí está en el resultado
    assert "ClinicalAgent" in result.agentes_activados


async def test_integrator_no_failed_agents_field_when_all_succeed():
    """
    Cuando todos los agentes responden, failed_agents y warnings deben estar vacíos.

    Verificamos que el comportamiento normal (happy path) no se ve afectado
    por los campos nuevos de resiliencia — deben quedar vacíos por default.
    """
    output = make_agent_output("ClinicalAgent")

    fake_registry = _make_registry({
        "ClinicalAgent": make_successful_mock(output),
    })

    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Caso simple.",
            nivel_urgencia=NivelUrgencia.NO_URGENTE,
        )

    # En el happy path, no hay fallos ni warnings
    assert result.failed_agents == []
    assert result.warnings == []


# ─── Tests: async_retry decorator ──────────────────────────────────────────────

async def test_retry_decorator_succeeds_on_first_try():
    """
    Si la función tiene éxito en el primer intento, no hay reintentos.

    Verificamos que el decorator no interfiere con funciones que funcionan.
    """
    call_count = 0

    @async_retry(max_retries=3, backoff_base=0.01)
    async def always_succeeds() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await always_succeeds()
    assert result == "ok"
    assert call_count == 1  # solo un intento


async def test_retry_decorator_retries_on_retryable_exception():
    """
    Si la función lanza un error retryable, el decorator reintenta.

    Configuramos una función que falla las primeras N veces y luego tiene éxito.
    Verificamos que el decorator reintentó las veces correctas.
    """
    call_count = 0

    @async_retry(max_retries=3, backoff_base=0.01, retryable_exceptions=(LLMProviderError,))
    async def fails_twice_then_succeeds() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise LLMProviderError("rate limit")
        return "éxito después de reintentos"

    result = await fails_twice_then_succeeds()
    assert result == "éxito después de reintentos"
    assert call_count == 3  # falló 2 veces + éxito en el 3er intento


async def test_retry_decorator_gives_up_after_max_retries():
    """
    Si la función sigue fallando después de max_retries, se propaga la última excepción.

    max_retries=2 → 1 intento inicial + 2 reintentos = 3 intentos totales.
    Después del 3er intento, el error se propaga sin más reintentos.
    """
    call_count = 0

    @async_retry(max_retries=2, backoff_base=0.01, retryable_exceptions=(LLMProviderError,))
    async def always_fails() -> str:
        nonlocal call_count
        call_count += 1
        raise LLMProviderError("timeout persistente")

    with pytest.raises(LLMProviderError, match="timeout persistente"):
        await always_fails()

    # 1 intento inicial + 2 reintentos = 3 intentos totales
    assert call_count == 3


async def test_retry_decorator_does_not_retry_non_retryable_exceptions():
    """
    Si la excepción NO está en retryable_exceptions, no se reintenta.

    ValueError indica un error en los datos — reintentar no lo va a arreglar.
    El decorator debe propagar inmediatamente sin reintentos adicionales.
    """
    call_count = 0

    @async_retry(max_retries=3, backoff_base=0.01, retryable_exceptions=(LLMProviderError,))
    async def fails_with_value_error() -> str:
        nonlocal call_count
        call_count += 1
        raise ValueError("datos inválidos — no reintentar")

    with pytest.raises(ValueError, match="datos inválidos"):
        await fails_with_value_error()

    # Solo un intento — no se reintentó porque ValueError no es LLMProviderError
    assert call_count == 1


async def test_retry_decorator_preserves_return_type():
    """
    El decorator no modifica el valor de retorno de la función decorada.

    Verificamos que el wrapper pasa correctamente el resultado original.
    """
    expected = {"clave": "valor", "numero": 42}

    @async_retry(max_retries=1, backoff_base=0.01)
    async def returns_dict() -> dict:
        return expected

    result = await returns_dict()
    assert result == expected


async def test_retry_decorator_preserves_function_name():
    """
    El decorator usa functools.wraps, así que el nombre de la función se preserva.

    Esto importa para debugging y logging — el nombre del wrapper debe ser
    el nombre de la función original, no "wrapper".
    """

    @async_retry(max_retries=1, backoff_base=0.01)
    async def mi_funcion_especifica() -> None:
        pass

    assert mi_funcion_especifica.__name__ == "mi_funcion_especifica"


# ─── Tests: Excepciones personalizadas ─────────────────────────────────────────

def test_agent_execution_error_has_agent_name():
    """AgentExecutionError expone el nombre del agente que falló."""
    cause = RuntimeError("timeout")
    error = AgentExecutionError(agent_name="CardiologyAgent", cause=cause)

    assert error.agent_name == "CardiologyAgent"
    assert error.cause is cause
    assert "CardiologyAgent" in str(error)


def test_all_agents_failed_error_has_all_names():
    """AllAgentsFailedError expone los nombres de todos los agentes fallidos."""
    errors = [RuntimeError("e1"), RuntimeError("e2")]
    error = AllAgentsFailedError(
        agent_names=["ClinicalAgent", "EmergencyAgent"],
        errors=errors,
    )

    assert "ClinicalAgent" in error.agent_names
    assert "EmergencyAgent" in error.agent_names
    assert len(error.errors) == 2


def test_clinical_base_error_is_base_for_all():
    """Todas las excepciones heredan de ClinicalBaseError."""
    from app.core.exceptions import (
        ClinicalBaseError,
        RAGRetrievalError,
        LLMProviderError,
        TriageError,
    )

    assert issubclass(AgentExecutionError, ClinicalBaseError)
    assert issubclass(AllAgentsFailedError, ClinicalBaseError)
    assert issubclass(LLMProviderError, ClinicalBaseError)
    assert issubclass(RAGRetrievalError, ClinicalBaseError)
    assert issubclass(TriageError, ClinicalBaseError)


def test_llm_provider_error_includes_provider():
    """LLMProviderError incluye el nombre del proveedor en el mensaje."""
    from app.core.exceptions import LLMProviderError

    error = LLMProviderError("rate limit superado", provider="groq")
    assert "groq" in str(error)
    assert error.provider == "groq"
