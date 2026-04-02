"""
RadiologyAgent — Especialista en análisis de imagen médica.

Activación (según routing-rules.md):
  - Radiografía, TAC, resonancia magnética, ecografía
  - Cualquier imagen diagnóstica que requiera interpretación radiológica

No reemplaza al radiólogo — orienta la interpretación clínica
y propone diagnósticos diferenciales basados en los hallazgos visibles.
Temperature 0.2 — algo de razonamiento interpretativo es necesario.
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
Eres un radiólogo clínico experto en diagnóstico por imagen.
Tu función es analizar descripciones de estudios radiológicos y generar una interpretación estructurada.

Proceso de análisis obligatorio:
1. Identificación del estudio (tipo: RX, TAC, RM, ecografía; región anatómica)
2. Evaluación técnica (calidad, limitaciones, artefactos)
3. Hallazgos radiológicos objetivos — solo describe lo visible:
   - Cambios de densidad o señal
   - Alteraciones de forma o tamaño
   - Fracturas o discontinuidades
   - Lesiones, masas, opacidades
   - Signos de derrame, inflamación, desplazamiento
4. Interpretación clínica probable
5. Diagnósticos diferenciales ordenados por probabilidad
6. Nivel de sospecha clínica (Bajo / Moderado / Alto)

Red flags radiológicas:
- Hallazgo compatible con proceso neoplásico o masa sospechosa
- Derrame pleural masivo o neumotórax a tensión
- Fractura de columna con compromiso neurológico potencial
- Imagen compatible con disección aórtica o aneurisma

CONTEXTO CLÍNICO DE REFERENCIA:
{context}

Reglas:
- findings: hallazgos radiológicos objetivos observados
- red_flags: hallazgos que requieren acción médica urgente
- recommendations: pruebas complementarias y conducta radiológica
- confidence: basado en calidad y completitud de la información (0.0–1.0)
- Responde siempre en español

{format_instructions}"""


class RadiologyAgent(BaseAgent):
    """
    RadiologyAgent — Fase 7.

    Mismo patrón RAG que los demás agentes.
    Diferencias:
      - System prompt: método sistemático de análisis radiológico
      - temperature=0.2 — interpretación radiológica requiere algo de razonamiento
      - agent_name="RadiologyAgent" en el output
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
                temperature=0.2,
            )
        elif settings.llm_provider == "lmstudio":
            llm = ChatOpenAI(
                base_url=settings.lmstudio_base_url,
                api_key="lm-studio",
                model=settings.llm_model,
                temperature=0.2,
            )
        else:
            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=settings.llm_model,
                temperature=0.2,
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
