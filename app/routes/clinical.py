from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clinical import (
    TriageInput,
    TriageOutput,
    AnalyzeInput,
    AnalyzeOutput,
    ClinicalCaseRead,
)
from app.agents.router import AgentRouter
from app.services.integrator import Integrator
from app.db.session import get_session
from app.db.repository import ClinicalCaseRepository

router = APIRouter(prefix="/clinical-case", tags=["Clinical"])


@router.post("/triage", response_model=TriageOutput)
async def triage(input: TriageInput) -> TriageOutput:
    agent_router = AgentRouter()
    return await agent_router.run(input.texto_clinico, input.sintomas)


@router.post("/analyze", response_model=AnalyzeOutput)
async def analyze(
    input: AnalyzeInput,
    session: AsyncSession = Depends(get_session),
) -> AnalyzeOutput:
    integrator = Integrator()
    result = await integrator.analyze(
        input.caso_clinico,
        agentes_sugeridos=input.agentes_sugeridos,
        nivel_urgencia=input.nivel_urgencia,
    )

    # Persistir el caso y su resultado
    repo = ClinicalCaseRepository(session)
    saved = await repo.save(input.caso_clinico, input.agentes_sugeridos, result)

    # Devolvemos el resultado con el case_id asignado por la DB
    result.case_id = saved.id
    return result


@router.get("/{case_id}", response_model=ClinicalCaseRead)
async def get_case(
    case_id: int,
    session: AsyncSession = Depends(get_session),
) -> ClinicalCaseRead:
    repo = ClinicalCaseRepository(session)
    case = await repo.get_by_id(case_id)

    if not case:
        raise HTTPException(status_code=404, detail=f"Caso {case_id} no encontrado")

    return ClinicalCaseRead(
        id=case.id,
        caso_clinico=case.caso_clinico,
        agentes_sugeridos=case.agentes_sugeridos,
        summary=case.summary,
        findings=case.findings,
        red_flags=case.red_flags,
        recommendations=case.recommendations,
        confidence=case.confidence,
        agentes_activados=case.agentes_activados,
        created_at=case.created_at.isoformat(),
    )
