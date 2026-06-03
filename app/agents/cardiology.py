"""
CardiologyAgent — Especialista en interpretación electrocardiográfica.

Activación (según routing-rules.md):
  - Imagen de ECG o trazado electrocardiográfico
  - Sospecha de arritmia, cambios ST, bloqueos de conducción
  - Análisis de ritmo cardíaco

Diferencias respecto a EmergencyAgent:
  - EmergencyAgent: detecta amenaza vital, estabiliza, usa ABCDE
  - CardiologyAgent: interpreta el ECG de forma sistemática, profundidad cardiológica

Temperature 0.1 — la interpretación de ECG requiere máxima precisión.
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
Eres un cardiólogo clínico experto en electrocardiografía.
Tu función es analizar casos clínicos con componente cardiológico y generar un informe estructurado.

Método sistemático obligatorio cuando hay datos de ECG:
1. Frecuencia cardíaca y ritmo
2. Regularidad (intervalos RR)
3. Intervalos PR, QRS, QT/QTc
4. Eje eléctrico
5. Segmento ST (elevación/depresión → derivaciones afectadas)
6. Onda T e inversiones
7. Ondas Q patológicas
8. Hipertrofia ventricular

Urgencias cardiológicas → siempre en red_flags:
- Elevación ST compatible con IAM
- Taquicardia ventricular o fibrilación ventricular
- Bloqueo AV avanzado
- QT prolongado con riesgo de torsade

CONTEXTO CLÍNICO DE REFERENCIA:
{context}

Reglas:
- findings: hallazgos electrocardiográficos y cardiológicos objetivos
- red_flags: urgencias cardiológicas que requieren acción inmediata
- recommendations: pruebas complementarias y conducta cardiológica
- confidence: basado en calidad de los datos disponibles (0.0–1.0)
- Responde siempre en español

{format_instructions}"""


class CardiologyAgent(BaseAgent):
    """
    CardiologyAgent — Fase 7.

    Mismo patrón RAG que ClinicalAgent.
    Diferencias:
      - System prompt: método sistemático de interpretación ECG
      - temperature=0.1 — precisión máxima en cardiología
      - NAME = "CardiologyAgent" — asignado determinísticamente en run()
    """

    NAME: ClassVar[str] = "CardiologyAgent"

    def __init__(self) -> None:
        self._parser = PydanticOutputParser(pydantic_object=AgentOutput)

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=self._parser.get_format_instructions())

        # temperature=0.1 — la interpretación de ECG requiere máxima precisión
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
