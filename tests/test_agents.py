"""
Tests de los agentes — Fase 5 (LangChain LCEL + RAG).

¿Qué cambió en Fase 11 (LLM Factory)?
────────────────────────────────────────
Antes de Fase 11, cada agente importaba ChatGroq y ChatOpenAI directamente.
Los tests mockeaban esas importaciones locales:
  @patch("app.agents.clinical.ChatGroq")

Desde Fase 11, los agentes usan create_llm() de app.core.llm.
La instanciación de ChatGroq/ChatOpenAI ocurre SOLO en ese módulo.

El nuevo patrón: mockear create_llm directamente.
  @patch("app.agents.clinical.create_llm")    ← mock en el módulo importador

¿Por qué mockeamos en el módulo importador y no en app.core.llm?
─────────────────────────────────────────────────────────────────
Python resuelve nombres en el momento en que se buscan, no cuando se definen.
Cuando clinical.py hace `from app.core.llm import create_llm`, crea una
referencia local `app.agents.clinical.create_llm`.
Si parcheás `app.core.llm.create_llm`, la referencia local en clinical.py
ya está resuelta y NO se ve afectada.
Por eso hay que parchear la referencia donde se USA, no donde se DEFINE.

También seguimos mockeando get_retriever — sigue siendo necesario para evitar
la conexión real a PGVector.

El flujo completo de la chain CON los mocks:
  "Paciente 62 años..."
    → fake_retriever (devuelve [doc1, doc2]) → format_docs → "[Fuente: ...]..."
    → RunnablePassthrough → "Paciente 62 años..."
    → prompt → [SystemMessage(context + instrucciones), HumanMessage(caso)]
    → fake_llm → AIMessage(content='{"agent_name": ...}')
    → parser → AgentOutput(agent_name=..., ...)
"""

import json
import pytest
from unittest.mock import patch
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage
from langchain_core.documents import Document

from app.agents.clinical import ClinicalAgent
from app.agents.emergency import EmergencyAgent
from app.agents.diagnosis import DifferentialDiagnosisAgent
from app.models.clinical import AgentOutput


# ─── Fixtures compartidos ──────────────────────────────────────────────────────

def make_agent_response(agent_name: str) -> dict:
    return {
        "agent_name": agent_name,
        "summary": "Paciente con síntomas compatibles con síndrome coronario agudo.",
        "findings": ["dolor torácico irradiado", "hipertensión", "tabaquismo"],
        "red_flags": ["posible IAM — requiere ECG urgente"],
        "recommendations": ["ECG inmediato", "troponinas", "derivación urgencias"],
        "confidence": 0.87,
        "context_sources": ["architecture/routing-rules.md"],
    }


def make_fake_llm(response: dict) -> RunnableLambda:
    """
    Fake LLM compatible con LCEL (igual que en Fase 3).
    Recibe los mensajes del prompt, los ignora, y devuelve el JSON hardcodeado.
    """
    return RunnableLambda(
        lambda _messages: AIMessage(content=json.dumps(response))
    )


def make_fake_retriever() -> RunnableLambda:
    """
    Fake retriever compatible con LCEL.
    Devuelve documentos hardcodeados sin tocar ninguna base de datos.

    En una chain, el retriever recibe la query (string) y devuelve Documents.
    RunnableLambda wrappea esa lógica — ignora la query y devuelve docs fijos.
    """
    return RunnableLambda(lambda _query: [
        Document(
            page_content="Si hay dolor torácico agudo → activar URGENCIAS primero.",
            metadata={"source": "architecture/routing-rules.md", "category": "architecture"},
        ),
        Document(
            page_content="STEMI: elevación del segmento ST, emergencia absoluta.",
            metadata={"source": "prompts/cardiology-agent.md", "category": "prompts"},
        ),
    ])


# ─── ClinicalAgent ─────────────────────────────────────────────────────────────

@patch("app.agents.clinical.create_llm")
@patch("app.agents.clinical.get_retriever")
async def test_clinical_agent_returns_agent_output(mock_retriever, mock_create_llm):
    """El agente devuelve un AgentOutput válido cuando la chain responde correctamente."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("ClinicalAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = ClinicalAgent()
    result = await agent.run("Paciente 62 años con dolor torácico irradiado al brazo izquierdo.")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "ClinicalAgent"
    assert len(result.findings) > 0
    assert 0.0 <= result.confidence <= 1.0


@patch("app.agents.clinical.create_llm")
@patch("app.agents.clinical.get_retriever")
async def test_clinical_agent_maps_red_flags(mock_retriever, mock_create_llm):
    """Las red_flags del LLM se mapean correctamente al modelo."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("ClinicalAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = ClinicalAgent()
    result = await agent.run("Paciente con dolor torácico agudo.")

    assert len(result.red_flags) > 0
    assert "posible IAM — requiere ECG urgente" in result.red_flags


@patch("app.agents.clinical.create_llm")
@patch("app.agents.clinical.get_retriever")
async def test_clinical_agent_handles_empty_red_flags(mock_retriever, mock_create_llm):
    """El agente funciona correctamente cuando no hay red_flags."""
    response = {**make_agent_response("ClinicalAgent"), "red_flags": []}
    mock_create_llm.return_value = make_fake_llm(response)
    mock_retriever.return_value = make_fake_retriever()

    agent = ClinicalAgent()
    result = await agent.run("Paciente con resfriado común sin complicaciones.")

    assert result.red_flags == []


# ─── EmergencyAgent ────────────────────────────────────────────────────────────

@patch("app.agents.emergency.create_llm")
@patch("app.agents.emergency.get_retriever")
async def test_emergency_agent_returns_agent_output(mock_retriever, mock_create_llm):
    """EmergencyAgent devuelve AgentOutput válido."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("EmergencyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = EmergencyAgent()
    result = await agent.run("Paciente con dolor torácico, hipotensión y diaforesis.")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "EmergencyAgent"


@patch("app.agents.emergency.create_llm")
@patch("app.agents.emergency.get_retriever")
async def test_emergency_agent_flags_critical_cases(mock_retriever, mock_create_llm):
    """EmergencyAgent marca red_flags en casos críticos."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("EmergencyAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = EmergencyAgent()
    result = await agent.run("Paciente inconsciente, sin pulso, cianosis.")

    assert len(result.red_flags) > 0


# ─── DifferentialDiagnosisAgent ────────────────────────────────────────────────

@patch("app.agents.diagnosis.create_llm")
@patch("app.agents.diagnosis.get_retriever")
async def test_diagnosis_agent_returns_agent_output(mock_retriever, mock_create_llm):
    """DifferentialDiagnosisAgent devuelve AgentOutput válido."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("DifferentialDiagnosisAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = DifferentialDiagnosisAgent()
    result = await agent.run("Paciente con fatiga crónica, pérdida de peso y sudoración nocturna.")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "DifferentialDiagnosisAgent"
    assert len(result.findings) > 0


@patch("app.agents.diagnosis.create_llm")
@patch("app.agents.diagnosis.get_retriever")
async def test_diagnosis_agent_generates_recommendations(mock_retriever, mock_create_llm):
    """El agente de diagnóstico diferencial genera recomendaciones."""
    mock_create_llm.return_value = make_fake_llm(make_agent_response("DifferentialDiagnosisAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = DifferentialDiagnosisAgent()
    result = await agent.run("Cuadro multisistémico sin diagnóstico claro.")

    assert len(result.recommendations) > 0
    assert 0.0 <= result.confidence <= 1.0
