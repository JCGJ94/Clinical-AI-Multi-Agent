"""
Excepciones personalizadas — Jerarquía de errores del sistema clínico.

¿Por qué crear excepciones propias y no usar las de Python directamente?
─────────────────────────────────────────────────────────────────────────

Pensá en un sistema de construcción. Cuando algo falla, ¿qué preferís escuchar?
  ❌ "Error inesperado" (RuntimeError genérico)
  ✅ "La cimentación del piso 3 tiene grietas en el sector norte" (específico)

Las excepciones propias permiten:

  1. SEMÁNTICA: el nombre de la excepción comunica QUÉ falló y DÓNDE.
     AgentExecutionError → fallo en un agente específico
     LLMProviderError    → problema con el proveedor de LLM (timeout, rate limit)
     RAGRetrievalError   → no se pudo acceder al vector store

  2. CONTEXTO ESTRUCTURADO: podés adjuntar datos al error.
     AgentExecutionError(agent_name="CardiologyAgent", cause=timeout_error)
     Ahora el handler sabe exactamente qué agente falló — no solo que "hubo un error".

  3. MANEJO DIFERENCIADO: el handler de FastAPI puede responder distinto según el tipo.
     ClinicalBaseError → 500 con JSON estructurado
     (en el futuro podés agregar: LLMProviderError → 503 Service Unavailable)

  4. HERENCIA Y CATCH SELECTIVO:
     try:
         ...
     except AgentExecutionError:     # solo errores de agentes
         handle_agent_failure()
     except ClinicalBaseError:       # cualquier otro error del sistema
         handle_generic_clinical()

Jerarquía:
  Exception
  └── ClinicalBaseError               ← base de todo lo nuestro
      ├── AgentExecutionError         ← un agente específico falló
      ├── AllAgentsFailedError        ← TODOS los agentes fallaron
      ├── LLMProviderError            ← error del proveedor LLM
      ├── RAGRetrievalError           ← error del vector store
      └── TriageError                 ← error en el router/triage
"""


