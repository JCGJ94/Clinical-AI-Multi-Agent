"""
Tests de routes — Fase 8.

Cambios respecto a Fase 6/7:
  - /analyze ahora persiste en DB vía ClinicalCaseRepository
  - /analyze devuelve case_id en la respuesta
  - GET /{case_id} es un endpoint nuevo

¿Cómo evitamos tocar la DB en tests de routes?
  FastAPI tiene `app.dependency_overrides` — permite reemplazar cualquier
  dependency de Depends() con una función alternativa en tests.

  app.dependency_overrides[get_session] = lambda: fake_session

  La fake_session es un MagicMock. El repository recibe el mock y
  sus métodos (add, commit, refresh) son AsyncMock que no hacen nada real.

  Combinamos esto con el mock de Integrator.analyze y AgentRouter.run
  para que los tests de routes no toquen LLM, PGVector ni PostgreSQL.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import get_session
from app.models.clinical import AgentOutput, AnalyzeOutput, TriageOutput, NivelUrgencia
from app.db.models import ClinicalCase
from datetime import datetime, timezone


MOCK_AGENT_OUTPUT = AgentOutput(
    agent_name="ClinicalAgent",
    summary="Paciente con síntomas compatibles con síndrome coronario agudo.",
    findings=["dolor torácico", "hipertensión"],
    red_flags=["posible IAM"],
    recommendations=["ECG urgente"],
    confidence=0.87,
    context_sources=[],
)

MOCK_ANALYZE_OUTPUT = AnalyzeOutput(
    case_id=None,
    summary="Paciente con síntomas compatibles con síndrome coronario agudo.",
    findings=["dolor torácico", "hipertensión"],
    red_flags=["posible IAM"],
    recommendations=["ECG urgente"],
    confidence=0.87,
    agentes_activados=["ClinicalAgent"],
    agent_outputs=[MOCK_AGENT_OUTPUT],
)

MOCK_TRIAGE_OUTPUT = TriageOutput(
    nivel_urgencia=NivelUrgencia.URGENTE,
    agentes_sugeridos=["ClinicalAgent", "DifferentialDiagnosisAgent"],
    razonamiento="Síntomas que requieren evaluación clínica.",
)

# Entidad ORM falsa que devuelve el repository al guardar
MOCK_SAVED_CASE = MagicMock(spec=ClinicalCase)
MOCK_SAVED_CASE.id = 42
MOCK_SAVED_CASE.caso_clinico = "Paciente de 62 años con dolor torácico."
MOCK_SAVED_CASE.agentes_sugeridos = None
MOCK_SAVED_CASE.summary = MOCK_ANALYZE_OUTPUT.summary
MOCK_SAVED_CASE.findings = MOCK_ANALYZE_OUTPUT.findings
MOCK_SAVED_CASE.red_flags = MOCK_ANALYZE_OUTPUT.red_flags
MOCK_SAVED_CASE.recommendations = MOCK_ANALYZE_OUTPUT.recommendations
MOCK_SAVED_CASE.confidence = MOCK_ANALYZE_OUTPUT.confidence
MOCK_SAVED_CASE.agentes_activados = MOCK_ANALYZE_OUTPUT.agentes_activados
MOCK_SAVED_CASE.created_at = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)


def make_fake_session():
    """
    Sesión SQLAlchemy falsa.
    No conecta a ninguna DB — todos sus métodos son AsyncMock o MagicMock.
    Se inyecta vía app.dependency_overrides[get_session].
    """
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
async def client():
    # Override de get_session para que no intente conectar a Postgres
    app.dependency_overrides[get_session] = lambda: make_fake_session()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_services():
    """
    Mockea AgentRouter, Integrator y ClinicalCaseRepository.
    """
    with patch("app.routes.clinical.AgentRouter.run", new=AsyncMock(return_value=MOCK_TRIAGE_OUTPUT)), \
         patch("app.routes.clinical.Integrator.analyze", new=AsyncMock(return_value=MOCK_ANALYZE_OUTPUT)), \
         patch("app.routes.clinical.ClinicalCaseRepository.save", new=AsyncMock(return_value=MOCK_SAVED_CASE)), \
         patch("app.routes.clinical.ClinicalCaseRepository.get_by_id", new=AsyncMock(return_value=MOCK_SAVED_CASE)):
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


async def test_analyze_returns_case_id(client: AsyncClient):
    """Fase 8: el analyze devuelve case_id del caso persistido."""
    response = await client.post("/clinical-case/analyze", json={
        "caso_clinico": "Paciente de 62 años con dolor torácico, hipertensión.",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == 42


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


# ─── GET /{case_id} ──────────────────────────────────────────

async def test_get_case_returns_200(client: AsyncClient):
    """GET /{case_id} devuelve el caso persistido."""
    response = await client.get("/clinical-case/42")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 42
    assert isinstance(data["summary"], str)
    assert isinstance(data["findings"], list)


async def test_get_case_returns_404_for_missing(client: AsyncClient):
    """GET /{case_id} devuelve 404 si el caso no existe."""
    with patch("app.routes.clinical.ClinicalCaseRepository.get_by_id", new=AsyncMock(return_value=None)):
        response = await client.get("/clinical-case/99999")

    assert response.status_code == 404
