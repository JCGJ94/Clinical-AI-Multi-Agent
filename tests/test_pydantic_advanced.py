"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TEST: Advanced Pydantic Patterns — Fase 12                                 ║
║                                                                              ║
║  Valida los patrones avanzados de Pydantic v2 introducidos en Fase 12:      ║
║                                                                              ║
║    1. @model_validator(mode="after") en TriageInput y AnalyzeInput          ║
║    2. @field_validator en AgentOutput (redondeo de confianza)                ║
║    3. @computed_field en AnalyzeOutput                                       ║
║    4. Discriminated unions en AgentConfig                                    ║
║    5. strict mode en TriageOutput                                            ║
║    6. json_schema_extra en TriageInput                                       ║
║                                                                              ║
║  Filosofía de testing de este módulo:                                        ║
║  ─────────────────────────────────────                                       ║
║  Los tests de modelos Pydantic son tests UNITARIOS puros.                   ║
║  No necesitamos mocks, no necesitamos HTTP, no necesitamos DB.              ║
║  Solo instanciamos los modelos y verificamos su comportamiento.             ║
║                                                                              ║
║  Esto los hace extremadamente rápidos y confiables.                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.models.clinical import (
    NivelUrgencia,
    TriageInput,
    TriageOutput,
    AnalyzeInput,
    AgentOutput,
    AnalyzeOutput,
)
from app.models.agent_config import (
    AgentConfig,
    ClinicalAgentConfig,
    EmergencyAgentConfig,
    RouterConfig,
)


# ─── Fixtures helpers ─────────────────────────────────────────────────────────

def make_agent_output(**kwargs) -> AgentOutput:
    """Factory helper para crear AgentOutput con defaults razonables."""
    defaults = {
        "agent_name": "TestAgent",
        "summary": "Resumen de prueba",
        "findings": ["hallazgo 1"],
        "red_flags": [],
        "recommendations": ["recomendación 1"],
        "confidence": 0.85,
        "context_sources": [],
    }
    defaults.update(kwargs)
    return AgentOutput(**defaults)


def make_analyze_output(**kwargs) -> AnalyzeOutput:
    """Factory helper para crear AnalyzeOutput con defaults razonables."""
    defaults = {
        "summary": "Resumen de análisis",
        "findings": ["hallazgo 1"],
        "red_flags": [],
        "recommendations": ["recomendación 1"],
        "confidence": 0.85,
        "agentes_activados": ["ClinicalAgent"],
        "agent_outputs": [make_agent_output()],
        "failed_agents": [],
        "warnings": [],
    }
    defaults.update(kwargs)
    return AnalyzeOutput(**defaults)


# ─── Tests: TriageInput @model_validator ──────────────────────────────────────

def test_triage_input_auto_contexto_on_chest_pain():
    """
    El validator debe auto-asignar contexto cuando hay dolor torácico
    y el contexto no fue especificado.
    """
    triage = TriageInput(
        texto_clinico="Paciente de 65 años con dolor en el pecho intenso",
        sintomas=["dolor torácico", "disnea"],
        contexto=None,
    )
    assert triage.contexto == "Evaluación cardiológica recomendada"


def test_triage_input_no_auto_contexto_for_other_symptoms():
    """
    El validator NO debe asignar contexto cuando los síntomas no
    incluyen dolor torácico.
    """
    triage = TriageInput(
        texto_clinico="Paciente con náuseas y mareos leves persistentes",
        sintomas=["náuseas", "mareos"],
        contexto=None,
    )
    assert triage.contexto is None


def test_triage_input_preserves_explicit_contexto():
    """
    Si el usuario ya proveyó un contexto, el validator NO debe
    sobreescribirlo — aunque haya dolor torácico.
    """
    contexto_original = "Paciente con antecedente de reflujo gastroesofágico"
    triage = TriageInput(
        texto_clinico="Paciente refiere dolor torácico post-comida",
        sintomas=["dolor torácico", "pirosis"],
        contexto=contexto_original,
    )
    assert triage.contexto == contexto_original


def test_triage_input_auto_contexto_case_insensitive():
    """
    El matching de keywords debe ser case-insensitive.
    'DOLOR TORÁCICO' debe activar el validator igual que 'dolor torácico'.
    """
    triage = TriageInput(
        texto_clinico="Paciente masculino de 70 años con DOLOR TORÁCICO súbito",
        sintomas=["DOLOR TORÁCICO", "diaforesis"],
        contexto=None,
    )
    assert triage.contexto == "Evaluación cardiológica recomendada"


# ─── Tests: AnalyzeInput @model_validator ─────────────────────────────────────

