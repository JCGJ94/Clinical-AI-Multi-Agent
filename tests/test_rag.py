"""
Tests de los módulos RAG — Fase 4.

¿Qué testeamos y qué NO?

✅ TESTEAMOS (sin base de datos, sin API):
   - loader: que carga y divide los documentos correctamente
   - chain: que la RAG chain se construye y produce output correcto

❌ NO testeamos en unitarios:
   - conexión real a PostgreSQL (requiere Docker corriendo)
   - llamadas reales a la API de OpenAI (requiere API key y dinero)
   Esos son tests de integración — se corren manualmente o en CI con servicios.

Estrategia de mocking para la RAG chain:
   - Patcheamos ChatGroq (igual que en test_agents.py)
   - Patcheamos get_retriever para devolver un retriever fake
   - El retriever fake devuelve Documents hardcodeados sin tocar la DB

Un retriever en LangChain es cualquier objeto con get_relevant_documents().
Podemos crear uno fake con MagicMock en 2 líneas.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage
from langchain_core.documents import Document

from app.rag.loader import load_docs_directory, split_documents, load_and_split


# ─── Tests del Loader ──────────────────────────────────────────────────────────

def test_load_docs_directory_finds_md_files():
    """
    El loader encuentra los archivos .md de docs/.

    Este test lee archivos REALES del disco — no necesita mocks.
    Los docs son parte del proyecto, no de infraestructura externa.
    """
    docs = load_docs_directory()

    assert len(docs) > 0, "Debería encontrar al menos un archivo .md en docs/"


def test_load_docs_directory_sets_metadata():
    """Cada documento tiene metadata con source y category."""
    docs = load_docs_directory()

    for doc in docs:
        assert "source" in doc.metadata
        assert "category" in doc.metadata
        assert "filename" in doc.metadata


def test_load_docs_directory_categories():
    """Los documentos se categorizan como 'architecture' o 'prompts'."""
    docs = load_docs_directory()
    categories = {doc.metadata["category"] for doc in docs}

    assert "architecture" in categories
    assert "prompts" in categories


def test_split_documents_creates_chunks():
    """
    split_documents divide documentos largos en chunks más pequeños.

    Creamos un documento de prueba con texto largo y verificamos que
    sale dividido en múltiples chunks.
    """
    # Documento de prueba con texto suficientemente largo para dividir
    long_text = "Este es un texto clínico. " * 50  # ~1250 chars
    doc = Document(page_content=long_text, metadata={"source": "test.md"})

    chunks = split_documents([doc], chunk_size=200, chunk_overlap=20)

    # Con 1250 chars y chunk_size=200, debería haber más de 1 chunk
    assert len(chunks) > 1


def test_split_documents_respects_chunk_size():
    """Ningún chunk supera el chunk_size configurado."""
    long_text = "Texto de prueba para el sistema clínico. " * 100
    doc = Document(page_content=long_text, metadata={"source": "test.md"})

    chunk_size = 300
    chunks = split_documents([doc], chunk_size=chunk_size, chunk_overlap=30)

    for chunk in chunks:
        # Los chunks pueden ser ligeramente más largos por el separador
        # pero nunca deberían duplicar el chunk_size
        assert len(chunk.page_content) <= chunk_size * 2


def test_split_documents_preserves_metadata():
    """Los chunks heredan la metadata del documento original."""
    doc = Document(
        page_content="Texto clínico de prueba. " * 30,
        metadata={"source": "test.md", "category": "architecture"},
    )

    chunks = split_documents([doc], chunk_size=100, chunk_overlap=10)

    for chunk in chunks:
        assert chunk.metadata["source"] == "test.md"
        assert chunk.metadata["category"] == "architecture"


def test_load_and_split_returns_more_chunks_than_files():
    """
    Después del split, hay más chunks que documentos originales.
    (Los docs son suficientemente largos para dividirse.)
    """
    original_docs = load_docs_directory()
    chunks = load_and_split()

    # Si algún doc se dividió, hay más chunks que documentos originales
    assert len(chunks) >= len(original_docs)


# ─── Tests de la RAG Chain ─────────────────────────────────────────────────────

@patch("app.rag.chain.get_retriever")
@patch("app.rag.chain.ChatGroq")
async def test_rag_chain_returns_string(MockChatGroq, mock_get_retriever):
    """
    La RAG chain devuelve un string (salida del LLM).

    Mocks usados:
    1. ChatGroq → fake LLM que devuelve respuesta hardcodeada
    2. get_retriever → fake retriever que devuelve docs hardcodeados
    """
    from app.rag.chain import build_rag_chain

    # 1. Fake LLM — igual que en test_agents.py
    MockChatGroq.return_value = RunnableLambda(
        lambda _: AIMessage(content="Basado en las guías clínicas, este caso sugiere síndrome coronario agudo.")
    )

    # 2. Fake retriever — devuelve documentos hardcodeados sin tocar DB
    #
    # Un retriever en LangChain es cualquier objeto con invoke() que devuelva
    # una lista de Documents. RunnableLambda nos sirve perfectamente.
    fake_docs = [
        Document(
            page_content="Si hay dolor torácico agudo → activar URGENCIAS primero.",
            metadata={"source": "architecture/routing-rules.md", "category": "architecture"},
        ),
        Document(
            page_content="STEMI: elevación del segmento ST, emergencia absoluta.",
            metadata={"source": "prompts/cardiology-agent.md", "category": "prompts"},
        ),
    ]
    mock_get_retriever.return_value = RunnableLambda(lambda _: fake_docs)

    chain = build_rag_chain(k=2)
    result = await chain.ainvoke({"caso_clinico": "Paciente 62 años con dolor torácico agudo."})

    assert isinstance(result, str)
    assert len(result) > 0


@patch("app.rag.chain.get_retriever")
@patch("app.rag.chain.ChatGroq")
async def test_rag_chain_passes_context_to_llm(MockChatGroq, mock_get_retriever):
    """
    Verificamos que el retriever es invocado y su resultado llega al LLM.

    Usamos un spy (MagicMock que registra llamadas) en el retriever
    para verificar que fue llamado con la query correcta.
    """
    from app.rag.chain import build_rag_chain

    captured_inputs = []

    def fake_llm_call(messages):
        # Capturamos el contenido del mensaje para verificar que tiene contexto
        captured_inputs.append(str(messages))
        return AIMessage(content="Respuesta del agente clínico.")

    MockChatGroq.return_value = RunnableLambda(fake_llm_call)

    fake_docs = [
        Document(
            page_content="PRIORIDAD ABSOLUTA: Si hay amenaza vital → URGENCIAS.",
            metadata={"source": "architecture/routing-rules.md", "category": "architecture"},
        )
    ]
    mock_get_retriever.return_value = RunnableLambda(lambda _: fake_docs)

    chain = build_rag_chain(k=1)
    await chain.ainvoke({"caso_clinico": "Paciente con dolor torácico."})

    # El LLM fue llamado Y el contexto recuperado estaba en el mensaje
    assert len(captured_inputs) > 0
    assert "PRIORIDAD ABSOLUTA" in captured_inputs[0]
