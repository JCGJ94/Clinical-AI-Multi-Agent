from fastapi import FastAPI
from app.core.config import get_settings
from app.routes.health import router as health_router
from app.routes.clinical import router as clinical_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
)

app.include_router(health_router)
app.include_router(clinical_router)
