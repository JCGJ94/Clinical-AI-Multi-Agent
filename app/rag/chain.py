"""
RAG Chain — Fase 4.

Esta es la chain más importante del proyecto. Es donde todo se conecta.

SIN RAG (lo que teníamos en Fase 2 y 3):
  caso_clinico → LLM → respuesta
  El LLM solo sabe lo que aprendió en entrenamiento.
  Puede alucinar. No conoce TUS protocolos.

CON RAG (lo que construimos acá):
  caso_clinico → retriever → [doc1, doc2, doc3]
                ↓
  [caso_clinico + doc1 + doc2 + doc3] → LLM → respuesta fundamentada

La chain en LCEL:

  {
    "context": retriever,           ← busca docs relevantes para la query
    "caso_clinico": passthrough     ← pasa la query original sin modificar
  }
  | prompt                          ← arma el mensaje con context + caso_clinico
  | llm                             ← genera la respuesta
  | StrOutputParser()               ← extrae el texto de la respuesta

RunnablePassthrough:
  Es el componente LCEL que "deja pasar" el input sin modificarlo.
  Lo necesitamos porque la chain tiene DOS inputs que llegan en paralelo:
    1. retriever recibe la query y devuelve documentos
    2. passthrough recibe la query y la pasa directamente al prompt

Así el prompt recibe TANTO el contexto recuperado COMO la pregunta original.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.rag.retriever import get_retriever
from app.core.config import get_settings


# ─── Prompt RAG ────────────────────────────────────────────────────────────────
#
# El prompt tiene DOS partes:
#   1. {context}: los documentos recuperados por el retriever
#   2. {caso_clinico}: la pregunta original del médico
#
# El LLM recibe TODO esto junto y genera una respuesta informada.
#
RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
Eres un asistente clínico especializado. Analiza el caso clínico \
usando el siguiente contexto de guías y protocolos clínicos.

CONTEXTO RECUPERADO:
{context}

Basa tu análisis en el contexto anterior cuando sea relevante.
Si el contexto no es suficiente, usa tu conocimiento clínico.
Responde siempre en español."""),
    ("human", "{caso_clinico}"),
])


def _format_docs(docs: list) -> str:
    """
    Convierte la lista de Documents en un string para el prompt.

    El retriever devuelve objetos Document con page_content y metadata.
    El prompt espera un string, así que los concatenamos.

    Ejemplo de salida:
      [Fuente: architecture/routing-rules.md]
      Si existen signos de posible amenaza vital...

      [Fuente: prompts/clinical-agent.md]
      Eres un médico especialista en Medicina Interna...
    """
    return "\n\n".join(
        f"[Fuente: {doc.metadata.get('source', 'desconocida')}]\n{doc.page_content}"
        for doc in docs
    )


def build_rag_chain(k: int = 3):
    """
    Construye la chain RAG completa.

    Parámetros:
      k: número de documentos a recuperar del vector store

    Devuelve una chain LCEL lista para ainvoke().
    Input esperado: {"caso_clinico": "Paciente de 62 años..."}
    Output: string con la respuesta del LLM fundamentada en los docs

    Requiere:
      - PostgreSQL corriendo (docker compose up)
      - Documentos indexados (correr el script de indexación)
      - OPENAI_API_KEY para embeddings
    """
    settings = get_settings()
    retriever = get_retriever(k=k)

    # LLM — misma lógica multi-provider que en clinical.py
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

    # ── La chain RAG ──────────────────────────────────────────────────────────
    #
    # Flujo cuando llamás chain.ainvoke({"caso_clinico": "Paciente 62 años..."}):
    #
    #  Input: {"caso_clinico": "Paciente 62 años con dolor torácico"}
    #    ↓
    #  {
    #    "context": retriever.ainvoke("Paciente 62 años con dolor torácico")
    #               → [Document("dolor torácico..."), Document("SCA..."), ...]
    #               → _format_docs([...])
    #               → "[Fuente: routing-rules.md]\n Si hay dolor torácico..."
    #
    #    "caso_clinico": RunnablePassthrough()
    #               → "Paciente 62 años con dolor torácico" (sin cambios)
    #  }
    #    ↓
    #  RAG_PROMPT.ainvoke({"context": "...", "caso_clinico": "..."})
    #    → [SystemMessage(context + instrucciones), HumanMessage(caso_clinico)]
    #    ↓
    #  llm.ainvoke([SystemMessage, HumanMessage])
    #    → AIMessage(content="Basado en las guías clínicas, este caso...")
    #    ↓
    #  StrOutputParser().ainvoke(AIMessage)
    #    → "Basado en las guías clínicas, este caso..."
    #
    return (
        {
            "context": retriever | _format_docs,
            "caso_clinico": RunnablePassthrough(),
        }
        | RAG_PROMPT
        | llm
        | StrOutputParser()
    )
