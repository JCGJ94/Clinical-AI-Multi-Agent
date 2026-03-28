from fastapi import APIRouter
from datetime import datetime, UTC
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
    llm_provider: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        timestamp=datetime.now(UTC),
        llm_provider=settings.llm_provider,
    )
