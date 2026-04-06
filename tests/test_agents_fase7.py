"""
Tests de los agentes especialistas — Fase 7.

Actualizado en Fase 11 (LLM Factory):
  Antes: @patch("app.agents.cardiology.ChatGroq")
  Ahora: @patch("app.agents.cardiology.create_llm")

¿Por qué cambió el mock?
  Desde Fase 11, los agentes ya no importan ChatGroq directamente.
  Importan create_llm de app.core.llm. Por tanto, hay que mockear la
  referencia donde se usa — que es el módulo del agente, no app.core.llm.

Seguimos mockeando get_retriever porque sigue siendo necesario para evitar
la conexión real a PGVector.

Patrón actualizado (dos @patch apilados):
  @patch("app.agents.cardiology.create_llm")    ← outermost → segundo param
  @patch("app.agents.cardiology.get_retriever") ← innermost → primer param
  async def test_algo(mock_retriever, mock_create_llm):

Los tres agentes (Cardiology, Pharmacology, Radiology) tienen exactamente
la misma estructura RAG — mismo test pattern, distintos system prompts.
"""

import json
import pytest
from unittest.mock import patch
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage
from langchain_core.documents import Document

from app.agents.cardiology import CardiologyAgent
from app.agents.pharmacology import PharmacologyAgent
from app.agents.radiology import RadiologyAgent
from app.models.clinical import AgentOutput


def make_agent_response(agent_name: str) -> dict:
    return {
        "agent_name": agent_name,
        "summary": f"Análisis especializado de {agent_name}.",
        "findings": ["hallazgo-1", "hallazgo-2"],
        "red_flags": ["red-flag-1"],
        "recommendations": ["recomendacion-1"],
        "confidence": 0.85,
        "context_sources": ["architecture/routing-rules.md"],
    }


def make_fake_llm(response: dict) -> RunnableLambda:
    return RunnableLambda(lambda _: AIMessage(content=json.dumps(response)))


def make_fake_retriever() -> RunnableLambda:
    return RunnableLambda(lambda _: [
        Document(
            page_content="Protocolo cardiológico de referencia.",
            metadata={"source": "docs/architecture/routing-rules.md", "category": "architecture"},
        ),
    ])


# ─── CardiologyAgent ───────────────────────────────────────────────────────────

@patch("app.agents.cardiology.create_llm")
@patch("app.agents.cardiology.get_retriever")
async def test_cardiology_agent_returns_agent_output(mock_retriever, mock_create_llm):
    """CardiologyAgent devuelve AgentOutput válido."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("CardiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = CardiologyAgent()
    result = await agent.run(
        "Paciente 65 años, ECG con elevación ST en DII, DIII y aVF."
    )

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "CardiologyAgent"
    assert len(result.findings) > 0
    assert 0.0 <= result.confidence <= 1.0


@patch("app.agents.cardiology.create_llm")
@patch("app.agents.cardiology.get_retriever")
async def test_cardiology_agent_flags_ecg_emergencies(mock_retriever, mock_create_llm):
    """CardiologyAgent incluye red_flags ante urgencias cardiológicas."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("CardiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = CardiologyAgent()
    result = await agent.run(
        "Taquicardia ventricular sostenida. FC 180 lpm. Inestabilidad hemodinámica."
    )

    assert len(result.red_flags) > 0


# ─── PharmacologyAgent ─────────────────────────────────────────────────────────

@patch("app.agents.pharmacology.create_llm")
@patch("app.agents.pharmacology.get_retriever")
async def test_pharmacology_agent_returns_agent_output(mock_retriever, mock_create_llm):
    """PharmacologyAgent devuelve AgentOutput válido."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("PharmacologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = PharmacologyAgent()
    result = await agent.run(
        "Paciente con warfarina, amiodarona y AAS. Solicita revisión de interacciones."
    )

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "PharmacologyAgent"
    assert len(result.recommendations) > 0


@patch("app.agents.pharmacology.create_llm")
@patch("app.agents.pharmacology.get_retriever")
async def test_pharmacology_agent_handles_no_red_flags(mock_retriever, mock_create_llm):
    """PharmacologyAgent funciona correctamente con medicación de bajo riesgo."""
    response = {**make_agent_response("PharmacologyAgent"), "red_flags": []}
    mock_create_llm.return_value = make_fake_llm(response)
    mock_retriever.return_value = make_fake_retriever()

    agent = PharmacologyAgent()
    result = await agent.run(
        "Paciente con paracetamol 1g cada 8h. Sin otras medicaciones ni alergias."
    )

    assert result.red_flags == []


# ─── RadiologyAgent ────────────────────────────────────────────────────────────

@patch("app.agents.radiology.create_llm")
@patch("app.agents.radiology.get_retriever")
async def test_radiology_agent_returns_agent_output(mock_retriever, mock_create_llm):
    """RadiologyAgent devuelve AgentOutput válido."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("RadiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = RadiologyAgent()
    result = await agent.run(
        "RX tórax PA: opacidad en base derecha, borramiento del seno costofrénico."
    )

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "RadiologyAgent"
    assert len(result.findings) > 0


@patch("app.agents.radiology.create_llm")
@patch("app.agents.radiology.get_retriever")
async def test_radiology_agent_includes_recommendations(mock_retriever, mock_create_llm):
    """RadiologyAgent propone recomendaciones de seguimiento radiológico."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("RadiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = RadiologyAgent()
    result = await agent.run(
        "TAC abdominal con contraste: masa hepática de 3cm con realce en fase arterial."
    )

    assert len(result.recommendations) > 0
    assert 0.0 <= result.confidence <= 1.0