def test_analyze_input_auto_agents_for_critical():
    """
    Para nivel CRITICO sin agentes especificados, el validator debe
    asignar ['EmergencyAgent', 'ClinicalAgent'] por defecto.
    """
    analyze = AnalyzeInput(
        caso_clinico="Paciente de 45 años con paro cardiorrespiratorio presenciado",
        nivel_urgencia=NivelUrgencia.CRITICO,
        agentes_sugeridos=None,
    )
    assert analyze.agentes_sugeridos == ["EmergencyAgent", "ClinicalAgent"]


def test_analyze_input_auto_agents_for_muy_urgente():
    """
    Para nivel MUY_URGENTE sin agentes especificados, también debe
    asignar los agentes por defecto. La regla aplica para ambos niveles críticos.
    """
    analyze = AnalyzeInput(
        caso_clinico="Paciente con insuficiencia respiratoria aguda severa",
        nivel_urgencia=NivelUrgencia.MUY_URGENTE,
        agentes_sugeridos=None,
    )
    assert analyze.agentes_sugeridos == ["EmergencyAgent", "ClinicalAgent"]


def test_analyze_input_no_auto_agents_for_urgente():
    """
    Para URGENTE (tercer nivel), el validator NO debe activarse.
    Solo aplica para CRITICO y MUY_URGENTE.
    """
    analyze = AnalyzeInput(
        caso_clinico="Paciente con fiebre alta y dolor abdominal moderado",
        nivel_urgencia=NivelUrgencia.URGENTE,
        agentes_sugeridos=None,
    )
    assert analyze.agentes_sugeridos is None


def test_analyze_input_no_auto_agents_for_no_urgente():
    """
    Para NO_URGENTE el validator tampoco debe activarse.
    """
    analyze = AnalyzeInput(
        caso_clinico="Paciente con resfriado común y congestión nasal leve",
        nivel_urgencia=NivelUrgencia.NO_URGENTE,
        agentes_sugeridos=None,
    )
    assert analyze.agentes_sugeridos is None


def test_analyze_input_no_auto_agents_when_urgency_is_none():
    """
    Sin nivel de urgencia especificado, el validator no debe activarse.
    """
    analyze = AnalyzeInput(
        caso_clinico="Paciente con síntomas inespecíficos pendiente de triage",
        nivel_urgencia=None,
        agentes_sugeridos=None,
    )
    assert analyze.agentes_sugeridos is None


def test_analyze_input_preserves_explicit_agentes():
    """
    Si el usuario ya especificó agentes (aunque sea para CRITICO),
    el validator NO debe sobreescribirlos.
    """
    agentes_originales = ["CardiologyAgent", "RadiologyAgent"]
    analyze = AnalyzeInput(
        caso_clinico="Paciente con síndrome coronario agudo confirmado por ECG",
        nivel_urgencia=NivelUrgencia.CRITICO,
        agentes_sugeridos=agentes_originales,
    )
    assert analyze.agentes_sugeridos == agentes_originales


# ─── Tests: AgentOutput @field_validator ──────────────────────────────────────

def test_agent_output_rounds_confidence():
    """
    El validator debe redondear confidence a 4 decimales.
    0.85678901 → 0.8568 (4to decimal: 6 → round up da 8568).
    """
    output = make_agent_output(confidence=0.85678901)
    assert output.confidence == round(0.85678901, 4)
    assert output.confidence == 0.8568


def test_agent_output_rounds_confidence_already_short():
    """
    Valores que ya tienen 4 o menos decimales no deben cambiar.
    """
    output = make_agent_output(confidence=0.85)
    assert output.confidence == 0.85


def test_agent_output_rounds_confidence_to_zero():
    """
    Un float muy pequeño que redondea a 0.0 es válido.
    """
    output = make_agent_output(confidence=0.00001)
    assert output.confidence == round(0.00001, 4)


def test_agent_output_rounds_confidence_max():
    """
    confidence=1.0 debe mantenerse exactamente en 1.0.
    """
    output = make_agent_output(confidence=1.0)
    assert output.confidence == 1.0


# ─── Tests: AnalyzeOutput @computed_field ─────────────────────────────────────

def test_analyze_output_computed_total_agents():
    """
    total_agents debe reflejar el número de agentes en agentes_activados.
    """
    output = make_analyze_output(
        agentes_activados=["ClinicalAgent", "CardiologyAgent", "EmergencyAgent"],
    )
    assert output.total_agents == 3


def test_analyze_output_computed_total_agents_empty():
    """
    Si no hay agentes activados, total_agents debe ser 0.
    """
    output = make_analyze_output(agentes_activados=[], agent_outputs=[])
    assert output.total_agents == 0


