"""
Tests de los agentes especialistas — Fase 7.

Patrón idéntico a test_agents.py (Fase 5):
  - dos @patch apilados: ChatGroq (outer) + get_retriever (inner)
  - El retriever más INTERNO → primer parámetro
  - El más EXTERNO → último parámetro

Los tres nuevos agentes (Cardiology, Pharmacology, Radiology) tienen exactamente
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

@patch("app.agents.cardiology.ChatGroq")
@patch("app.agents.cardiology.get_retriever")
async def test_cardiology_agent_returns_agent_output(mock_retriever, MockChatGroq):
    """CardiologyAgent devuelve AgentOutput válido."""
    MockChatGroq.return_value = make_fake_llm(make_agent_response("CardiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = CardiologyAgent()
    result = await agent.run(
        "Paciente 65 años, ECG con elevación ST en DII, DIII y aVF."
    )

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "CardiologyAgent"
    assert len(result.findings) > 0
    assert 0.0 <= result.confidence <= 1.0


@patch("app.agents.cardiology.ChatGroq")
@patch("app.agents.cardiology.get_retriever")
async def test_cardiology_agent_flags_ecg_emergencies(mock_retriever, MockChatGroq):
    """CardiologyAgent incluye red_flags ante urgencias cardiológicas."""
    MockChatGroq.return_value = make_fake_llm(make_agent_response("CardiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = CardiologyAgent()
    result = await agent.run(
        "Taquicardia ventricular sostenida. FC 180 lpm. Inestabilidad hemodinámica."
    )

    assert len(result.red_flags) > 0


# ─── PharmacologyAgent ─────────────────────────────────────────────────────────

@patch("app.agents.pharmacology.ChatGroq")
@patch("app.agents.pharmacology.get_retriever")
async def test_pharmacology_agent_returns_agent_output(mock_retriever, MockChatGroq):
    """PharmacologyAgent devuelve AgentOutput válido."""
    MockChatGroq.return_value = make_fake_llm(make_agent_response("PharmacologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = PharmacologyAgent()
    result = await agent.run(
        "Paciente con warfarina, amiodarona y AAS. Solicita revisión de interacciones."
    )

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "PharmacologyAgent"
    assert len(result.recommendations) > 0


@patch("app.agents.pharmacology.ChatGroq")
@patch("app.agents.pharmacology.get_retriever")
async def test_pharmacology_agent_handles_no_red_flags(mock_retriever, MockChatGroq):
    """PharmacologyAgent funciona correctamente con medicación de bajo riesgo."""
    response = {**make_agent_response("PharmacologyAgent"), "red_flags": []}
    MockChatGroq.return_value = make_fake_llm(response)
    mock_retriever.return_value = make_fake_retriever()

    agent = PharmacologyAgent()
    result = await agent.run(
        "Paciente con paracetamol 1g cada 8h. Sin otras medicaciones ni alergias."
    )

    assert result.red_flags == []


# ─── RadiologyAgent ────────────────────────────────────────────────────────────

@patch("app.agents.radiology.ChatGroq")
@patch("app.agents.radiology.get_retriever")
async def test_radiology_agent_returns_agent_output(mock_retriever, MockChatGroq):
    """RadiologyAgent devuelve AgentOutput válido."""
    MockChatGroq.return_value = make_fake_llm(make_agent_response("RadiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = RadiologyAgent()
    result = await agent.run(
        "RX tórax PA: opacidad en base derecha, borramiento del seno costofrénico."
    )

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "RadiologyAgent"
    assert len(result.findings) > 0


@patch("app.agents.radiology.ChatGroq")
@patch("app.agents.radiology.get_retriever")
async def test_radiology_agent_includes_recommendations(mock_retriever, MockChatGroq):
    """RadiologyAgent propone recomendaciones de seguimiento radiológico."""
    MockChatGroq.return_value = make_fake_llm(make_agent_response("RadiologyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = RadiologyAgent()
    result = await agent.run(
        "TAC abdominal con contraste: masa hepática de 3cm con realce en fase arterial."
    )

    assert len(result.recommendations) > 0
    assert 0.0 <= result.confidence <= 1.0
