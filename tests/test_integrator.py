"""
Tests del Integrator — Fase 6.

¿Qué mockeamos?
  El Integrator instancia agentes (ClinicalAgent, EmergencyAgent, DifferentialDiagnosisAgent).
  Cada agente llama get_retriever() y ChatGroq en __init__.
  En lugar de parchear cada agente individualmente, mockeamos el método .run() directamente.

Patrón (el más limpio para tests de integración de servicios):
  patch("app.services.integrator.ClinicalAgent")           → reemplaza la CLASE
  patch("app.services.integrator.EmergencyAgent")          → reemplaza la CLASE
  patch("app.services.integrator.DifferentialDiagnosisAgent") → reemplaza la CLASE

  Cuando el Integrator hace ClinicalAgent() → obtiene el mock, no la clase real.
  MockClinicalAgent.return_value.run = AsyncMock(return_value=MOCK_OUTPUT)
    ↑ instancia mock       ↑ método run mockeado

¿Por qué no parcheamos get_retriever aquí?
  Porque mockeamos toda la CLASE, nunca se ejecuta __init__ real.
  Los agentes ni siquiera se construyen — el mock es la instancia completa.

Tests de _combine_results (función pura):
  Se puede importar y testear directamente — no necesita mocks.
  Es la lógica más importante: deduplicación y combinación de outputs.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.integrator import Integrator, _combine_results, _dedup_strings
from app.models.clinical import AgentOutput, AnalyzeOutput, NivelUrgencia


# ─── Fixtures ──────────────────────────────────────────────────────────────────

def make_agent_output(agent_name: str, confidence: float = 0.8, red_flags: list[str] | None = None) -> AgentOutput:
    return AgentOutput(
        agent_name=agent_name,
        summary=f"Análisis de {agent_name}.",
        findings=[f"hallazgo-{agent_name}-1", f"hallazgo-{agent_name}-2"],
        red_flags=red_flags if red_flags is not None else [f"flag-{agent_name}"],
        recommendations=[f"rec-{agent_name}-1"],
        confidence=confidence,
        context_sources=[],
    )


# ─── Tests de _combine_results (función pura — sin mocks) ──────────────────────

def test_combine_picks_highest_confidence_summary():
    """El summary del resultado combinado viene del agente con mayor confidence."""
    low = make_agent_output("LowAgent", confidence=0.5)
    high = make_agent_output("HighAgent", confidence=0.9)
    result = _combine_results([low, high])
    assert result.summary == high.summary


def test_combine_merges_all_findings():
    """findings es la unión de todos los agentes."""
    a = AgentOutput(
        agent_name="AgentA", summary="s", confidence=0.7, context_sources=[],
        findings=["taquicardia ventricular", "edema pulmonar"],
        red_flags=[], recommendations=[],
    )
    b = AgentOutput(
        agent_name="AgentB", summary="s", confidence=0.8, context_sources=[],
        findings=["hipoglucemia severa", "insuficiencia renal aguda"],
        red_flags=[], recommendations=[],
    )
    result = _combine_results([a, b])
    assert "taquicardia ventricular" in result.findings
    assert "hipoglucemia severa" in result.findings


def test_combine_deduplicates_findings():
    """Findings duplicados aparecen una sola vez."""
    shared = AgentOutput(
        agent_name="A", summary="s", findings=["dolor torácico"],
        red_flags=[], recommendations=[], confidence=0.7, context_sources=[],
    )
    shared2 = AgentOutput(
        agent_name="B", summary="s", findings=["dolor torácico"],
        red_flags=[], recommendations=[], confidence=0.8, context_sources=[],
    )
    result = _combine_results([shared, shared2])
    assert result.findings.count("dolor torácico") == 1


def test_combine_never_loses_red_flags():
    """NUNCA se pierde una red_flag — unión completa de todos los agentes."""
    a = make_agent_output("Emergency", confidence=0.9, red_flags=["posible IAM"])
    b = make_agent_output("Clinical", confidence=0.7, red_flags=["hipertensión severa"])
    result = _combine_results([a, b])
    assert "posible IAM" in result.red_flags
    assert "hipertensión severa" in result.red_flags


def test_combine_confidence_is_average():
    """La confidence combinada es el promedio de todos los agentes."""
    a = make_agent_output("A", confidence=0.6)
    b = make_agent_output("B", confidence=0.8)
    result = _combine_results([a, b])
    assert result.confidence == pytest.approx(0.7, abs=0.001)


def test_combine_lists_all_agents():
    """agentes_activados lista todos los agentes que participaron."""
    a = make_agent_output("ClinicalAgent")
    b = make_agent_output("EmergencyAgent")
    result = _combine_results([a, b])
    assert "ClinicalAgent" in result.agentes_activados
    assert "EmergencyAgent" in result.agentes_activados


def test_combine_single_agent():
    """Con un solo agente, el resultado es directo sin modificaciones."""
    single = make_agent_output("ClinicalAgent", confidence=0.85)
    result = _combine_results([single])
    assert result.summary == single.summary
    assert result.confidence == pytest.approx(0.85)
    assert result.agentes_activados == ["ClinicalAgent"]


# ─── Tests del Integrator (con mocks de agentes) ───────────────────────────────

MOCK_CLINICAL = make_agent_output("ClinicalAgent", confidence=0.75)
MOCK_EMERGENCY = make_agent_output("EmergencyAgent", confidence=0.9, red_flags=["riesgo vital"])
MOCK_DIAGNOSIS = make_agent_output("DifferentialDiagnosisAgent", confidence=0.7)


def _make_mock_registry(outputs: dict[str, AgentOutput]) -> dict:
    """
    Construye un AGENT_REGISTRY falso donde cada clase es un callable
    que devuelve una instancia mock con .run() ya configurado.

    ¿Por qué patch.dict en lugar de @patch de cada clase?
    ─────────────────────────────────────────────────────
    AGENT_REGISTRY es un dict construido en tiempo de IMPORTACIÓN:
      AGENT_REGISTRY = {"ClinicalAgent": ClinicalAgent, ...}

    Cuando hacemos @patch("app.services.integrator.ClinicalAgent"),
    parchamos el NOMBRE en el módulo, pero el dict ya apunta a la clase
    real — el dict no se actualiza con el patch.

    patch.dict("app.services.integrator.AGENT_REGISTRY", {...}) reemplaza
    las entradas del dict MIENTRAS DURA el contexto. El Integrator hace
    AGENT_REGISTRY[name]() → obtiene el mock, no la clase real.
    """
    registry = {}
    for name, output in outputs.items():
        instance = MagicMock()
        instance.run = AsyncMock(return_value=output)
        registry[name] = lambda _inst=instance: _inst
    return registry


async def test_integrator_urgente_activates_two_agents():
    """URGENTE → ClinicalAgent + DifferentialDiagnosisAgent."""
    fake_registry = _make_mock_registry({
        "ClinicalAgent": MOCK_CLINICAL,
        "DifferentialDiagnosisAgent": MOCK_DIAGNOSIS,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Paciente con fatiga y pérdida de peso.",
            nivel_urgencia=NivelUrgencia.URGENTE,
        )

    assert isinstance(result, AnalyzeOutput)
    assert "ClinicalAgent" in result.agentes_activados
    assert "DifferentialDiagnosisAgent" in result.agentes_activados


async def test_integrator_no_urgente_activates_one_agent():
    """NO_URGENTE → solo ClinicalAgent."""
    fake_registry = _make_mock_registry({"ClinicalAgent": MOCK_CLINICAL})
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Paciente con resfriado leve.",
            nivel_urgencia=NivelUrgencia.NO_URGENTE,
        )

    assert result.agentes_activados == ["ClinicalAgent"]


async def test_integrator_critico_activates_three_agents():
    """CRITICO → EmergencyAgent + ClinicalAgent + DifferentialDiagnosisAgent."""
    fake_registry = _make_mock_registry({
        "EmergencyAgent": MOCK_EMERGENCY,
        "ClinicalAgent": MOCK_CLINICAL,
        "DifferentialDiagnosisAgent": MOCK_DIAGNOSIS,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Paciente con paro cardiorrespiratorio.",
            nivel_urgencia=NivelUrgencia.CRITICO,
        )

    assert len(result.agentes_activados) == 3
    assert "EmergencyAgent" in result.agentes_activados


async def test_integrator_critico_preserves_red_flags():
    """En CRITICO, ninguna red_flag se pierde."""
    fake_registry = _make_mock_registry({
        "EmergencyAgent": MOCK_EMERGENCY,
        "ClinicalAgent": MOCK_CLINICAL,
        "DifferentialDiagnosisAgent": MOCK_DIAGNOSIS,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Caso crítico multisistémico.",
            nivel_urgencia=NivelUrgencia.CRITICO,
        )

    assert "riesgo vital" in result.red_flags


async def test_integrator_defaults_to_urgente_when_no_nivel():
    """Sin nivel_urgencia → asume URGENTE (ClinicalAgent + DifferentialDiagnosisAgent)."""
    fake_registry = _make_mock_registry({
        "ClinicalAgent": MOCK_CLINICAL,
        "DifferentialDiagnosisAgent": MOCK_DIAGNOSIS,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze("Caso sin urgencia especificada.")

    assert "ClinicalAgent" in result.agentes_activados
    assert "DifferentialDiagnosisAgent" in result.agentes_activados


# ─── Tests de agentes_sugeridos (Fase 7) ───────────────────────────────────────

MOCK_CARDIOLOGY = make_agent_output("CardiologyAgent", confidence=0.88)
MOCK_PHARMACOLOGY = make_agent_output("PharmacologyAgent", confidence=0.82)
MOCK_RADIOLOGY = make_agent_output("RadiologyAgent", confidence=0.79)


async def test_integrator_uses_agentes_sugeridos_over_urgency():
    """
    agentes_sugeridos tiene precedencia sobre nivel_urgencia.
    El router sugirió CardiologyAgent → se usa ese, aunque nivel_urgencia sea NO_URGENTE.
    """
    fake_registry = _make_mock_registry({
        "ClinicalAgent": MOCK_CLINICAL,
        "CardiologyAgent": MOCK_CARDIOLOGY,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Paciente con cambios en el ECG.",
            agentes_sugeridos=["ClinicalAgent", "CardiologyAgent"],
            nivel_urgencia=NivelUrgencia.NO_URGENTE,  # se ignora — agentes_sugeridos gana
        )

    assert "CardiologyAgent" in result.agentes_activados
    # EmergencyAgent NO se activa aunque podría por urgency fallback
    assert "EmergencyAgent" not in result.agentes_activados


async def test_integrator_activates_pharmacology_via_sugeridos():
    """PharmacologyAgent se activa vía agentes_sugeridos."""
    fake_registry = _make_mock_registry({
        "ClinicalAgent": MOCK_CLINICAL,
        "PharmacologyAgent": MOCK_PHARMACOLOGY,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Paciente con warfarina y amiodarona — revisar interacciones.",
            agentes_sugeridos=["ClinicalAgent", "PharmacologyAgent"],
        )

    assert "PharmacologyAgent" in result.agentes_activados


async def test_integrator_activates_radiology_via_sugeridos():
    """RadiologyAgent se activa vía agentes_sugeridos."""
    fake_registry = _make_mock_registry({
        "ClinicalAgent": MOCK_CLINICAL,
        "RadiologyAgent": MOCK_RADIOLOGY,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "RX tórax con opacidad en base derecha.",
            agentes_sugeridos=["ClinicalAgent", "RadiologyAgent"],
        )

    assert "RadiologyAgent" in result.agentes_activados


async def test_integrator_filters_unknown_agents_in_sugeridos():
    """
    Si el router alucina un nombre de agente que no existe en el registry,
    se filtra silenciosamente. Los válidos se usan igual.
    Si TODOS son inválidos, fallback a nivel_urgencia.
    """
    fake_registry = _make_mock_registry({"ClinicalAgent": MOCK_CLINICAL})
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Caso con agente inventado.",
            agentes_sugeridos=["ClinicalAgent", "AgenteQueNoExiste"],
            nivel_urgencia=NivelUrgencia.NO_URGENTE,
        )

    # El agente válido (ClinicalAgent) se activa, el inválido se ignora
    assert "ClinicalAgent" in result.agentes_activados
    assert "AgenteQueNoExiste" not in result.agentes_activados


async def test_integrator_full_specialist_pipeline():
    """
    Pipeline completo con tres especialistas — como lo activaría el router
    en un caso con ECG, imagen y medicación.
    """
    fake_registry = _make_mock_registry({
        "EmergencyAgent": MOCK_EMERGENCY,
        "CardiologyAgent": MOCK_CARDIOLOGY,
        "RadiologyAgent": MOCK_RADIOLOGY,
    })
    with patch.dict("app.services.integrator.AGENT_REGISTRY", fake_registry):
        integrator = Integrator()
        result = await integrator.analyze(
            "Dolor torácico con ECG alterado y RX tórax compatible con derrame.",
            agentes_sugeridos=["EmergencyAgent", "CardiologyAgent", "RadiologyAgent"],
        )

    assert len(result.agentes_activados) == 3
    assert len(result.agent_outputs) == 3
    assert isinstance(result.confidence, float)


# ─── Tests de _dedup_strings (fuzzy dedup — Fase findings-dedup) ───────────────

def test_dedup_word_order_variant():
    """Word-order variants collapse to the first occurrence."""
    items = ["dolor torácico opresivo", "opresivo dolor torácico"]
    result = _dedup_strings(items)
    assert len(result) == 1
    assert result == ["dolor torácico opresivo"]


def test_dedup_preserves_near_distinct_medical_terms():
    """Near-distinct medical terms (below threshold) are both kept."""
    items = ["fibrilación auricular", "flutter auricular"]
    result = _dedup_strings(items)
    assert len(result) == 2
    assert "fibrilación auricular" in result
    assert "flutter auricular" in result


def test_red_flags_near_duplicate_passes_through():
    """Near-duplicate red_flags from two agents are both preserved (exact dedup only)."""
    output_a = AgentOutput(
        agent_name="AgentA",
        summary="summary a",
        findings=[],
        red_flags=["IAM con supra ST"],
        recommendations=[],
        confidence=0.8,
        context_sources=[],
    )
    output_b = AgentOutput(
        agent_name="AgentB",
        summary="summary b",
        findings=[],
        red_flags=["IAM con BRIHH nuevo"],
        recommendations=[],
        confidence=0.75,
        context_sources=[],
    )
    combined = _combine_results([output_a, output_b])
    assert "IAM con supra ST" in combined.red_flags
    assert "IAM con BRIHH nuevo" in combined.red_flags
