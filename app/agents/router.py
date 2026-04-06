"""
AgentRouter — Decisor de enrutado basado en LLM.

¿Por qué NO hereda de BaseAgent?
─────────────────────────────────
BaseAgent tiene el contrato: async run(...) → AgentOutput
El router devuelve TriageOutput (urgencia + agentes sugeridos), no un AgentOutput clínico.
Son responsabilidades distintas:
  - BaseAgent → analiza un caso clínico, produce hallazgos
  - AgentRouter → decide QUIÉN analiza el caso

¿Por qué NO usa RAG?
────────────────────
El router toma decisiones de enrutado usando las reglas codificadas en el system prompt.
El RAG es útil cuando necesitás fundamentar una respuesta en documentos de conocimiento.
Para decidir "¿qué agente activo?", el LLM puede razonar directo con las instrucciones.
RAG aquí sería overhead sin beneficio.

¿Cómo recibe input?
────────────────────
El prompt tiene dos variables: {texto_clinico} y {sintomas}.
chain.ainvoke recibe un DICT — a diferencia de los agentes clínicos que usan RAG
y necesitan un string puro para la búsqueda semántica.
Sin retriever, el input puede ser dict perfectamente.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from app.models.clinical import TriageOutput, NivelUrgencia
from app.core.llm import create_llm


SYSTEM_PROMPT = """\
Sos un sistema de triage clínico inteligente. Tu única función es:
1. Clasificar la urgencia del caso
2. Seleccionar los agentes clínicos apropiados

NIVELES DE URGENCIA:
- CRITICO: amenaza vital inminente (paro cardíaco, shock, hemorragia masiva, compromiso de vía aérea)
- MUY_URGENTE: posible amenaza vital (dolor torácico agudo, disnea severa, alteración neurológica aguda)
- URGENTE: síntomas importantes que requieren evaluación pronto (dolor moderado-severo, síntomas sistémicos, casos complejos)
- NO_URGENTE: síntomas leves, controles, consultas no urgentes

AGENTES DISPONIBLES (Fase 7):
- ClinicalAgent: internista generalista, evalúa síntomas médicos generales
- EmergencyAgent: especialista en urgencias, protocolo ABCDE, activa ante riesgo vital
- DifferentialDiagnosisAgent: genera hipótesis diagnósticas diferenciales, activa en casos complejos o ambiguos
- CardiologyAgent: interpreta ECG, arritmias, cambios ST, bloqueos, hipertrofia — activar cuando hay datos cardiológicos específicos
- PharmacologyAgent: seguridad farmacológica, interacciones, ajuste de dosis — activar cuando hay medicación relevante o dudas terapéuticas
- RadiologyAgent: interpreta imagen médica (RX, TAC, RM, ecografía) — activar cuando hay estudio de imagen

REGLAS DE ACTIVACIÓN:
- CRITICO/MUY_URGENTE → EmergencyAgent SIEMPRE + ClinicalAgent
- CRITICO → agregar DifferentialDiagnosisAgent si el caso es multisistémico o ambiguo
- URGENTE con síntomas complejos → ClinicalAgent + DifferentialDiagnosisAgent
- URGENTE simple → ClinicalAgent solo
- NO_URGENTE → ClinicalAgent solo
- Si hay datos de ECG, arritmia o cambios ST → agregar CardiologyAgent
- Si hay medicación relevante, interacciones o ajuste de dosis → agregar PharmacologyAgent
- Si hay imagen médica (RX/TAC/RM/ecografía) → agregar RadiologyAgent
- Los agentes especialistas (Cardiology/Pharmacology/Radiology) se activan por CONTENIDO, no por urgencia

Respondé ÚNICAMENTE con el JSON solicitado. Sin explicaciones adicionales.

{format_instructions}"""


class AgentRouter:
    """
    AgentRouter — Fase 6.

    Chain LCEL simple (sin RAG):
      dict input → prompt → llm → PydanticOutputParser(TriageOutput)

    Input: {"texto_clinico": str, "sintomas": str}
    Output: TriageOutput (nivel_urgencia, agentes_sugeridos, razonamiento)
    """

    def __init__(self) -> None:
        # PydanticOutputParser sobre TriageOutput — reutilizamos el modelo existente
        # Genera las format_instructions automáticamente igual que en los otros agentes
        parser = PydanticOutputParser(pydantic_object=TriageOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "Caso clínico: {texto_clinico}\nSíntomas reportados: {sintomas}"),
        ]).partial(format_instructions=parser.get_format_instructions())

        # temperature=0.0 — cero — las decisiones de triage NO son creativas
        # create_llm() centraliza la selección de proveedor (ver app/core/llm.py)
        llm = create_llm(temperature=0.0)

        # Chain simple — sin RAG, sin RunnablePassthrough
        # El prompt recibe directamente el dict que le pasamos en ainvoke
        self.chain = prompt | llm | parser

    async def run(self, texto_clinico: str, sintomas: list[str]) -> TriageOutput:
        sintomas_str = ", ".join(sintomas) if sintomas else "no especificados"
        return await self.chain.ainvoke({
            "texto_clinico": texto_clinico,
            "sintomas": sintomas_str,
        })
