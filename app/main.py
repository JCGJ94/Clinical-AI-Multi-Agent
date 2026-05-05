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

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import (
    ClinicalBaseError,
    ProviderQuotaError,
    LLMProviderError,
    RAGRetrievalError,
    AllAgentsFailedError,
    AgentExecutionError,
    TriageError,
)
from app.core.logging import setup_logging, get_logger
from app.routes.health import router as health_router
from app.routes.clinical import router as clinical_router
from app.db.session import engine
from app.db.models import Base

logger = get_logger(__name__)


settings = get_settings()


def _mark_startup_state(app: FastAPI, *, completed: bool, error: str | None) -> None:
    app.state.startup_completed = completed
    app.state.startup_error = error


async def _initialize_database(init_mode: str) -> None:
    if init_mode != "create_all":
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    # setup_logging ANTES de cualquier otra inicialización para que
    # todos los eventos de startup queden registrados.
    # debug=settings.debug → DEBUG en desarrollo, INFO en producción.
    runtime_settings = get_settings()
    setup_logging(debug=runtime_settings.debug)
    _mark_startup_state(app, completed=False, error=None)

    try:
        # create_all(): crea tablas si no existen — idempotente (no falla si ya existen)
        # Útil en dev y tests. En prod: usar `alembic upgrade head` en lugar de esto.
        await _initialize_database(runtime_settings.startup_db_init_mode)
    except Exception as exc:
        _mark_startup_state(app, completed=False, error=str(exc))
        if runtime_settings.fail_startup_on_init_error:
            raise
    else:
        _mark_startup_state(app, completed=True, error=None)

    yield  # la app corre acá

    # SHUTDOWN
    # Cerramos el engine correctamente — libera conexiones del pool
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)
_mark_startup_state(app, completed=False, error=None)


# Mapa de tipo de excepción → status HTTP correcto.
#
# ¿Por qué no siempre 500?
# ─────────────────────────
# HTTP 500 significa "el servidor falló por un bug interno".
# Pero muchos de nuestros errores son fallas de SERVICIOS EXTERNOS —
# no hay bug en el código, el proveedor simplemente no está disponible.
#
# La semántica correcta:
#   503 Service Unavailable → el servicio externo (LLM, pgvector) no está disponible
#   500 Internal Server Error → fallo interno del servidor (todos los agentes fallaron,
#                               o hubo un error de ejecución inesperado)
#   422 Unprocessable Entity → los datos del request son válidos sintácticamente
#                              pero no semánticamente (triage no puede parsear el caso)
#
# La MRO (Method Resolution Order) de Python importa acá:
# ProviderQuotaError es subclase de LLMProviderError → debe ir ANTES en el map.
# isinstance() busca de forma lineal, así que el orden de las keys no importa en
# el dict, pero sí importa la forma en que iteramos el map en el handler.
#
# Usamos type(exc) para match exacto + fallback a issubclass para subclases.
_STATUS_MAP: dict[type[ClinicalBaseError], int] = {
    ProviderQuotaError:   503,
    LLMProviderError:     503,
    RAGRetrievalError:    503,
    AllAgentsFailedError: 500,
    AgentExecutionError:  500,
    TriageError:          422,
}


@app.exception_handler(ClinicalBaseError)
async def clinical_error_handler(
    request: Request, exc: ClinicalBaseError
) -> JSONResponse:
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
      if error.error == "ProviderQuotaError": mostrar_recarga_creditos()

    type(exc).__name__ devuelve el nombre de la clase de la excepción.
    Para AgentExecutionError → "AgentExecutionError"
    Para AllAgentsFailedError → "AllAgentsFailedError"
    Así el cliente puede discriminar sin hardcodear mensajes.

    ¿Cómo determinamos el status_code?
    ────────────────────────────────────
    Iteramos _STATUS_MAP usando isinstance() para respetar la herencia.
    ProviderQuotaError es subclase de LLMProviderError — sin isinstance(),
    si la key fuera LLMProviderError, matchearía primero y devolvería 503
    igualmente, pero perderíamos la especificidad del tipo.

    El fallback es 500 para cualquier ClinicalBaseError no mapeada.
    """
    # isinstance respeta herencia: ProviderQuotaError matchea LLMProviderError también.
    # Iteramos en orden de inserción del dict (Python 3.7+) — como ProviderQuotaError
    # está ANTES que LLMProviderError en _STATUS_MAP, siempre matchea primero.
    status_code = next(
        (code for exc_type, code in _STATUS_MAP.items() if isinstance(exc, exc_type)),
        500,  # fallback para ClinicalBaseError no mapeada
    )

    return JSONResponse(
        status_code=status_code,
        content={
            "error": type(exc).__name__,
            "detail": exc.message,
            "status_code": status_code,
        },
    )


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """
    Middleware que registra cada request HTTP con método, path, status y duración.

    ¿Qué es un middleware en FastAPI?
    ──────────────────────────────────
    Un middleware es una función que envuelve CADA request-response del servidor.
    Se ejecuta ANTES del endpoint (para setup) y DESPUÉS (para cleanup/logging).

    La firma siempre es: async (request, call_next) → Response
    donde call_next(request) invoca el siguiente middleware o el endpoint final.

    Esto es el PATRÓN CHAIN OF RESPONSIBILITY: cada middleware decide si
    procesar el request, pasarlo al siguiente, o ambos.

    ¿Por qué time.perf_counter() y no time.time()?
    ─────────────────────────────────────────────────
    time.time() es el "wall clock" — puede ir hacia atrás si el sistema
    ajusta el reloj (NTP sync, zona horaria, etc.).
    time.perf_counter() es MONOTÓNICO — garantizado que nunca retrocede.
    Para medir duraciones, siempre usás perf_counter.

    ¿Por qué logueamos DESPUÉS de call_next(request)?
    ───────────────────────────────────────────────────
    Porque recién después tenemos el status_code de la response.
    El request llega, se procesa completamente, y solo entonces
    conocemos si fue un 200, 404, 500, etc.
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)

    logger.info(
        "Request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )

    return response


app.include_router(health_router)
app.include_router(clinical_router)
