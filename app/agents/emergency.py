"""
EmergencyAgent — Especialista en Medicina de Urgencias.

Activación (según routing-rules.md):
  - Dolor torácico agudo, disnea severa, shock
  - Alteración neurológica aguda, hemorragia activa
  - Cualquier caso con posible amenaza vital

SIEMPRE se activa antes que cualquier otro agente cuando hay riesgo vital.
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
      - agent_name = "EmergencyAgent" en el output
      - Activa red_flags agresivamente ante cualquier señal de riesgo vital
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
                temperature=0.1,  # más bajo que ClinicalAgent — urgencias requiere más precisión
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
