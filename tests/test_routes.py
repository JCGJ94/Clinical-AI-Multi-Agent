import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.clinical import AgentOutput


MOCK_AGENT_OUTPUT = AgentOutput(
    agent_name="ClinicalAgent",
    summary="Paciente con síntomas compatibles con síndrome coronario agudo.",
    findings=["dolor torácico", "hipertensión"],
    red_flags=["posible IAM"],
    recommendations=["ECG urgente"],
    confidence=0.87,
    context_sources=[],
)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def mock_clinical_agent():
    """Mockea ClinicalAgent en todas las pruebas de rutas — sin llamadas reales a la API."""
    with patch(
        "app.routes.clinical.ClinicalAgent.run",
        new=AsyncMock(return_value=MOCK_AGENT_OUTPUT),
    ):
        yield


# ─── Triage ──────────────────────────────────────────────────

async def test_triage_returns_valid_structure(client: AsyncClient):
    response = await client.post("/clinical-case/triage", json={
        "texto_clinico": "Paciente de 62 años con dolor torácico y disnea",
        "sintomas": ["dolor_toracico", "disnea"],
    })

    assert response.status_code == 200
    data = response.json()
    assert data["nivel_urgencia"] in ["CRITICO", "MUY_URGENTE", "URGENTE", "NO_URGENTE"]
    assert isinstance(data["agentes_sugeridos"], list)
    assert len(data["agentes_sugeridos"]) > 0
    assert isinstance(data["razonamiento"], str)


async def test_triage_rejects_empty_sintomas(client: AsyncClient):
    response = await client.post("/clinical-case/triage", json={
        "texto_clinico": "Paciente con dolor torácico",
        "sintomas": [],
    })
    assert response.status_code == 422


async def test_triage_rejects_short_texto(client: AsyncClient):
    response = await client.post("/clinical-case/triage", json={
        "texto_clinico": "corto",
        "sintomas": ["dolor"],
    })
    assert response.status_code == 422


# ─── Analyze ─────────────────────────────────────────────────

async def test_analyze_returns_valid_structure(client: AsyncClient):
    response = await client.post("/clinical-case/analyze", json={
        "caso_clinico": "Paciente de 62 años con dolor torácico, hipertensión y antecedentes de tabaquismo.",
    })

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["summary"], str)
    assert isinstance(data["findings"], list)
    assert isinstance(data["red_flags"], list)
    assert isinstance(data["recommendations"], list)
    assert 0.0 <= data["confidence"] <= 1.0
    assert isinstance(data["agentes_activados"], list)
    assert isinstance(data["agent_outputs"], list)


async def test_analyze_accepts_nivel_urgencia(client: AsyncClient):
    response = await client.post("/clinical-case/analyze", json={
        "caso_clinico": "Paciente de 45 años con dolor torácico agudo irradiado al brazo izquierdo.",
        "nivel_urgencia": "CRITICO",
    })
    assert response.status_code == 200


async def test_analyze_rejects_invalid_nivel_urgencia(client: AsyncClient):
    response = await client.post("/clinical-case/analyze", json={
        "caso_clinico": "Paciente con síntomas leves y malestar general.",
        "nivel_urgencia": "INVENTADO",
    })
    assert response.status_code == 422