class ClinicalBaseError(Exception):
    """
    Base de todas las excepciones del sistema clínico.

    ¿Por qué existe esta clase base?
    ──────────────────────────────────
    Para poder hacer un catch genérico en el middleware de FastAPI:

        @app.exception_handler(ClinicalBaseError)
        async def clinical_error_handler(request, exc):
            return JSONResponse(status_code=500, content={"error": ...})

    Sin esta base, tendríamos que registrar un handler por cada tipo.
    Con ella, UN handler captura todo el árbol de errores del sistema.

    El patrón "base exception" es estándar en proyectos serios:
      - Django: Django tiene ImproperlyConfigured, DatabaseError, etc., todos bajo Exception
      - SQLAlchemy: SQLAlchemyError es la base de todos sus errores
      - requests: RequestException es la base de ConnectionError, Timeout, etc.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class AgentExecutionError(ClinicalBaseError):
    """
    Se lanza cuando un agente específico falla durante su ejecución.

    ¿Cuándo usarla?
    ────────────────
    Cuando agent.run(caso_clinico) lanza cualquier excepción — timeout,
    error de LLM, JSON inválido en la respuesta, etc.

    El Integrator captura el error original y lo envuelve en AgentExecutionError,
    adjuntando el nombre del agente que falló. Esto es el patrón "Exception Chaining":

        try:
            result = await agent.run(caso_clinico)
        except Exception as e:
            raise AgentExecutionError(agent_name="CardiologyAgent", cause=e) from e

    ¿Por qué `from e`?
    La cadena de excepciones preserva el traceback original.
    Sin `from e`, perdés el contexto de dónde vino el error.

    Contexto estructurado:
      agent_name: saber qué agente falló sin parsear el mensaje de error
      cause: la excepción original para debugging
    """

    def __init__(self, agent_name: str, cause: Exception) -> None:
        self.agent_name = agent_name
        self.cause = cause
        super().__init__(
            f"El agente '{agent_name}' falló durante la ejecución: {cause}"
        )


class AllAgentsFailedError(ClinicalBaseError):
    """
    Se lanza cuando TODOS los agentes en un batch fallaron.

    ¿Cuándo usarla?
    ────────────────
    El Integrator ejecuta múltiples agentes en paralelo.
    Si alguno falla, captura el error y continúa con los que funcionaron.
    Pero si TODOS fallan, no hay resultados válidos que combinar →
    no tiene sentido retornar un AnalyzeOutput vacío → lanzamos esta excepción.

    ¿Por qué no simplemente retornar un AnalyzeOutput vacío?
    ──────────────────────────────────────────────────────────
    Un resultado vacío es engañoso: el sistema procesó el caso y no encontró nada.
    Un error es honesto: el sistema no pudo procesar el caso en absoluto.
    La diferencia importa para el médico que usa la herramienta.

    Contexto:
      agent_names: lista de los agentes que fallaron (todos)
      errors: lista de errores correspondientes para debugging
    """

    def __init__(self, agent_names: list[str], errors: list[Exception]) -> None:
        self.agent_names = agent_names
        self.errors = errors
        names_str = ", ".join(agent_names)
        super().__init__(
            f"Todos los agentes fallaron: [{names_str}]. "
            f"Primer error: {errors[0] if errors else 'desconocido'}"
        )


class LLMProviderError(ClinicalBaseError):
    """
    Se lanza ante errores del proveedor de LLM (OpenAI, Groq, LM Studio).

    ¿Cuándo usarla?
    ────────────────
    - Timeout en la llamada a la API
    - Rate limit superado (429 Too Many Requests)
    - Error de autenticación (clave API inválida)
    - Servicio no disponible (503)
    - Respuesta malformada del LLM

    ¿Por qué separar LLMProviderError de AgentExecutionError?
    ──────────────────────────────────────────────────────────
    AgentExecutionError indica que UN agente específico falló — puede ser
    por muchas razones (incluyendo un LLMProviderError interno).

    LLMProviderError es más específico: el problema está en la llamada
    al proveedor de LLM. Esto permite:
      - Reintentos automáticos SOLO para errores de proveedor (ver retry.py)
      - Alertas específicas de disponibilidad del servicio LLM
      - Fallback a otro proveedor (OpenAI → Groq → LM Studio)

    El decorator @async_retry en retry.py solo reintenta LLMProviderError,
    no AgentExecutionError genérico.
    """

    def __init__(self, message: str, provider: str | None = None) -> None:
        self.provider = provider
        prefix = f"[{provider}] " if provider else ""
        super().__init__(f"{prefix}Error del proveedor LLM: {message}")


class RAGRetrievalError(ClinicalBaseError):
    """
    Se lanza cuando el pipeline RAG falla al recuperar contexto del vector store.

    ¿Cuándo usarla?
    ────────────────
    - No se puede conectar a pgvector/PostgreSQL
    - La consulta de embeddings falla
    - El índice vectorial está corrupto o vacío
    - Timeout en la búsqueda de similitud

    ¿Por qué importa esta excepción?
    ─────────────────────────────────
    El RAG es el mecanismo que le da contexto clínico a los agentes.
    Sin RAG, los agentes trabajan sin protocolos de referencia — respuestas
    de menor calidad, potencialmente peligrosas en un contexto médico.

    Cuando el RAG falla, hay dos opciones:
      1. Fail fast: lanzar RAGRetrievalError → el médico sabe que el contexto no estuvo disponible
      2. Degraded mode: continuar sin contexto RAG pero advertir al médico

    Esta excepción permite que el caller tome esa decisión.
    En la implementación actual, el agente continúa sin contexto (degraded mode),
    pero lo ideal es que el médico sepa que el análisis fue sin base de conocimiento.
    """

    def __init__(self, message: str, query: str | None = None) -> None:
        self.query = query
        query_info = f" (query: '{query[:50]}...')" if query and len(query) > 50 else f" (query: '{query}')" if query else ""
        super().__init__(f"Error en la recuperación RAG{query_info}: {message}")


class TriageError(ClinicalBaseError):
    """
    Se lanza cuando el proceso de triage/routing falla.

    ¿Cuándo usarla?
    ────────────────
    - El AgentRouter no puede determinar el nivel de urgencia
    - La respuesta del LLM del router no es parseable como JSON
    - El router devuelve agentes que no existen en el registry
    - Timeout en el proceso de clasificación de urgencia

    ¿Por qué separar TriageError de LLMProviderError?
    ───────────────────────────────────────────────────
    LLMProviderError es a nivel de infraestructura: el servicio LLM no respondió.
    TriageError es a nivel de lógica de negocio: el LLM respondió, pero
    lo que devolvió no sirve para el triage (JSON inválido, campos faltantes, etc.).

    En un contexto médico, la distinción importa:
      - TriageError puede indicar que el prompt del router necesita ajuste
      - LLMProviderError indica un problema de infraestructura
    """

    def __init__(self, message: str, caso_clinico: str | None = None) -> None:
        self.caso_clinico = caso_clinico
        case_preview = f" (caso: '{caso_clinico[:80]}...')" if caso_clinico and len(caso_clinico) > 80 else f" (caso: '{caso_clinico}')" if caso_clinico else ""
        super().__init__(f"Error en el triage{case_preview}: {message}")
