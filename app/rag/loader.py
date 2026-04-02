"""
Loader — cargar y chunkear documentos clínicos.

¿Por qué necesitamos "chunks"?

Imaginá que tenés un PDF de 50 páginas con protocolos clínicos.
No podés mandarlo entero al LLM porque:
  1. Los LLMs tienen un límite de tokens (contexto)
  2. Mandar 50 páginas cuando solo necesitás 1 párrafo es desperdicio
  3. Los embeddings de textos CORTOS son más precisos que los de textos largos

Entonces lo que hacemos es:
  1. Cargar el documento completo
  2. Dividirlo en fragmentos (chunks) de ~500 caracteres
  3. Guardar CADA chunk como un vector separado en la base de datos

Cuando el agente busca contexto relevante, recupera los chunks específicos
que responden a su pregunta — no todo el documento.

Analogía: el índice de un libro.
No releés el libro entero — vas directo al capítulo relevante.
El chunking hace posible ese salto directo.

Chunk overlap:
  Chunk 1: "...dolor torácico irradiado al brazo izquierdo. La presión..."
  Chunk 2: "La presión arterial estaba elevada. Se realizó ECG..."
               ↑
           50 chars de overlap
  El overlap evita que una frase importante quede cortada en el límite.

Esta función carga TODOS los .md de docs/ — ahí está el conocimiento del sistema:
  - docs/architecture/: flujo clínico, reglas de enrutado, prioridades
  - docs/prompts/: comportamiento de cada agente especializado
"""

from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


# Directorio raíz del proyecto (dos niveles arriba de app/rag/)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCS_DIR = _PROJECT_ROOT / "docs"


def load_docs_directory(docs_dir: Path = DOCS_DIR) -> list[Document]:
    """
    Carga todos los archivos .md de docs/ como objetos Document.

    Document es el contenedor estándar de LangChain:
      - page_content: el texto del fragmento
      - metadata: información extra (source, category, etc.)

    La metadata es importante porque cuando el retriever devuelve
    un chunk, podés saber de qué archivo vino.
    """
    documents: list[Document] = []

    for md_file in docs_dir.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")

        # Guardamos el path relativo a docs/ como source
        # Ejemplo: "architecture/routing-rules.md"
        relative_path = md_file.relative_to(docs_dir)

        documents.append(Document(
            page_content=text,
            metadata={
                "source": str(relative_path),
                "category": relative_path.parts[0],  # "architecture" o "prompts"
                "filename": md_file.name,
            }
        ))

    return documents


def split_documents(
    documents: list[Document],
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Document]:
    """
    Divide los documentos en chunks más pequeños.

    RecursiveCharacterTextSplitter intenta dividir respetando separadores
    naturales en este orden: párrafos → líneas → palabras → caracteres.
    Nunca corta una palabra por la mitad si puede evitarlo.

    chunk_size=500: máximo 500 caracteres por chunk
    chunk_overlap=50: 50 caracteres compartidos entre chunks consecutivos
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_documents(documents)


def load_and_split(
    docs_dir: Path = DOCS_DIR,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Document]:
    """
    Shortcut: carga Y divide en una sola llamada.
    Es lo que llama el script de indexación.
    """
    docs = load_docs_directory(docs_dir)
    return split_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def format_docs(docs: list[Document]) -> str:
    """
    Convierte una lista de Documents en un string para inyectar en el prompt.

    El retriever devuelve objetos Document. El prompt espera un string.
    Esta función hace el puente — concatena los chunks con su fuente.

    Ejemplo de salida:
      [Fuente: architecture/routing-rules.md]
      Si hay dolor torácico → activar URGENCIAS primero.

      [Fuente: prompts/emergency-agent.md]
      Aplica ABCDE: Airway, Breathing, Circulation...
    """
    if not docs:
        return "No se encontró contexto relevante en la base de conocimiento."

    return "\n\n".join(
        f"[Fuente: {doc.metadata.get('source', 'desconocida')}]\n{doc.page_content}"
        for doc in docs
    )
