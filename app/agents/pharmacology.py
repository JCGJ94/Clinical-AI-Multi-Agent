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

from typing import ClassVar

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnablePassthrough

from app.agents.base import BaseAgent
from app.models.clinical import AgentOutput
from app.core.llm import create_llm
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
      - NAME = "PharmacologyAgent" — asignado determinísticamente en run()
    """

    NAME: ClassVar[str] = "PharmacologyAgent"

    def __init__(self) -> None:
        self._parser = PydanticOutputParser(pydantic_object=AgentOutput)

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=self._parser.get_format_instructions())

        # temperature=0.1 — mínima creatividad, máxima precisión en medicación
        # create_llm() centraliza la selección de proveedor (ver app/core/llm.py)
        self._llm = create_llm(temperature=0.1)

        # Chain lazy — se construye en _ensure_chain() al primer run()
        self._chain = None

    async def _ensure_chain(self) -> None:
        """Construye la chain RAG en la primera llamada a run()."""
        if self._chain is not None:
            return

        retriever = await get_retriever(k=3)

        self._chain = (
            {
                "context": retriever | format_docs,
                "caso_clinico": RunnablePassthrough(),
            }
            | self._prompt
            | self._llm
            | self._parser
        )

    async def run(self, caso_clinico: str) -> AgentOutput:
        await self._ensure_chain()
        result = await self._chain.ainvoke(caso_clinico)
        result.agent_name = self.NAME
        return result
