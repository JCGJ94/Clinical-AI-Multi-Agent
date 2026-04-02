"""
Tests del ClinicalCaseRepository — Fase 8.

¿Por qué SQLite in-memory en lugar de PostgreSQL?
──────────────────────────────────────────────────
Los tests de repository necesitan una DB real para verificar que los
INSERT, SELECT y las constraints funcionan. Pero no queremos depender
de que Postgres esté corriendo para pasar los tests.

SQLite in-memory:
  - Se crea en RAM al iniciar el test → no persiste después del test
  - No requiere Docker ni servidor externo
  - SQLAlchemy abstrae el dialecto → los mismos modelos funcionan en SQLite y Postgres
  - aiosqlite: driver async para SQLite (como asyncpg pero para SQLite)

Connection URL:
  PostgreSQL: "postgresql+asyncpg://user:pass@host/db"
  SQLite in-memory: "sqlite+aiosqlite:///:memory:"

Fixture pattern para async SQLAlchemy:
  1. Crear engine in-memory
  2. create_all() para generar las tablas
  3. Crear sesión
  4. Usar sesión en el test
  5. drop_all() + dispose() en teardown

check_same_thread=False:
  SQLite normalmente solo permite acceso desde el thread que la creó.
  En tests async con pytest-asyncio el thread puede variar.
  connect_args={"check_same_thread": False} deshabilita esa restricción.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.repository import ClinicalCaseRepository
from app.models.clinical import AgentOutput, AnalyzeOutput


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def session():
    """
    Crea una sesión SQLite in-memory por test.
    create_all → test → drop_all garantiza aislamiento total entre tests.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncTestSession = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncTestSession() as sess:
        yield sess

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


def make_analyze_output(**overrides) -> AnalyzeOutput:
    base = {
        "summary": "Paciente con síntomas compatibles con IAM.",
        "findings": ["dolor torácico", "hipertensión"],
        "red_flags": ["posible IAM"],
        "recommendations": ["ECG urgente", "troponinas"],
        "confidence": 0.87,
        "agentes_activados": ["EmergencyAgent", "ClinicalAgent"],
        "agent_outputs": [],
    }
    return AnalyzeOutput(**{**base, **overrides})


# ─── save() ────────────────────────────────────────────────────────────────────

async def test_save_returns_case_with_id(session: AsyncSession):
    """save() devuelve la entidad persistida con un id asignado por la DB."""
    repo = ClinicalCaseRepository(session)
    result = make_analyze_output()

    saved = await repo.save("Paciente 62 años con dolor torácico.", None, result)

    assert saved.id is not None
    assert saved.id > 0


async def test_save_persists_caso_clinico(session: AsyncSession):
    """El caso clínico se guarda correctamente."""
    repo = ClinicalCaseRepository(session)
    caso = "Paciente de 45 años con fiebre y tos productiva."

    saved = await repo.save(caso, None, make_analyze_output())

    assert saved.caso_clinico == caso


async def test_save_persists_result_fields(session: AsyncSession):
    """Todos los campos del AnalyzeOutput se persisten correctamente."""
    repo = ClinicalCaseRepository(session)
    result = make_analyze_output(
        summary="Síndrome coronario agudo.",
        findings=["elevación ST", "troponinas positivas"],
        red_flags=["IAM confirmado"],
        recommendations=["cateterismo urgente"],
        confidence=0.95,
        agentes_activados=["EmergencyAgent", "CardiologyAgent"],
    )

    saved = await repo.save("Caso cardio.", None, result)

    assert saved.summary == "Síndrome coronario agudo."
    assert saved.findings == ["elevación ST", "troponinas positivas"]
    assert saved.red_flags == ["IAM confirmado"]
    assert saved.recommendations == ["cateterismo urgente"]
    assert saved.confidence == pytest.approx(0.95)
    assert saved.agentes_activados == ["EmergencyAgent", "CardiologyAgent"]


async def test_save_persists_agentes_sugeridos(session: AsyncSession):
    """agentes_sugeridos se guarda como JSON correctamente."""
    repo = ClinicalCaseRepository(session)
    sugeridos = ["EmergencyAgent", "CardiologyAgent"]

    saved = await repo.save("Caso con ECG.", sugeridos, make_analyze_output())

    assert saved.agentes_sugeridos == sugeridos


async def test_save_allows_null_agentes_sugeridos(session: AsyncSession):
    """agentes_sugeridos puede ser None (cuando no hubo triage previo)."""
    repo = ClinicalCaseRepository(session)

    saved = await repo.save("Caso sin triage.", None, make_analyze_output())

    assert saved.agentes_sugeridos is None


async def test_save_sets_created_at(session: AsyncSession):
    """created_at se asigna automáticamente."""
    repo = ClinicalCaseRepository(session)

    saved = await repo.save("Caso.", None, make_analyze_output())

    assert saved.created_at is not None


# ─── get_by_id() ───────────────────────────────────────────────────────────────

async def test_get_by_id_returns_saved_case(session: AsyncSession):
    """get_by_id() devuelve el caso guardado previamente."""
    repo = ClinicalCaseRepository(session)
    saved = await repo.save("Caso persistido.", None, make_analyze_output())

    retrieved = await repo.get_by_id(saved.id)

    assert retrieved is not None
    assert retrieved.id == saved.id
    assert retrieved.caso_clinico == "Caso persistido."


async def test_get_by_id_returns_none_for_missing(session: AsyncSession):
    """get_by_id() devuelve None si el id no existe."""
    repo = ClinicalCaseRepository(session)

    result = await repo.get_by_id(99999)

    assert result is None


# ─── list_recent() ─────────────────────────────────────────────────────────────

async def test_list_recent_returns_all_when_below_limit(session: AsyncSession):
    """list_recent() devuelve todos los casos cuando hay menos que el limit."""
    repo = ClinicalCaseRepository(session)

    for i in range(3):
        await repo.save(f"Caso {i}.", None, make_analyze_output())

    cases = await repo.list_recent(limit=10)

    assert len(cases) == 3


async def test_list_recent_respects_limit(session: AsyncSession):
    """list_recent() no devuelve más casos que el limit."""
    repo = ClinicalCaseRepository(session)

    for i in range(5):
        await repo.save(f"Caso {i}.", None, make_analyze_output())

    cases = await repo.list_recent(limit=3)

    assert len(cases) == 3


async def test_list_recent_returns_newest_first(session: AsyncSession):
    """list_recent() ordena por created_at desc — el más reciente primero."""
    repo = ClinicalCaseRepository(session)

    first = await repo.save("Primer caso.", None, make_analyze_output())
    second = await repo.save("Segundo caso.", None, make_analyze_output())

    cases = await repo.list_recent(limit=10)

    # El más reciente tiene id mayor (autoincrement)
    assert cases[0].id >= cases[1].id