def test_analyze_output_computed_has_red_flags_true():
    """
    has_red_flags debe ser True cuando hay al menos una red flag.
    """
    output = make_analyze_output(red_flags=["posible IAM", "inestabilidad hemodinámica"])
    assert output.has_red_flags is True


def test_analyze_output_computed_has_red_flags_false():
    """
    has_red_flags debe ser False cuando la lista de red_flags está vacía.
    """
    output = make_analyze_output(red_flags=[])
    assert output.has_red_flags is False


def test_analyze_output_computed_success_rate_all_succeed():
    """
    Con 3 agentes activos y 0 fallidos, success_rate debe ser 1.0.
    """
    output = make_analyze_output(
        agentes_activados=["AgentA", "AgentB", "AgentC"],
        failed_agents=[],
    )
    assert output.success_rate == 1.0


def test_analyze_output_computed_success_rate_partial():
    """
    Con 1 agente exitoso y 1 fallido (50%), success_rate debe ser 0.5.
    """
    output = make_analyze_output(
        agentes_activados=["AgentA"],
        failed_agents=["AgentB"],
    )
    assert output.success_rate == 0.5


def test_analyze_output_computed_success_rate_all_failed():
    """
    Con 0 agentes exitosos y 2 fallidos, success_rate debe ser 0.0.
    """
    output = make_analyze_output(
        agentes_activados=[],
        agent_outputs=[],
        failed_agents=["AgentA", "AgentB"],
    )
    assert output.success_rate == 0.0


def test_analyze_output_computed_success_rate_zero_total():
    """
    Sin agentes en absoluto (ni exitosos ni fallidos), success_rate debe
    ser 0.0 — sin división por cero.
    """
    output = make_analyze_output(
        agentes_activados=[],
        agent_outputs=[],
        failed_agents=[],
    )
    assert output.success_rate == 0.0


def test_analyze_output_computed_fields_in_json():
    """
    Los @computed_field deben aparecer en model_dump() y model_dump_json().
    Esto los diferencia de @property normales que no se serializan.
    """
    output = make_analyze_output(
        agentes_activados=["ClinicalAgent", "CardiologyAgent"],
        failed_agents=["RadiologyAgent"],
        red_flags=["posible IAM"],
    )
    dumped = output.model_dump()

    # Verificar que los campos computados están presentes en el dict
    assert "total_agents" in dumped
    assert "has_red_flags" in dumped
    assert "success_rate" in dumped

    # Verificar los valores correctos
    assert dumped["total_agents"] == 2
    assert dumped["has_red_flags"] is True
    assert dumped["success_rate"] == round(2 / 3, 2)


# ─── Tests: Discriminated Union ───────────────────────────────────────────────

def test_discriminated_union_clinical_config():
    """
    Parsear un dict con agent_type='clinical' debe devolver ClinicalAgentConfig.
    """
    adapter = TypeAdapter(AgentConfig)
    config = adapter.validate_python({
        "agent_type": "clinical",
        "temperature": 0.2,
        "rag_k": 5,
    })
    assert isinstance(config, ClinicalAgentConfig)
    assert config.agent_type == "clinical"
    assert config.temperature == 0.2
    assert config.rag_k == 5


def test_discriminated_union_emergency_config():
    """
    Parsear un dict con agent_type='emergency' debe devolver EmergencyAgentConfig.
    """
    adapter = TypeAdapter(AgentConfig)
    config = adapter.validate_python({
        "agent_type": "emergency",
        "temperature": 0.1,
        "priority_boost": True,
    })
    assert isinstance(config, EmergencyAgentConfig)
    assert config.agent_type == "emergency"
    assert config.priority_boost is True


def test_discriminated_union_router_config():
    """
    Parsear un dict con agent_type='router' debe devolver RouterConfig.
    """
    adapter = TypeAdapter(AgentConfig)
    config = adapter.validate_python({
        "agent_type": "router",
        "temperature": 0.0,
        "max_retries": 2,
    })
    assert isinstance(config, RouterConfig)
    assert config.agent_type == "router"
    assert config.max_retries == 2


def test_discriminated_union_wrong_type_fails():
    """
    Un agent_type desconocido debe levantar ValidationError inmediatamente,
    sin trial-and-error — eso es el poder del discriminador.
    """
    adapter = TypeAdapter(AgentConfig)
    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python({
            "agent_type": "inexistente",
            "temperature": 0.5,
        })
    # Verificar que el error menciona el campo discriminador
    assert "agent_type" in str(exc_info.value) or "inexistente" in str(exc_info.value)


