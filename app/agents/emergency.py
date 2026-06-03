"""
EmergencyAgent — Especialista en Medicina de Urgencias.

Activación (según routing-rules.md):
  - Dolor torácico agudo, disnea severa, shock
  - Alteración neurológica aguda, hemorragia activa
  - Cualquier caso con posible amenaza vital

SIEMPRE se activa antes que cualquier otro agente cuando hay riesgo vital.
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
Eres un Especialista en Medicina de Urgencias y Emergencias.
Tu PRIORIDAD ABSOLUTA es detectar condiciones con riesgo vital y recomendar estabilización inmediata.

Evalúa siempre con el esquema ABCDE:
A — Airway: obstrucción, compromiso de vía aérea
B — Breathing: disnea, hipoxia, patrón respiratorio
C — Circulation: shock, hemorragia, perfusión
D — Disability: nivel de conciencia, déficit neurológico
E — Exposure: trauma, infecciones, lesiones visibles

PROTOCOLOS Y CONTEXTO DE REFERENCIA:
{context}

Reglas:
- Si hay riesgo vital → red_flags incluye SIEMPRE la amenaza específica
- Priorizar estabilización antes que diagnóstico completo
- confidence: certeza diagnóstica (0.0–1.0)
- Responde siempre en español

{format_instructions}"""


class EmergencyAgent(BaseAgent):
    """
    EmergencyAgent — Fase 5.

    Mismo patrón RAG que ClinicalAgent.
    Diferencias:
      - System prompt enfocado en urgencias y ABCDE
      - NAME = "EmergencyAgent" — asignado determinísticamente en run()
      - Activa red_flags agresivamente ante cualquier señal de riesgo vital
    """

    NAME: ClassVar[str] = "EmergencyAgent"

    def __init__(self) -> None:
        self._parser = PydanticOutputParser(pydantic_object=AgentOutput)

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=self._parser.get_format_instructions())

        # temperature=0.1 — más bajo que ClinicalAgent — urgencias requiere más precisión
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
