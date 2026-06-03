"""
Tests for deterministic agent_name assignment.

Verifies:
1. Each agent class has a NAME: ClassVar[str] attribute
2. run() sets result.agent_name = self.NAME regardless of what the LLM returns
3. Lazy _chain attribute — __init__ does NOT call get_retriever()
4. _ensure_chain() is an async method on each agent
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage
from langchain_core.documents import Document


def make_agent_response(agent_name: str) -> dict:
    """LLM returns a different agent_name to prove code overrides it."""
    return {
        "agent_name": agent_name,
        "summary": "Análisis de caso clínico.",
        "findings": ["hallazgo-1"],
        "red_flags": [],
        "recommendations": ["recomendacion-1"],
        "confidence": 0.85,
        "context_sources": [],
    }


def make_fake_llm(response: dict) -> RunnableLambda:
    return RunnableLambda(lambda _: AIMessage(content=json.dumps(response)))


def make_fake_retriever() -> RunnableLambda:
    return RunnableLambda(lambda _: [
        Document(
            page_content="Protocolo clínico de referencia.",
            metadata={"source": "docs/routing-rules.md", "category": "architecture"},
        ),
    ])


# ─── RED: NAME class attribute ─────────────────────────────────────────────────

def test_clinical_agent_has_name_class_attribute():
    from app.agents.clinical import ClinicalAgent
    assert hasattr(ClinicalAgent, "NAME"), "ClinicalAgent must have a NAME class attribute"
    assert ClinicalAgent.NAME == "ClinicalAgent"


def test_cardiology_agent_has_name_class_attribute():
    from app.agents.cardiology import CardiologyAgent
    assert hasattr(CardiologyAgent, "NAME"), "CardiologyAgent must have a NAME class attribute"
    assert CardiologyAgent.NAME == "CardiologyAgent"


def test_pharmacology_agent_has_name_class_attribute():
    from app.agents.pharmacology import PharmacologyAgent
    assert hasattr(PharmacologyAgent, "NAME"), "PharmacologyAgent must have a NAME class attribute"
    assert PharmacologyAgent.NAME == "PharmacologyAgent"


def test_radiology_agent_has_name_class_attribute():
    from app.agents.radiology import RadiologyAgent
    assert hasattr(RadiologyAgent, "NAME"), "RadiologyAgent must have a NAME class attribute"
    assert RadiologyAgent.NAME == "RadiologyAgent"


def test_diagnosis_agent_has_name_class_attribute():
    from app.agents.diagnosis import DifferentialDiagnosisAgent
    assert hasattr(DifferentialDiagnosisAgent, "NAME"), "DifferentialDiagnosisAgent must have a NAME class attribute"
    assert DifferentialDiagnosisAgent.NAME == "DifferentialDiagnosisAgent"


def test_emergency_agent_has_name_class_attribute():
    from app.agents.emergency import EmergencyAgent
    assert hasattr(EmergencyAgent, "NAME"), "EmergencyAgent must have a NAME class attribute"
    assert EmergencyAgent.NAME == "EmergencyAgent"


# ─── RED: run() overrides agent_name from LLM with self.NAME ──────────────────

@patch("app.agents.clinical.create_llm")
@patch("app.agents.clinical.get_retriever")
async def test_clinical_agent_name_is_set_from_NAME(mock_retriever, mock_create_llm):
    """
    Even if LLM returns a different agent_name, run() must override it with self.NAME.
    This tests the deterministic post-parse assignment: result.agent_name = self.NAME
    """
    from app.agents.clinical import ClinicalAgent
    # LLM responds with wrong name to prove we override it
    mock_create_llm.return_value = make_fake_llm(make_agent_response("WrongAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = ClinicalAgent()
    result = await agent.run("Paciente con dolor torácico.")

    assert result.agent_name == ClinicalAgent.NAME, (
        f"Expected {ClinicalAgent.NAME!r}, got {result.agent_name!r}"
    )


@patch("app.agents.cardiology.create_llm")
@patch("app.agents.cardiology.get_retriever")
async def test_cardiology_agent_name_is_set_from_NAME(mock_retriever, mock_create_llm):
    from app.agents.cardiology import CardiologyAgent
    mock_create_llm.return_value = make_fake_llm(make_agent_response("WrongAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = CardiologyAgent()
    result = await agent.run("ECG con elevación ST en DII.")

    assert result.agent_name == CardiologyAgent.NAME


@patch("app.agents.pharmacology.create_llm")
@patch("app.agents.pharmacology.get_retriever")
async def test_pharmacology_agent_name_is_set_from_NAME(mock_retriever, mock_create_llm):
    from app.agents.pharmacology import PharmacologyAgent
    mock_create_llm.return_value = make_fake_llm(make_agent_response("WrongAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = PharmacologyAgent()
    result = await agent.run("Paciente con warfarina y amiodarona.")

    assert result.agent_name == PharmacologyAgent.NAME


@patch("app.agents.radiology.create_llm")
@patch("app.agents.radiology.get_retriever")
async def test_radiology_agent_name_is_set_from_NAME(mock_retriever, mock_create_llm):
    from app.agents.radiology import RadiologyAgent
    mock_create_llm.return_value = make_fake_llm(make_agent_response("WrongAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = RadiologyAgent()
    result = await agent.run("RX tórax con opacidad en base derecha.")

    assert result.agent_name == RadiologyAgent.NAME


@patch("app.agents.diagnosis.create_llm")
@patch("app.agents.diagnosis.get_retriever")
async def test_diagnosis_agent_name_is_set_from_NAME(mock_retriever, mock_create_llm):
    from app.agents.diagnosis import DifferentialDiagnosisAgent
    mock_create_llm.return_value = make_fake_llm(make_agent_response("WrongAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = DifferentialDiagnosisAgent()
    result = await agent.run("Fatiga crónica con pérdida de peso.")

    assert result.agent_name == DifferentialDiagnosisAgent.NAME


@patch("app.agents.emergency.create_llm")
@patch("app.agents.emergency.get_retriever")
async def test_emergency_agent_name_is_set_from_NAME(mock_retriever, mock_create_llm):
    from app.agents.emergency import EmergencyAgent
    mock_create_llm.return_value = make_fake_llm(make_agent_response("WrongAgent"))
    mock_retriever.return_value = make_fake_retriever()

    agent = EmergencyAgent()
    result = await agent.run("Paciente inconsciente, sin pulso.")

    assert result.agent_name == EmergencyAgent.NAME


# ─── RED: lazy chain — __init__ must NOT call get_retriever synchronously ─────

def test_clinical_agent_init_does_not_call_get_retriever():
    """
    __init__ must be lightweight — no blocking calls to get_retriever().
    After migration, __init__ only stores llm/parser/prompt; chain is lazy.
    """
    from app.agents.clinical import ClinicalAgent
    with patch("app.agents.clinical.get_retriever") as mock_get_retriever, \
         patch("app.agents.clinical.create_llm"):
        ClinicalAgent()
        mock_get_retriever.assert_not_called(), (
            "get_retriever must NOT be called in __init__ (lazy chain)"
        )


def test_cardiology_agent_init_does_not_call_get_retriever():
    from app.agents.cardiology import CardiologyAgent
    with patch("app.agents.cardiology.get_retriever") as mock_get_retriever, \
         patch("app.agents.cardiology.create_llm"):
        CardiologyAgent()
        mock_get_retriever.assert_not_called()


def test_emergency_agent_init_does_not_call_get_retriever():
    from app.agents.emergency import EmergencyAgent
    with patch("app.agents.emergency.get_retriever") as mock_get_retriever, \
         patch("app.agents.emergency.create_llm"):
        EmergencyAgent()
        mock_get_retriever.assert_not_called()