def test_discriminated_union_missing_discriminator_fails():
    """
    Si falta el campo discriminador agent_type, debe fallar la validación.
    """
    adapter = TypeAdapter(AgentConfig)
    with pytest.raises(ValidationError):
        adapter.validate_python({
            "temperature": 0.5,
        })


def test_discriminated_union_defaults_are_applied():
    """
    Los valores por defecto de BaseAgentConfig deben aplicarse correctamente.
    """
    adapter = TypeAdapter(AgentConfig)
    config = adapter.validate_python({
        "agent_type": "clinical",
        "temperature": 0.3,
        # max_retries y timeout_seconds usan defaults
    })
    assert isinstance(config, ClinicalAgentConfig)
    assert config.max_retries == 3  # default de BaseAgentConfig
    assert config.timeout_seconds == 30.0  # default de BaseAgentConfig
    assert config.rag_k == 3  # default de ClinicalAgentConfig


# ─── Tests: Strict Mode ──────────────────────────────────────────────────────

class _StrictOutputExample(BaseModel):
    """
    Modelo auxiliar para demostrar ConfigDict(strict=True).

    NO se usa en producción — existe solo para enseñar el patrón.

    ¿Por qué TriageOutput no usa strict=True en producción?
    ────────────────────────────────────────────────────────
    LangChain's PydanticOutputParser llama model_validate() con un dict
    proveniente de json.loads() — todos los valores son strings, no enums.

    Con strict=True, "MUY_URGENTE" (str) no sería aceptado como NivelUrgencia,
    rompiendo la chain. La coerción lax (modo default) es lo que necesitamos
    para integrar con LLMs.

    En un sistema donde controlás 100% el origen de los datos (ej: tests,
    servicios internos) podrías usar strict=True en outputs para garantizar
    que nada pasa strings donde esperás enums.
    """
    model_config = ConfigDict(strict=True)

    nivel_urgencia: NivelUrgencia
    agentes_sugeridos: list[str]
    razonamiento: str


def test_strict_mode_accepts_valid_enum():
    """
    Con strict=True, un NivelUrgencia enum explícito debe aceptarse.
    """
    output = _StrictOutputExample(
        nivel_urgencia=NivelUrgencia.CRITICO,
        agentes_sugeridos=["EmergencyAgent"],
        razonamiento="Caso crítico detectado",
    )
    assert output.nivel_urgencia == NivelUrgencia.CRITICO


def test_strict_mode_rejects_string_as_enum():
    """
    Con strict=True, pasar "CRITICO" (string) cuando se espera NivelUrgencia
    (enum) debe levantar ValidationError.

    En modo lax (default), Pydantic convertiría "CRITICO" → NivelUrgencia.CRITICO.
    En modo estricto, rechaza cualquier coerción — el tipo debe ser exacto.

    Nota: usamos _StrictOutputExample (modelo de prueba) en lugar de
    TriageOutput porque TriageOutput usa modo lax para ser compatible con
    LangChain's PydanticOutputParser que devuelve strings desde JSON.
    """
    with pytest.raises(ValidationError):
        _StrictOutputExample(
            nivel_urgencia="CRITICO",  # string, no NivelUrgencia enum
            agentes_sugeridos=["EmergencyAgent"],
            razonamiento="Caso crítico",
        )


# ─── Tests: JSON Schema Extra ─────────────────────────────────────────────────

def test_json_schema_extra_examples_in_triage_input():
    """
    El json_schema_extra con 'examples' debe estar presente en el schema
    generado por Pydantic — esto es lo que aparece en /docs de FastAPI.
    """
    schema = TriageInput.model_json_schema()
    # El schema debe contener la clave 'examples'
    assert "examples" in schema
    # Debe tener al menos un ejemplo
    assert len(schema["examples"]) > 0
    # El primer ejemplo debe tener los campos obligatorios
    first_example = schema["examples"][0]
    assert "texto_clinico" in first_example
    assert "sintomas" in first_example


def test_json_schema_extra_examples_in_analyze_input():
    """
    AnalyzeInput también debe tener ejemplos en su JSON Schema.
    """
    schema = AnalyzeInput.model_json_schema()
    assert "examples" in schema
    assert len(schema["examples"]) > 0
    first_example = schema["examples"][0]
    assert "caso_clinico" in first_example


def test_json_schema_extra_examples_in_agent_output():
    """
    AgentOutput también debe tener ejemplos en su JSON Schema.
    """
    schema = AgentOutput.model_json_schema()
    assert "examples" in schema
    assert len(schema["examples"]) > 0
    first_example = schema["examples"][0]
    assert "agent_name" in first_example
    assert "confidence" in first_example
