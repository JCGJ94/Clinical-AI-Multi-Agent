from pydantic import BaseModel, Field
from enum import Enum


class NivelUrgencia(str, Enum):
    CRITICO = "CRITICO"
    MUY_URGENTE = "MUY_URGENTE"
    URGENTE = "URGENTE"
    NO_URGENTE = "NO_URGENTE"


# ─── Inputs ──────────────────────────────────────────────────

class TriageInput(BaseModel):
    texto_clinico: str = Field(min_length=10, description="Descripción del caso clínico")
    sintomas: list[str] = Field(min_length=1, description="Lista de síntomas")
    contexto: str | None = Field(default=None, description="Contexto adicional del paciente")


class AnalyzeInput(BaseModel):
    caso_clinico: str = Field(min_length=10, description="Caso clínico completo")
    nivel_urgencia: NivelUrgencia | None = Field(default=None, description="Urgencia pre-calculada")
    agentes_sugeridos: list[str] | None = Field(default=None, description="Agentes del triage previo")


# ─── Outputs ─────────────────────────────────────────────────

class TriageOutput(BaseModel):
    nivel_urgencia: NivelUrgencia
    agentes_sugeridos: list[str]
    razonamiento: str


class AgentOutput(BaseModel):
    agent_name: str
    summary: str
    findings: list[str]
    red_flags: list[str]
    recommendations: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    context_sources: list[str] = Field(default_factory=list)


class AnalyzeOutput(BaseModel):
    case_id: int | None = Field(default=None, description="ID del caso persistido en DB")
    summary: str
    findings: list[str]
    red_flags: list[str]
    recommendations: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    agentes_activados: list[str]
    agent_outputs: list[AgentOutput]


class ClinicalCaseRead(BaseModel):
    """Respuesta del GET /clinical-case/{case_id} — sin agent_outputs (verbose)."""
    id: int
    caso_clinico: str
    agentes_sugeridos: list[str] | None
    summary: str
    findings: list[str]
    red_flags: list[str]
    recommendations: list[str]
    confidence: float
    agentes_activados: list[str]
    created_at: str  # ISO 8601
