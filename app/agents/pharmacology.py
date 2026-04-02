"""
PharmacologyAgent — Especialista en Farmacología Clínica.

Activación (según routing-rules.md):
  - Interacciones medicamentosas
  - Ajuste de dosis por función renal/hepática, edad, fragilidad
  - Efectos adversos y farmacovigilancia
  - Conciliación de medicación (ingreso/alta/cambios)
  - Deprescripción y optimización terapéutica

Prioridad de seguridad MÁXIMA — errores de medicación son prevenibles
y pueden ser fatales. Temperature 0.1.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.agents.base import BaseAgent
from app.models.clinical import AgentOutput
from app.core.config import get_settings
from app.rag.retriever import get_retriever
from app.rag.loader import format_docs


SYSTEM_PROMPT = """\
Eres un especialista en Farmacología Clínica con enfoque en seguridad y optimización terapéutica.
Tu misión es detectar riesgos farmacológicos y proponer un plan seguro y eficaz.

Proceso obligatorio:
1. Identifica medicación actual, indicación, comorbilidades y función renal/hepática
2. Clasifica urgencia farmacológica (tóxico/anafilaxia → red_flags inmediatas)
3. Analiza interacciones relevantes (prioriza las peligrosas)
4. Evalúa contraindicaciones, duplicidades, ajustes por órgano
5. Propone monitorización concreta (qué vigilar, cuándo, umbrales)

Medicamentos de alto riesgo — extrema cautela:
- Anticoagulantes / antiagregantes
- Insulina y antidiabéticos orales
- Opioides y sedantes
- Antiarrítmicos y fármacos que prolongan QT
- Litio, digoxina, valproato, inmunosupresores

Red flags farmacológicas:
- Anafilaxia / angioedema
- Depresión respiratoria / síndrome serotoninérgico / NMS
- Hemorragia mayor por anticoagulantes
- Toxicidad por fármaco de estrecho margen terapéutico

CONTEXTO CLÍNICO DE REFERENCIA:
{context}

Reglas:
- findings: hallazgos farmacológicos (interacciones, ajustes, duplicidades)
- red_flags: riesgos farmacológicos críticos que requieren acción inmediata
- recommendations: plan concreto (mantener/suspender/ajustar + monitorización)
- confidence: basado en completitud de la información (0.0–1.0)
- Responde siempre en español

{format_instructions}"""


class PharmacologyAgent(BaseAgent):
    """
    PharmacologyAgent — Fase 7.

    Mismo patrón RAG que los demás agentes.
    Diferencias:
      - System prompt: enfoque en seguridad farmacológica
      - temperature=0.1 — mínima creatividad, máxima precisión en medicación
      - agent_name="PharmacologyAgent" en el output
    """

    def __init__(self) -> None:
        settings = get_settings()

        parser = PydanticOutputParser(pydantic_object=AgentOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=parser.get_format_instructions())

        if settings.llm_provider == "groq":
            llm = ChatGroq(
                api_key=settings.groq_api_key,
                model=settings.llm_model,
                temperature=0.1,
            )
        elif settings.llm_provider == "lmstudio":
            llm = ChatOpenAI(
                base_url=settings.lmstudio_base_url,
                api_key="lm-studio",
                model=settings.llm_model,
                temperature=0.1,
            )
        else:
            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=settings.llm_model,
                temperature=0.1,
            )

        retriever = get_retriever(k=3)

        self.chain = (
            {
                "context": retriever | format_docs,
                "caso_clinico": RunnablePassthrough(),
            }
            | prompt
            | llm
            | parser
        )

    async def run(self, caso_clinico: str) -> AgentOutput:
        return await self.chain.ainvoke(caso_clinico)
