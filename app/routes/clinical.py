from fastapi import APIRouter
from app.models.clinical import (
    TriageInput,
    TriageOutput,
    AnalyzeInput,
    AnalyzeOutput,
    NivelUrgencia,
)
from app.agents.clinical import ClinicalAgent

router = APIRouter(prefix="/clinical-case", tags=["Clinical"])


@router.post("/triage", response_model=TriageOutput)
async def triage(input: TriageInput) -> TriageOutput:
    # FASE 4: el AgentRouter con LLM llega en Fase 4 — por ahora mock
    return TriageOutput(
        nivel_urgencia=NivelUrgencia.URGENTE,
        agentes_sugeridos=["ClinicalAgent", "DifferentialDiagnosisAgent"],
        razonamiento="[mock] Triage pendiente de integración con AgentRouter.",
    )


@router.post("/analyze", response_model=AnalyzeOutput)
async def analyze(input: AnalyzeInput) -> AnalyzeOutput:
    agent = ClinicalAgent()
    result = await agent.run(input.caso_clinico)

    return AnalyzeOutput(
        summary=result.summary,
        findings=result.findings,
        red_flags=result.red_flags,
        recommendations=result.recommendations,
        confidence=result.confidence,
        agentes_activados=[result.agent_name],
        agent_outputs=[result],
    )
