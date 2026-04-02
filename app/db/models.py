"""
Modelos ORM — SQLAlchemy 2.0 (con Mapped[] type hints).

¿Qué cambió entre SQLAlchemy 1.x y 2.0?
─────────────────────────────────────────
SQLAlchemy 1.x:
    class User(Base):
        id = Column(Integer, primary_key=True)
        name = Column(String)

SQLAlchemy 2.0 (este proyecto):
    class User(Base):
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column(String)

El nuevo estilo usa type hints reales → mypy/pyright pueden verificarlos.
`Mapped[X]` le dice a SQLAlchemy y al type checker que este atributo es de tipo X.
`mapped_column()` configura cómo se mapea a SQL (tipo, constraints, defaults).

¿Qué es DeclarativeBase?
  La clase base que SQLAlchemy usa para registrar todos los modelos.
  `metadata` vive en Base.metadata — Alembic lo lee para generar migraciones.

¿Por qué JSON para listas?
  PostgreSQL puede guardar JSON nativo y hacer queries sobre él.
  Para listas (findings, red_flags, etc.) es más simple que tablas separadas.
  En tests usamos SQLite que también soporta JSON desde la versión 3.38.
"""

from datetime import datetime, timezone
from sqlalchemy import String, Float, JSON, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Clase base para todos los modelos ORM del proyecto.
    Base.metadata contiene el schema completo — lo usa Alembic para migraciones.
    """
    pass


class ClinicalCase(Base):
    """
    Tabla: clinical_cases

    Persiste el caso clínico de entrada + el resultado del análisis multi-agente.
    Un registro = una llamada a /clinical-case/analyze.

    Decisión de diseño: una sola tabla (no caso + resultado separados).
    ¿Por qué? El resultado es inmutable — una vez generado no cambia.
    No hay relación 1-N entre caso y resultado en Fase 8.
    Si en el futuro hubiera reanalysis, ahí sí vale separar.
    """

    __tablename__ = "clinical_cases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Input
    caso_clinico: Mapped[str] = mapped_column(String)
    agentes_sugeridos: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Output del Integrator
    summary: Mapped[str] = mapped_column(String)
    findings: Mapped[list] = mapped_column(JSON)
    red_flags: Mapped[list] = mapped_column(JSON)
    recommendations: Mapped[list] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    agentes_activados: Mapped[list] = mapped_column(JSON)

    # Metadatos
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
