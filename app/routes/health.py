from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: datetime
    llm_provider: str | None = None


class CheckStatus(BaseModel):
    ok: bool
    detail: str | None = None


class ReadyResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
    checks: dict[str, CheckStatus]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    settings = get_settings()
    llm_provider = settings.llm_provider if settings.health_expose_details else None

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.now(UTC),
        llm_provider=llm_provider,
    )


async def _check_database(enabled: bool) -> CheckStatus:
    if not enabled:
        return CheckStatus(ok=True, detail="db check disabled")

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        return CheckStatus(ok=False, detail=str(exc))

    return CheckStatus(ok=True)


@router.get("/ready", response_model=ReadyResponse)
async def readiness_check(request: Request, response: Response) -> ReadyResponse:
    settings = get_settings()
    startup_completed = bool(getattr(request.app.state, "startup_completed", False))
    startup_error = getattr(request.app.state, "startup_error", None)

    checks = {
        "startup": CheckStatus(ok=startup_completed, detail=startup_error),
        "database": await _check_database(settings.readiness_check_db),
    }

    is_ready = all(check.ok for check in checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadyResponse(
        status="ready" if is_ready else "not_ready",
        version=settings.app_version,
        timestamp=datetime.now(UTC),
        checks=checks,
    )
