import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.clinical import ClinicalAgent
from app.models.clinical import AgentOutput


def make_mock_response(content: dict) -> MagicMock:
    """Construye una respuesta falsa con la misma forma que devuelve la API de OpenAI."""
    message = MagicMock()
    message.content = json.dumps(content)

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


VALID_AGENT_RESPONSE = {
    "agent_name": "ClinicalAgent",
    "summary": "Paciente con síntomas compatibles con síndrome coronario agudo.",
    "findings": ["dolor torácico irradiado", "hipertensión", "tabaquismo"],
    "red_flags": ["posible IAM — requiere ECG urgente"],
    "recommendations": ["ECG inmediato", "troponinas", "derivación urgencias"],
    "confidence": 0.87,
    "context_sources": [],
}


async def test_clinical_agent_returns_agent_output():
    """El agente devuelve un AgentOutput válido cuando el LLM responde correctamente."""
    mock_response = make_mock_response(VALID_AGENT_RESPONSE)

    with patch("app.agents.clinical.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        agent = ClinicalAgent()
        result = await agent.run("Paciente 62 años con dolor torácico irradiado al brazo izquierdo.")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "ClinicalAgent"
    assert len(result.findings) > 0
    assert 0.0 <= result.confidence <= 1.0


async def test_clinical_agent_maps_red_flags():
    """Las red_flags del LLM se mapean correctamente al modelo."""
    mock_response = make_mock_response(VALID_AGENT_RESPONSE)

    with patch("app.agents.clinical.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        agent = ClinicalAgent()
        result = await agent.run("Paciente con dolor torácico agudo.")

    assert len(result.red_flags) > 0
    assert "posible IAM — requiere ECG urgente" in result.red_flags


async def test_clinical_agent_handles_empty_red_flags():
    """El agente funciona correctamente cuando no hay red_flags."""
    response_without_flags = {**VALID_AGENT_RESPONSE, "red_flags": []}
    mock_response = make_mock_response(response_without_flags)

    with patch("app.agents.clinical.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        agent = ClinicalAgent()
        result = await agent.run("Paciente con resfriado común sin complicaciones.")

    assert result.red_flags == []
