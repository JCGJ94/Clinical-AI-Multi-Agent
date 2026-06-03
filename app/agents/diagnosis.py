"""
DifferentialDiagnosisAgent — Motor de hipótesis diagnósticas.

Activación (según routing-rules.md):
  - Múltiples síntomas sin diagnóstico claro
  - Caso clínico complejo o multisistémico
  - Cuando ClinicalAgent no puede cerrar un diagnóstico

No sustituye a Urgencias ni a Cardiología/Radiología.
Su función es el razonamiento clínico diferencial.
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
Eres un especialista clínico en razonamiento diagnóstico y diagnóstico diferencial.
Tu misión es generar y priorizar hipótesis diagnósticas de forma rigurosa y útil.

Principios de razonamiento:
1. Primero lo peligroso, luego lo probable — incluye diagnósticos graves aunque sean menos probables
2. Coherencia fisiopatológica — cada hipótesis debe explicar los hallazgos principales
3. Parsimonia — prefiere una explicación unificada antes que múltiples diagnósticos innecesarios
4. Probabilidad condicionada — edad, sexo, antecedentes y tiempo de evolución pesan mucho

CONTEXTO CLÍNICO DE REFERENCIA:
{context}

Genera 3–6 hipótesis diagnósticas ordenadas por probabilidad Y peligrosidad.

Reglas:
- findings: incluye hallazgos que APOYAN cada diagnóstico diferencial
- red_flags: si hay riesgo vital → señalarlo inmediatamente
- recommendations: incluye las pruebas más discriminativas
- confidence: certeza del análisis (0.0–1.0)
- Responde siempre en español

{format_instructions}"""


class DifferentialDiagnosisAgent(BaseAgent):
    """
    DifferentialDiagnosisAgent — Fase 5.

    Especializado en generar diagnósticos diferenciales priorizados.
    Temperature ligeramente más alta que EmergencyAgent — la creatividad
    diagnóstica es un activo cuando se buscan hipótesis alternativas.

    NAME = "DifferentialDiagnosisAgent" — asignado determinísticamente en run().
    """

    NAME: ClassVar[str] = "DifferentialDiagnosisAgent"

    def __init__(self) -> None:
        self._parser = PydanticOutputParser(pydantic_object=AgentOutput)

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=self._parser.get_format_instructions())

        # temperature=0.3 — algo más alto — creatividad diagnóstica es útil aquí
        # create_llm() centraliza la selección de proveedor (ver app/core/llm.py)
        self._llm = create_llm(temperature=0.3)

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
