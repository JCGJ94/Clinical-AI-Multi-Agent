"""
Session management — SQLAlchemy async.

Conceptos clave:
────────────────

create_async_engine(url)
  Crea el motor de conexión. El motor NO abre una conexión inmediatamente.
  Mantiene un connection pool — reutiliza conexiones en lugar de abrir/cerrar cada vez.

async_sessionmaker(engine)
  Fábrica de sesiones. Cada sesión es una unidad de trabajo (Unit of Work).
  Una sesión trackea todos los objetos que modificaste → al hacer commit() los persiste.

expire_on_commit=False
  Por defecto, SQLAlchemy "expira" los atributos después de commit() para forzar
  un reload desde la DB en el próximo acceso. Eso requiere que la sesión siga abierta.
  Con async y FastAPI, la sesión puede cerrarse antes de que la respuesta use los datos.
  expire_on_commit=False mantiene los valores en memoria → sin consultas adicionales.

get_session() como dependency de FastAPI:
  yield abre la sesión antes de la request y la cierra (con rollback si hubo error)
  después de que la respuesta se envió. Es el patrón estándar en FastAPI + SQLAlchemy.

  @router.post("/analyze")
  async def analyze(session: AsyncSession = Depends(get_session)):
      ...  # session disponible, se cierra automáticamente al final
"""

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import get_settings


def _get_async_engine():
    """
    Crea el AsyncEngine a partir de la database_url de settings.
    database_url usa "+asyncpg" → SQLAlchemy usa el driver asyncpg para PostgreSQL.
    En tests se reemplaza por "sqlite+aiosqlite:///:memory:" (ver conftest.py).
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,  # True en debug → imprime SQL en consola
    )


# Motor compartido por toda la app (singleton efectivo vía módulo Python)
engine = _get_async_engine()

# Fábrica de sesiones
AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — provee una sesión async por request.

    Uso:
        from app.db.session import get_session
        from sqlalchemy.ext.asyncio import AsyncSession

        @router.post("/algo")
        async def mi_route(session: AsyncSession = Depends(get_session)):
            ...

    El bloque `async with` garantiza que la sesión se cierra siempre,
    incluso si hay una excepción. SQLAlchemy hace rollback automático en ese caso.
    """
    async with AsyncSessionLocal() as session:
        yield session
