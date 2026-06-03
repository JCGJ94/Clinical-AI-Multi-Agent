"""
╔══════════════════════════════════════════════════════════════╗
║  FASE 5: ClinicalAgent con RAG                              ║
║                                                              ║
║  FASE 3 (sin RAG):                                          ║
║    chain = prompt | llm | parser                            ║
║    run() → chain.ainvoke({"caso_clinico": "..."})           ║
║                                                              ║
║  FASE 5 (con RAG):                                          ║
║    chain = {context: retriever | format, caso: passthrough} ║
║            | prompt | llm | parser                          ║
║    run() → chain.ainvoke("Paciente 62 años...")             ║
║                                                              ║
║  Diferencia clave: el agente ya NO responde solo con lo     ║
║  que "sabe" el LLM — primero busca en docs/, recupera       ║
║  los fragmentos más relevantes, y los inyecta en el prompt. ║
║  Las respuestas están fundamentadas en TU base de           ║
║  conocimiento, no en el entrenamiento del modelo.           ║
╚══════════════════════════════════════════════════════════════╝
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


# ─── System Prompt ─────────────────────────────────────────────────────────────
#
# Ahora tiene {context} — esa variable se rellena en tiempo de ejecución
# con los fragmentos recuperados del vector store.
# {format_instructions} sigue pre-rellenándose via .partial()
#
SYSTEM_PROMPT = """\
Eres un asistente clínico de IA especializado en análisis de casos médicos.
Analiza el caso clínico y responde ÚNICAMENTE con el objeto JSON solicitado.

CONTEXTO RECUPERADO (guías y protocolos clínicos):
{context}

Usa el contexto anterior cuando sea relevante para fundamentar tu análisis.

Reglas:
- confidence: número entre 0.0 y 1.0
- red_flags: solo señales de peligro inmediato
- context_sources: indica las fuentes del contexto que usaste (ej: ["architecture/routing-rules.md"])
- Responde siempre en español

{format_instructions}"""


class ClinicalAgent(BaseAgent):
    """
    ClinicalAgent — Fase 5: LangChain LCEL + RAG.

    Chain completa (lazy — se construye en _ensure_chain() la primera vez):
      string input (caso_clinico)
        ↓
      {
        "context":      retriever | format_docs,   ← busca docs relevantes
        "caso_clinico": RunnablePassthrough(),      ← pasa el string sin tocar
      }
        ↓
      prompt    ← recibe {"context": "...", "caso_clinico": "..."}
        ↓
      llm       ← genera respuesta informada por el contexto
        ↓
      parser    ← valida y estructura como AgentOutput

    ¿Por qué el input es ahora un string y no un dict?
    Porque el RETRIEVER necesita un string para buscar por similitud semántica.
    Si le pasás un dict {"caso_clinico": "..."}, busca el dict como texto.
    Con un string limpio, la búsqueda semántica funciona correctamente.

    NAME: constante de clase para asignación determinista de agent_name.
    No dependemos del LLM para saber quién somos.
    """

    NAME: ClassVar[str] = "ClinicalAgent"

    def __init__(self) -> None:
        # ── Parser ───────────────────────────────────────────────────────────
        self._parser = PydanticOutputParser(pydantic_object=AgentOutput)

        # ── Prompt con {context} y {format_instructions} ─────────────────────
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=self._parser.get_format_instructions())

        # ── LLM (multi-provider via Factory) ─────────────────────────────────
        # temperature=0.2 — balance entre precisión y capacidad de síntesis
        # create_llm() centraliza la selección de proveedor (ver app/core/llm.py)
        self._llm = create_llm(temperature=0.2)

        # ── Chain lazy — se construye en _ensure_chain() al primer run() ─────
        self._chain = None

    async def _ensure_chain(self) -> None:
        """
        Construye la chain RAG en la primera llamada a run().

        El retriever se inicializa aquí (async) para evitar llamadas
        sincrónicas bloqueantes en __init__.
        """
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
        # Construir la chain si aún no fue creada
        await self._ensure_chain()

        # Pasamos el string directamente — el retriever lo necesita para buscar
        result = await self._chain.ainvoke(caso_clinico)

        # Asignación determinista — no dependemos del LLM para saber quién somos
        result.agent_name = self.NAME
        return result
