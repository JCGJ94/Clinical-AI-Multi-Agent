"""
DifferentialDiagnosisAgent — Motor de hipótesis diagnósticas.

Activación (según routing-rules.md):
  - Múltiples síntomas sin diagnóstico claro
  - Caso clínico complejo o multisistémico
  - Cuando ClinicalAgent no puede cerrar un diagnóstico

No sustituye a Urgencias ni a Cardiología/Radiología.
Su función es el razonamiento clínico diferencial.
"""

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
    """

    def __init__(self) -> None:
        parser = PydanticOutputParser(pydantic_object=AgentOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{caso_clinico}"),
        ]).partial(format_instructions=parser.get_format_instructions())

        # temperature=0.3 — algo más alto — creatividad diagnóstica es útil aquí
        # create_llm() centraliza la selección de proveedor (ver app/core/llm.py)
        llm = create_llm(temperature=0.3)

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
