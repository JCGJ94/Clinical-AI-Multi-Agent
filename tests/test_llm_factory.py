"""
Tests del LLM Factory — Fase 11.

¿Qué probamos aquí?
────────────────────
La función create_llm() es la pieza central de Fase 11 — si falla, TODOS
los agentes fallan. Por eso necesita sus propios tests exhaustivos.

Estos tests verifican:
  1. Que create_llm() devuelve el tipo correcto según el proveedor
  2. Que la temperature se pasa correctamente a la instancia
  3. Que los parámetros de conexión (api_key, base_url) se usan correctamente
  4. Que un proveedor inválido lanza ValueError con mensaje claro

Patrón de mocking en este módulo:
────────────────────────────────────
Acá usamos una estrategia diferente a los tests de agentes.
En los tests de agentes mockeamos create_llm completa — la reemplazamos por
una función que devuelve un LLM falso.

Aquí queremos testear create_llm INTERNAMENTE — ver qué instancia crea.
Por eso mockeamos ChatGroq y ChatOpenAI DENTRO de app.core.llm:
  @patch("app.core.llm.ChatGroq")
  @patch("app.core.llm.ChatOpenAI")

Si parcheáramos en otro módulo, create_llm() vería las clases reales.
Al parchear donde se DEFINEN (que es también donde se USAN dentro de llm.py),
interceptamos la instanciación antes de que ocurra.

¿Por qué mockeamos get_settings()?
────────────────────────────────────
create_llm() llama get_settings() internamente. En tests, NO queremos leer
variables de entorno — queremos controlar exactamente qué configuración recibe.

get_settings() usa @lru_cache, lo que significa que devuelve SIEMPRE la misma
instancia cacheada. Si en el test anterior se cargó "groq", el siguiente test
recibirá "groq" también.

Solución: @patch("app.core.llm.get_settings") para reemplazar get_settings
dentro del módulo llm.py. Cada test inyecta su propia instancia de Settings.

¿Cómo construimos el Settings falso?
──────────────────────────────────────
Usamos MagicMock() — un objeto que responde a cualquier atributo sin error.
  mock_settings = MagicMock()
  mock_settings.llm_provider = "groq"
  mock_settings.groq_api_key = "test-groq-key"

Es la forma más limpia de crear un stub de Settings sin instanciar
la clase real (que leería .env y variables de entorno).
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.llm import create_llm, LLMProvider


def make_mock_settings(
    provider: str,
    groq_api_key: str = "test-groq-key",
    openai_api_key: str = "test-openai-key",
    lmstudio_base_url: str = "http://localhost:1234/v1",
    llm_model: str = "test-model",
) -> MagicMock:
    """
    Crea un mock de Settings con los valores indicados.

    MagicMock permite acceder a cualquier atributo — esto es útil para
    simular Settings sin instanciar la clase real (que lee .env).

    Parámetros:
        provider: valor de llm_provider (ej: "groq", "openai", "lmstudio")
        groq_api_key: clave de API de Groq (fake para tests)
        openai_api_key: clave de API de OpenAI (fake para tests)
        lmstudio_base_url: URL del servidor LM Studio
        llm_model: nombre del modelo (irrelevante en tests, pero requerido)
    """
    mock = MagicMock()
    mock.llm_provider = provider
    mock.groq_api_key = groq_api_key
    mock.openai_api_key = openai_api_key
    mock.lmstudio_base_url = lmstudio_base_url
    mock.llm_model = llm_model
    return mock


# ─── Tests de tipo devuelto por proveedor ──────────────────────────────────────

@patch("app.core.llm.get_settings")
@patch("app.core.llm.ChatGroq")
def test_create_llm_groq(MockChatGroq, mock_get_settings):
    """Con proveedor 'groq', create_llm devuelve una instancia de ChatGroq.

    Verificamos que:
      1. ChatGroq se instancia UNA vez
      2. Se le pasan los parámetros correctos (api_key, model, temperature)
      3. El retorno es la instancia que creó ChatGroq
    """
    mock_get_settings.return_value = make_mock_settings(provider="groq")
    fake_instance = MagicMock()
    MockChatGroq.return_value = fake_instance

    result = create_llm(temperature=0.2)

    MockChatGroq.assert_called_once()
    call_kwargs = MockChatGroq.call_args[1]
    assert call_kwargs["api_key"] == "test-groq-key"
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["temperature"] == 0.2
    assert result is fake_instance


@patch("app.core.llm.get_settings")
@patch("app.core.llm.ChatOpenAI")
def test_create_llm_openai(MockChatOpenAI, mock_get_settings):
    """Con proveedor 'openai', create_llm devuelve una instancia de ChatOpenAI.

    Verificamos que se pasan openai_api_key, model y temperature — sin base_url.
    La ausencia de base_url es lo que diferencia OpenAI de LM Studio.
    """
    mock_get_settings.return_value = make_mock_settings(provider="openai")
    fake_instance = MagicMock()
    MockChatOpenAI.return_value = fake_instance

    result = create_llm(temperature=0.5)

    MockChatOpenAI.assert_called_once()
    call_kwargs = MockChatOpenAI.call_args[1]
    assert call_kwargs["api_key"] == "test-openai-key"
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["temperature"] == 0.5
    assert result is fake_instance


@patch("app.core.llm.get_settings")
@patch("app.core.llm.ChatOpenAI")
def test_create_llm_lmstudio(MockChatOpenAI, mock_get_settings):
    """Con proveedor 'lmstudio', create_llm devuelve ChatOpenAI con base_url personalizada.

    LM Studio usa la API de OpenAI pero apuntando a un servidor local.
    La diferencia clave es:
      - base_url: apunta al servidor local (no a api.openai.com)
      - api_key="lm-studio": el placeholder que LM Studio espera

    Verificamos que base_url y api_key="lm-studio" están presentes.
    """
    mock_get_settings.return_value = make_mock_settings(
        provider="lmstudio",
        lmstudio_base_url="http://localhost:1234/v1",
    )
    fake_instance = MagicMock()
    MockChatOpenAI.return_value = fake_instance

    result = create_llm(temperature=0.1)

    MockChatOpenAI.assert_called_once()
    call_kwargs = MockChatOpenAI.call_args[1]
    assert call_kwargs["base_url"] == "http://localhost:1234/v1"
    assert call_kwargs["api_key"] == "lm-studio"
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["temperature"] == 0.1
    assert result is fake_instance


# ─── Tests de temperature ──────────────────────────────────────────────────────

@patch("app.core.llm.get_settings")
@patch("app.core.llm.ChatGroq")
def test_create_llm_respects_temperature(MockChatGroq, mock_get_settings):
    """La temperature se pasa exactamente como se especifica.

    Este test es importante porque temperature es el único parámetro que
    varía entre agentes. Si create_llm ignorara la temperature, TODOS los
    agentes usarían el valor por defecto (0.2) sin importar lo que pidan.

    Probamos varios valores para verificar que no hay hardcoding interno.
    """
    mock_get_settings.return_value = make_mock_settings(provider="groq")
    MockChatGroq.return_value = MagicMock()

    # temperature=0.0 → para el router (triage determinista)
    create_llm(temperature=0.0)
    call_kwargs = MockChatGroq.call_args[1]
    assert call_kwargs["temperature"] == 0.0

    MockChatGroq.reset_mock()

    # temperature=0.3 → para DifferentialDiagnosisAgent (más creatividad)
    create_llm(temperature=0.3)
    call_kwargs = MockChatGroq.call_args[1]
    assert call_kwargs["temperature"] == 0.3


# ─── Test de proveedor inválido ────────────────────────────────────────────────

@patch("app.core.llm.get_settings")
def test_create_llm_invalid_provider(mock_get_settings):
    """Un proveedor desconocido lanza ValueError con mensaje descriptivo.

    Principio de Fail-Fast: es mejor fallar inmediatamente con un mensaje
    claro que continuar con un comportamiento indefinido.

    El mensaje de error debe:
      1. Indicar cuál fue el proveedor inválido
      2. Listar los valores válidos
      3. Sugerir dónde corregirlo (LLM_PROVIDER en .env)
    """
    mock_get_settings.return_value = make_mock_settings(provider="proveedor_inexistente")

    with pytest.raises(ValueError) as exc_info:
        create_llm(temperature=0.2)

    error_msg = str(exc_info.value)
    assert "proveedor_inexistente" in error_msg
    # Verificamos que el mensaje menciona los valores válidos
    assert "groq" in error_msg
    assert "openai" in error_msg
    assert "lmstudio" in error_msg
