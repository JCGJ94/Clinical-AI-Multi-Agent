"""
Tests — llm-agnostic-provider (T9–T12).

Cubren los cambios introducidos en esta feature:
  T9:  create_llm() con OPENAI_COMPATIBLE crea ChatOpenAI con base_url correcto
  T10: _safe_run() con RateLimitError "insufficient_quota" levanta ProviderQuotaError
  T11: El endpoint HTTP devuelve 503 cuando ProviderQuotaError es lanzada
  T12: get_embeddings() con EMBEDDING_PROVIDER=lmstudio devuelve OpenAIEmbeddings
       apuntando al base_url de LM Studio

Todos los tests siguen el patrón de mocking establecido en test_llm_factory.py
y test_routes.py — nunca tocan servicios reales.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.session import get_session
from app.core.llm import create_llm, LLMProvider
from app.core.exceptions import ProviderQuotaError, LLMProviderError
from app.rag.embeddings import get_embeddings
from langchain_openai import OpenAIEmbeddings


# ─── Helpers ────────────────────────────────────────────────────────────────────

def make_mock_settings_for_llm(
    provider: str,
    llm_base_url: str | None = None,
    llm_api_key: str | None = None,
    llm_model: str = "test-model",
    groq_api_key: str = "test-groq-key",
    openai_api_key: str = "test-openai-key",
    lmstudio_base_url: str = "http://localhost:1234/v1",
) -> MagicMock:
    """Stub de Settings para tests de create_llm()."""
    mock = MagicMock()
    mock.llm_provider = provider
    mock.llm_base_url = llm_base_url
    mock.llm_api_key = llm_api_key
    mock.llm_model = llm_model
    mock.groq_api_key = groq_api_key
    mock.openai_api_key = openai_api_key
    mock.lmstudio_base_url = lmstudio_base_url
    return mock


def make_mock_settings_for_embeddings(
    embedding_provider: str = "openai",
    openai_api_key: str = "test-openai-key",
    lmstudio_base_url: str = "http://localhost:1234/v1",
    embedding_model: str = "text-embedding-3-small",
) -> MagicMock:
    """Stub de Settings para tests de get_embeddings()."""
    mock = MagicMock()
    mock.embedding_provider = embedding_provider
    mock.openai_api_key = openai_api_key
    mock.lmstudio_base_url = lmstudio_base_url
    mock.embedding_model = embedding_model
    return mock


def make_fake_session():
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


# ─── T9: create_llm() con OPENAI_COMPATIBLE ─────────────────────────────────────

@patch("app.core.llm.get_settings")
@patch("app.core.llm.ChatOpenAI")
def test_create_llm_openai_compatible_uses_correct_base_url(MockChatOpenAI, mock_get_settings):
    """
    T9 — Con proveedor 'openai_compatible', create_llm() crea ChatOpenAI
    usando llm_base_url y llm_api_key de Settings.

    Esto permite conectar a cualquier API compatible con OpenAI
    (Nvidia NIM, DeepSeek, etc.) sin cambiar el código de los agentes.
    """
    mock_get_settings.return_value = make_mock_settings_for_llm(
        provider="openai_compatible",
        llm_base_url="https://integrate.api.nvidia.com/v1",
        llm_api_key="nvapi-test-key",
    )
    fake_instance = MagicMock()
    MockChatOpenAI.return_value = fake_instance

    result = create_llm(temperature=0.2)

    MockChatOpenAI.assert_called_once()
    call_kwargs = MockChatOpenAI.call_args[1]
    assert call_kwargs["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert call_kwargs["api_key"] == "nvapi-test-key"
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["temperature"] == 0.2
    assert result is fake_instance


@patch("app.core.llm.get_settings")
@patch("app.core.llm.ChatOpenAI")
def test_create_llm_openai_compatible_enum_value(MockChatOpenAI, mock_get_settings):
    """
    T9b — LLMProvider.OPENAI_COMPATIBLE existe con valor 'openai_compatible'.

    El enum debe tener el nuevo miembro para que la comparación interna funcione.
    """
    assert LLMProvider.OPENAI_COMPATIBLE == "openai_compatible"

    mock_get_settings.return_value = make_mock_settings_for_llm(
        provider="openai_compatible",
        llm_base_url="https://api.deepseek.com/v1",
        llm_api_key="sk-deepseek-test",
    )
    MockChatOpenAI.return_value = MagicMock()

    # No debe levantar ValueError — el proveedor es válido
    result = create_llm()
    assert result is not None


# ─── T10: _safe_run() con RateLimitError → ProviderQuotaError ───────────────────

async def test_safe_run_insufficient_quota_raises_provider_quota_error():
    """
    T10 — Cuando el agente levanta openai.RateLimitError con 'insufficient_quota',
    _safe_run() debe capturar ese error ANTES del except Exception genérico
    y levanta ProviderQuotaError en su lugar.

    ProviderQuotaError es no-retryable y mapea a HTTP 503.
    """
    import openai
    from app.services.integrator import _safe_run

    # Construimos un RateLimitError con código "insufficient_quota"
    rate_limit_error = openai.RateLimitError(
        message="You exceeded your current quota, please check your plan and billing details.",
        response=MagicMock(
            status_code=429,
            headers={},
            request=MagicMock(),
        ),
        body={"error": {"code": "insufficient_quota", "message": "quota exceeded"}},
    )

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(side_effect=rate_limit_error)

    with pytest.raises(ProviderQuotaError):
        await _safe_run(mock_agent, "ClinicalAgent", "caso clínico de prueba", timeout=5.0)


async def test_safe_run_rate_limit_without_quota_raises_llm_provider_error():
    """
    T10b — Un RateLimitError genérico (sin 'insufficient_quota') sube como
    LLMProviderError, que sí es retryable.

    La distinción importa: quota exhausted → no reintentar; rate limit temporal → sí.
    """
    import openai
    from app.services.integrator import _safe_run

    # RateLimitError sin código "insufficient_quota"
    rate_limit_error = openai.RateLimitError(
        message="Rate limit exceeded. Please retry after 1 minute.",
        response=MagicMock(
            status_code=429,
            headers={},
            request=MagicMock(),
        ),
        body={"error": {"code": "rate_limit_exceeded", "message": "too many requests"}},
    )

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(side_effect=rate_limit_error)

    with pytest.raises(LLMProviderError):
        await _safe_run(mock_agent, "ClinicalAgent", "caso clínico de prueba", timeout=5.0)


# ─── T11: HTTP 503 cuando ProviderQuotaError es lanzada ─────────────────────────

@pytest.fixture
async def client_with_db_override():
    """Cliente HTTP con la DB mockeada para evitar conexiones a Postgres."""
    app.dependency_overrides[get_session] = lambda: make_fake_session()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()


async def test_provider_quota_error_returns_503(client_with_db_override: AsyncClient):
    """
    T11 — Cuando el endpoint /clinical-case/analyze levanta ProviderQuotaError,
    el exception handler devuelve HTTP 503 (Service Unavailable).

    Antes de este cambio, TODOS los errores devolvían 500 — incluyendo
    errores de quota que indican "el servicio externo no está disponible".
    """
    from app.models.clinical import TriageOutput, NivelUrgencia

    mock_triage_output = TriageOutput(
        nivel_urgencia=NivelUrgencia.URGENTE,
        agentes_sugeridos=["ClinicalAgent"],
        razonamiento="Evaluación necesaria.",
    )

    with (
        patch(
            "app.routes.clinical.AgentRouter",
            return_value=MagicMock(run=AsyncMock(return_value=mock_triage_output)),
        ),
        patch(
            "app.routes.clinical.Integrator",
            return_value=MagicMock(
                analyze=AsyncMock(side_effect=ProviderQuotaError("quota exhausted"))
            ),
        ),
        patch(
            "app.routes.clinical.ClinicalCaseRepository.save",
            new=AsyncMock(return_value=MagicMock(id=99)),
        ),
        patch(
            "app.routes.clinical.ClinicalCaseRepository.get_by_id",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = await client_with_db_override.post(
            "/clinical-case/analyze",
            json={"caso_clinico": "Paciente con dolor torácico severo."},
        )

    assert response.status_code == 503
    data = response.json()
    assert data["error"] == "ProviderQuotaError"


async def test_all_agents_failed_error_returns_500(client_with_db_override: AsyncClient):
    """
    T11b — AllAgentsFailedError continúa mapeando a HTTP 500.

    Verificamos que el _STATUS_MAP no rompió los códigos de error existentes.
    """
    from app.core.exceptions import AllAgentsFailedError
    from app.models.clinical import TriageOutput, NivelUrgencia

    mock_triage_output = TriageOutput(
        nivel_urgencia=NivelUrgencia.URGENTE,
        agentes_sugeridos=["ClinicalAgent"],
        razonamiento="Evaluación necesaria.",
    )

    with (
        patch(
            "app.routes.clinical.AgentRouter",
            return_value=MagicMock(run=AsyncMock(return_value=mock_triage_output)),
        ),
        patch(
            "app.routes.clinical.Integrator",
            return_value=MagicMock(
                analyze=AsyncMock(
                    side_effect=AllAgentsFailedError(
                        agent_names=["ClinicalAgent"],
                        errors=[RuntimeError("fallo")],
                    )
                )
            ),
        ),
        patch(
            "app.routes.clinical.ClinicalCaseRepository.save",
            new=AsyncMock(return_value=MagicMock(id=99)),
        ),
    ):
        response = await client_with_db_override.post(
            "/clinical-case/analyze",
            json={"caso_clinico": "Paciente con dolor torácico severo."},
        )

    assert response.status_code == 500


# ─── T12: get_embeddings() con EMBEDDING_PROVIDER=lmstudio ──────────────────────

@patch("app.rag.embeddings.get_settings")
@patch("app.rag.embeddings.OpenAIEmbeddings")
def test_get_embeddings_lmstudio_uses_local_base_url(MockOpenAIEmbeddings, mock_get_settings):
    """
    T12 — Con EMBEDDING_PROVIDER=lmstudio, get_embeddings() devuelve
    OpenAIEmbeddings apuntando al base_url de LM Studio.

    LM Studio expone una API compatible con OpenAI para embeddings —
    podemos usar el mismo cliente cambiando solo el base_url y api_key.
    """
    mock_get_settings.return_value = make_mock_settings_for_embeddings(
        embedding_provider="lmstudio",
        lmstudio_base_url="http://localhost:1234/v1",
    )
    fake_instance = MagicMock()
    MockOpenAIEmbeddings.return_value = fake_instance

    result = get_embeddings()

    MockOpenAIEmbeddings.assert_called_once()
    call_kwargs = MockOpenAIEmbeddings.call_args[1]
    assert call_kwargs["base_url"] == "http://localhost:1234/v1"
    assert call_kwargs["api_key"] == "lm-studio"
    assert result is fake_instance


@patch("app.rag.embeddings.get_settings")
@patch("app.rag.embeddings.OpenAIEmbeddings")
def test_get_embeddings_openai_default(MockOpenAIEmbeddings, mock_get_settings):
    """
    T12b — Con EMBEDDING_PROVIDER=openai (default), el comportamiento existente
    se mantiene: usa openai_api_key sin base_url personalizado.

    Verificamos que el refactor no rompió el caso de uso original.
    """
    mock_get_settings.return_value = make_mock_settings_for_embeddings(
        embedding_provider="openai",
        openai_api_key="test-openai-key",
    )
    fake_instance = MagicMock()
    MockOpenAIEmbeddings.return_value = fake_instance

    result = get_embeddings()

    MockOpenAIEmbeddings.assert_called_once()
    call_kwargs = MockOpenAIEmbeddings.call_args[1]
    assert call_kwargs["api_key"] == "test-openai-key"
    # No debe pasar base_url para OpenAI (usa el default de OpenAI)
    assert "base_url" not in call_kwargs or call_kwargs.get("base_url") is None
    assert result is fake_instance
