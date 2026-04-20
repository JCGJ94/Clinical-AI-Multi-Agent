import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.core.config import get_settings
from app.main import app
from app.routes.health import CheckStatus


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_returns_ok(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "skip")
    monkeypatch.setenv("HEALTH_EXPOSE_DETAILS", "true")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "Clinical AI Multi-Agent"
    assert "version" in data
    assert "timestamp" in data
    assert data["llm_provider"] == "groq"


def test_health_hides_internal_details_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "skip")
    monkeypatch.setenv("HEALTH_EXPOSE_DETAILS", "false")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["llm_provider"] is None


def test_ready_returns_ok_when_startup_complete_and_db_check_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "skip")
    monkeypatch.setenv("READINESS_CHECK_DB", "false")

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["startup"]["ok"] is True
    assert data["checks"]["database"]["ok"] is True


def test_ready_returns_503_when_database_check_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "skip")
    monkeypatch.setenv("READINESS_CHECK_DB", "true")

    with patch(
        "app.routes.health._check_database",
        new=AsyncMock(return_value=CheckStatus(ok=False, detail="db down")),
    ):
        with TestClient(app) as client:
            response = client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["startup"]["ok"] is True
    assert data["checks"]["database"]["ok"] is False
    assert "db down" in data["checks"]["database"]["detail"]
