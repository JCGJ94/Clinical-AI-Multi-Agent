"""
Repository pattern — capa de acceso a datos.

¿Por qué Repository en lugar de SQLAlchemy directo en las routes?
──────────────────────────────────────────────────────────────────

SIN Repository (anti-patrón):
    @router.post("/analyze")
    async def analyze(session: AsyncSession = Depends(get_session)):
        result = await integrator.analyze(...)
        case = ClinicalCase(caso_clinico=..., summary=result.summary, ...)
        session.add(case)
        await session.commit()
        return result

  Problemas:
  - La route conoce detalles de la DB (modelo ORM, cómo hacer queries)
  - Para testear la route necesitás una DB real o mockear SQLAlchemy completo
  - Si cambiás el modelo ORM, tenés que cambiar todas las routes

CON Repository (patrón correcto):
    @router.post("/analyze")
    async def analyze(session: AsyncSession = Depends(get_session)):
        result = await integrator.analyze(...)
        repo = ClinicalCaseRepository(session)
        saved = await repo.save(input.caso_clinico, input.agentes_sugeridos, result)
        return result  # o devolver saved.id

  Ventajas:
  - La route no sabe nada de SQL ni de ORM
  - El repository es la ÚNICA pieza que sabe cómo persistir un caso
  - Para testear el repository: SQLite in-memory (rápido, sin Postgres)
  - Para testear las routes: mockear repo.save() con AsyncMock

Métodos del repositorio:
  save()      → persiste un caso nuevo, retorna la entidad con id generado
  get_by_id() → busca un caso por id, retorna None si no existe
  list_recent() → últimos N casos ordenados por created_at desc
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClinicalCase
from app.models.clinical import AnalyzeOutput


class ClinicalCaseRepository:
    """
    Repository para la entidad ClinicalCase.

    Recibe la sesión por constructor (inyección de dependencias):
      repo = ClinicalCaseRepository(session)

    ¿Por qué no usar la sesión como global o singleton?
      Porque la sesión es por request (ver get_session en session.py).
      Si la guardáramos en un singleton, requests concurrentes compartirían estado.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        caso_clinico: str,
        agentes_sugeridos: list[str] | None,
        result: AnalyzeOutput,
    ) -> ClinicalCase:
        """
        Persiste un caso clínico con su resultado de análisis.

        ORM pattern:
          1. Crear instancia del modelo ORM
          2. session.add(obj) → registra en la sesión (aún NO en la DB)
          3. await session.commit() → ejecuta el INSERT y obtiene el id generado
          4. await session.refresh(obj) → recarga obj desde la DB (para obtener el id y created_at)
        """
        case = ClinicalCase(
            caso_clinico=caso_clinico,
            agentes_sugeridos=agentes_sugeridos,
            summary=result.summary,
            findings=result.findings,
            red_flags=result.red_flags,
            recommendations=result.recommendations,
            confidence=result.confidence,
            agentes_activados=result.agentes_activados,
        )
        self.session.add(case)
        await self.session.commit()
        await self.session.refresh(case)
        return case

    async def get_by_id(self, case_id: int) -> ClinicalCase | None:
        """
        Busca un caso por id primario.
        Retorna None si no existe — el caller decide qué hacer (404, etc.).

        select(ClinicalCase) genera: SELECT * FROM clinical_cases WHERE id = :id
        scalars().first() extrae el primer resultado como objeto Python (no Row).
        """
        result = await self.session.execute(
            select(ClinicalCase).where(ClinicalCase.id == case_id)
        )
        return result.scalars().first()

    async def list_recent(self, limit: int = 10) -> list[ClinicalCase]:
        """
        Devuelve los últimos N casos, ordenados por created_at desc.
        Útil para dashboards o auditoría.
        """
        result = await self.session.execute(
            select(ClinicalCase)
            .order_by(ClinicalCase.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
