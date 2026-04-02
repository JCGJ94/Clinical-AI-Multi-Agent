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
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
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

app.include_router(health_router)
app.include_router(clinical_router)
