"""
FastAPI app con lifespan.

¿Qué es lifespan?
─────────────────
Lifespan es el ciclo de vida de la app: startup y shutdown.
Antes de lifespan, FastAPI usaba @app.on_event("startup") (deprecated).

El patrón con lifespan:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # STARTUP: código antes del yield
        yield
        # SHUTDOWN: código después del yield

Todo lo que ponés antes del yield se ejecuta cuando arranca el servidor.
Todo lo que ponés después del yield se ejecuta cuando se detiene.

¿Por qué creamos las tablas en startup?
  Para desarrollo y tests en SQLite, `create_all()` crea todas las tablas
  definidas en Base.metadata si no existen. Es el modo "simple" sin Alembic.

  En producción con Postgres:
    - NO uses create_all() → usás `alembic upgrade head` antes de arrancar
    - create_all() puede silenciar problemas de schema (no detecta columnas eliminadas)
    - Alembic tiene historial, rollback, y genera SQL verificable
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.exceptions import ClinicalBaseError
from app.routes.health import router as health_router
from app.routes.clinical import router as clinical_router
from app.db.session import engine
from app.db.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    # create_all(): crea tablas si no existen — idempotente (no falla si ya existen)
    # Útil en dev y tests. En prod: usar `alembic upgrade head` en lugar de esto.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield  # la app corre acá

    # SHUTDOWN
    # Cerramos el engine correctamente — libera conexiones del pool
    await engine.dispose()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)


@app.exception_handler(ClinicalBaseError)
async def clinical_error_handler(request: Request, exc: ClinicalBaseError) -> JSONResponse:
    """
    Handler global para todas las excepciones del sistema clínico.

    ¿Cómo funciona exception_handler en FastAPI?
    ─────────────────────────────────────────────
    FastAPI permite registrar handlers para tipos específicos de excepción.
    Cuando una excepción no capturada de ese tipo sube hasta el middleware,
    FastAPI llama a este handler en lugar de devolver un 500 genérico.

    ¿Por qué respuesta JSON estructurada?
    ──────────────────────────────────────
    El cliente (frontend médico, otro microservicio) necesita saber:
      1. QUÉ tipo de error ocurrió (para mostrar mensaje apropiado)
      2. QUÉ detalle tiene el error (para debugging)
      3. QUÉ status HTTP corresponde

    Un 500 genérico con "Internal Server Error" no sirve para nada.
    Este formato permite al cliente hacer:
      if error.error == "AllAgentsFailedError": mostrar_alerta_critica()
      if error.error == "LLMProviderError": mostrar_retry_button()

    type(exc).__name__ devuelve el nombre de la clase de la excepción.
    Para AgentExecutionError → "AgentExecutionError"
    Para AllAgentsFailedError → "AllAgentsFailedError"
    Así el cliente puede discriminar sin hardcodear mensajes.
    """
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "detail": exc.message,
            "status_code": 500,
        },
    )


app.include_router(health_router)
app.include_router(clinical_router)
