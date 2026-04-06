"""
Tests del AgentRouter — Fase 6.

Actualizado en Fase 11 (LLM Factory):
  Antes: @patch("app.agents.router.create_llm")
  Ahora: @patch("app.agents.router.create_llm")

¿Qué mockeamos?
  AgentRouter.__init__ llama create_llm() (sin RAG, sin get_retriever).
  Solo necesitamos parchear create_llm para que devuelva un LLM falso.
  No hay get_retriever aquí — el router no usa RAG.

Patrón actualizado:
  @patch("app.agents.router.create_llm")
  async def test_algo(mock_create_llm):
      mock_create_llm.return_value = RunnableLambda(lambda _: AIMessage(content=json.dumps(response)))
      router = AgentRouter()
      result = await router.run(...)

Nota sobre el input al fake LLM:
  El prompt ya procesó {texto_clinico} y {sintomas} → la chain llega al LLM
  con una lista de mensajes [SystemMessage(...), HumanMessage(...)].
  El fake LLM recibe esos mensajes, los ignora, y devuelve el JSON hardcodeado.
"""

import json
import pytest
from unittest.mock import patch
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage

from app.agents.router import AgentRouter
from app.models.clinical import TriageOutput, NivelUrgencia


def make_triage_response(nivel: str, agentes: list[str], razonamiento: str) -> dict:
    return {
        "nivel_urgencia": nivel,
        "agentes_sugeridos": agentes,
        "razonamiento": razonamiento,
    }


def make_fake_llm(response: dict) -> RunnableLambda:
    return RunnableLambda(lambda _: AIMessage(content=json.dumps(response)))


# ─── Tests básicos ─────────────────────────────────────────────────────────────

@patch("app.agents.router.create_llm")
async def test_router_returns_triage_output(mock_create_llm):
    """AgentRouter devuelve un TriageOutput válido."""
    mock_create_llm.return_value = make_fake_llm(make_triage_response(
        nivel="URGENTE",
        agentes=["ClinicalAgent", "DifferentialDiagnosisAgent"],
        razonamiento="Síntomas complejos que requieren evaluación clínica y diferencial.",
    ))

    router = AgentRouter()
    result = await router.run(
        texto_clinico="Paciente de 50 años con fatiga crónica y pérdida de peso inexplicada.",
        sintomas=["fatiga", "perdida_de_peso"],
    )

    assert isinstance(result, TriageOutput)
    assert result.nivel_urgencia in NivelUrgencia.__members__.values()
    assert isinstance(result.agentes_sugeridos, list)
    assert len(result.agentes_sugeridos) > 0
    assert isinstance(result.razonamiento, str)


@patch("app.agents.router.create_llm")
async def test_router_classifies_critical_cases(mock_create_llm):
    """CRITICO → EmergencyAgent siempre presente."""
    mock_create_llm.return_value = make_fake_llm(make_triage_response(
        nivel="CRITICO",
        agentes=["EmergencyAgent", "ClinicalAgent", "DifferentialDiagnosisAgent"],
        razonamiento="Posible síndrome coronario agudo con riesgo vital inminente.",
    ))

    router = AgentRouter()
    result = await router.run(
        texto_clinico="Paciente de 62 años con dolor torácico irradiado, hipotensión y diaforesis.",
        sintomas=["dolor_toracico", "hipotension", "diaforesis"],
    )

    assert result.nivel_urgencia == NivelUrgencia.CRITICO
    assert "EmergencyAgent" in result.agentes_sugeridos


@patch("app.agents.router.create_llm")
async def test_router_classifies_non_urgent_cases(mock_create_llm):
    """NO_URGENTE → solo ClinicalAgent."""
    mock_create_llm.return_value = make_fake_llm(make_triage_response(
        nivel="NO_URGENTE",
        agentes=["ClinicalAgent"],
        razonamiento="Síntomas leves sin signos de alarma.",
    ))

    router = AgentRouter()
    result = await router.run(
        texto_clinico="Paciente con resfriado común, fiebre baja y congestión nasal.",
        sintomas=["fiebre_baja", "congestion_nasal"],
    )

    assert result.nivel_urgencia == NivelUrgencia.NO_URGENTE
    assert result.agentes_sugeridos == ["ClinicalAgent"]


@patch("app.agents.router.create_llm")
async def test_router_handles_empty_sintomas(mock_create_llm):
    """El router funciona incluso si la lista de síntomas está vacía."""
    mock_create_llm.return_value = make_fake_llm(make_triage_response(
        nivel="URGENTE",
        agentes=["ClinicalAgent"],
        razonamiento="Sin síntomas específicos — evaluación clínica general.",
    ))

    router = AgentRouter()
    result = await router.run(
        texto_clinico="Paciente con malestar general sin síntomas específicos.",
        sintomas=[],
    )

    assert isinstance(result, TriageOutput)


@patch("app.agents.router.create_llm")
async def test_router_includes_razonamiento(mock_create_llm):
    """El razonamiento siempre es un string no vacío."""
    razonamiento = "Disnea severa con saturación baja → posible TEP o insuficiencia respiratoria."
    mock_create_llm.return_value = make_fake_llm(make_triage_response(
        nivel="MUY_URGENTE",
        agentes=["EmergencyAgent", "ClinicalAgent"],
        razonamiento=razonamiento,
    ))

    router = AgentRouter()
    result = await router.run(
        texto_clinico="Paciente con disnea severa y saturación de oxígeno 88%.",
        sintomas=["disnea_severa", "hipoxia"],
    )

    assert len(result.razonamiento) > 0
