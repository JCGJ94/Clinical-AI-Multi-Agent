"""
Alembic env.py — configuración del entorno de migraciones.

¿Por qué Alembic usa psycopg (sync) si la app usa asyncpg (async)?
─────────────────────────────────────────────────────────────────────
Las migraciones se ejecutan como scripts de línea de comandos, no como
un servidor web. No hay un event loop activo. Usar async aquí complicaría
el setup sin beneficio real. psycopg (sync) ya está instalado en el proyecto.

Alembic modo "autogenerate":
  Compara Base.metadata (lo que definen los modelos ORM) con el schema actual de la DB.
  Genera automáticamente los ALTER TABLE, CREATE TABLE, etc.

  Comando:
    alembic revision --autogenerate -m "create clinical_cases table"

  Esto crea un archivo en alembic/versions/ con las funciones upgrade() y downgrade().

  Luego:
    alembic upgrade head  → aplica todas las migraciones pendientes
    alembic downgrade -1  → revierte la última migración

target_metadata:
  Le decimos a Alembic cuál es nuestro schema. Sin esto no puede comparar.
"""

import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Importamos Base para que Alembic conozca nuestros modelos
from app.db.models import Base

config = context.config


def _get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    return database_url.replace("+asyncpg", "+psycopg")


config.set_main_option("sqlalchemy.url", _get_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Acá está la magia: le decimos a Alembic qué tablas existen en nuestra app
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Modo offline: genera el SQL sin conectarse a la DB.
    Útil para generar scripts de migración para revisar antes de aplicar.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Modo online: se conecta a la DB y aplica las migraciones directamente.
    Es el modo normal cuando ejecutás `alembic upgrade head`.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool: no reutiliza conexiones — ideal para migraciones
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
