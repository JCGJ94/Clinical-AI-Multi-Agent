from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import get_settings
from app.main import app, lifespan


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_lifespan_runs_create_all_when_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "create_all")

    mock_initialize_database = AsyncMock()

    with (
        patch("app.main.setup_logging"),
        patch("app.main._initialize_database", new=mock_initialize_database),
    ):
        async with lifespan(app):
            assert app.state.startup_completed is True
            assert app.state.startup_error is None

    mock_initialize_database.assert_awaited_once_with("create_all")


@pytest.mark.asyncio
async def test_lifespan_skips_create_all_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "skip")

    mock_initialize_database = AsyncMock()

    with (
        patch("app.main.setup_logging"),
        patch("app.main._initialize_database", new=mock_initialize_database),
    ):
        async with lifespan(app):
            assert app.state.startup_completed is True
            assert app.state.startup_error is None

    mock_initialize_database.assert_awaited_once_with("skip")


@pytest.mark.asyncio
async def test_lifespan_marks_error_when_init_fails_and_fail_fast_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "create_all")
    monkeypatch.setenv("FAIL_STARTUP_ON_INIT_ERROR", "false")

    with (
        patch("app.main.setup_logging"),
        patch(
            "app.main._initialize_database",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        async with lifespan(app):
            assert app.state.startup_completed is False
            assert "boom" in app.state.startup_error


@pytest.mark.asyncio
async def test_lifespan_raises_when_init_fails_and_fail_fast_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STARTUP_DB_INIT_MODE", "create_all")
    monkeypatch.setenv("FAIL_STARTUP_ON_INIT_ERROR", "true")

    with (
        patch("app.main.setup_logging"),
        patch(
            "app.main._initialize_database",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            async with lifespan(app):
                pass
