"""
LLM Factory — Fase 11: centralización de la creación de modelos de lenguaje.

╔══════════════════════════════════════════════════════════════════════════════╗
║  EL PROBLEMA QUE RESUELVE ESTE MÓDULO                                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Antes de Fase 11, el bloque if/elif/else para seleccionar el proveedor     ║
║  de LLM estaba COPIADO EXACTAMENTE en 8 archivos:                           ║
║    - app/agents/clinical.py                                                 ║
║    - app/agents/emergency.py                                                ║
║    - app/agents/diagnosis.py                                                ║
║    - app/agents/cardiology.py                                               ║
║    - app/agents/pharmacology.py                                             ║
║    - app/agents/radiology.py                                                ║
║    - app/agents/router.py                                                   ║
║    - app/rag/chain.py                                                       ║
║                                                                              ║
║  Eso es CÓDIGO DUPLICADO. Y el código duplicado tiene consecuencias reales: ║
║    1. Si cambiás un proveedor → tenés que editar 8 archivos                 ║
║    2. Si hay un bug en la lógica → se copia el bug en 8 lugares             ║
║    3. Si agregás un proveedor nuevo → tenés que acordarte de los 8           ║
║                                                                              ║
║  La solución: DRY — Don't Repeat Yourself.                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRINCIPIO DRY — Don't Repeat Yourself
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

El principio DRY dice: "Cada pieza de conocimiento debe tener una representación
ÚNICA, sin ambigüedad, y de autoridad dentro de un sistema."

No se trata solo de no repetir código textualmente — se trata de no repetir
CONOCIMIENTO. La lógica "qué LLM instanciar según el proveedor configurado"
es conocimiento del sistema. Debe vivir en un SOLO lugar.

El opuesto de DRY es WET ("Write Everything Twice" / "We Enjoy Typing").
El código WET es frágil: dos copias pueden divergir silenciosamente y crear
bugs inconsistentes difíciles de rastrear.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PATRÓN FACTORY — creación centralizada de objetos
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

El Factory Pattern es uno de los patrones creacionales del GoF (Gang of Four).
La idea central: en lugar de que cada cliente cree sus propios objetos (con
new/constructor), delegás esa responsabilidad a una función o clase fábrica.

Ventajas del Factory aquí:
  1. CENTRALIZACIÓN: la decisión de qué clase instanciar vive en un lugar
  2. FLEXIBILIDAD: cambiar el proveedor no requiere tocar los agentes
  3. TESTABILIDAD: mockear create_llm es más simple que mockear cada clase
  4. EXTENSIBILIDAD: agregar un nuevo proveedor = modificar solo este archivo

Analogía real: una fábrica de autos no te pide que construyas el motor vos.
Vos pedís "quiero un auto con motor diesel" y la fábrica sabe qué piezas usar.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BaseChatModel — la abstracción que hace posible el Factory
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ChatGroq y ChatOpenAI son clases DISTINTAS, pero ambas heredan de BaseChatModel
de LangChain. BaseChatModel define el contrato:
  - ainvoke(input) → AIMessage
  - invoke(input) → AIMessage
  - stream(input) → Iterator[AIMessage]

Gracias a esta jerarquía, la cadena LCEL puede recibir `BaseChatModel` sin
saber si adentro hay Groq, OpenAI o cualquier otro — siempre respeta el mismo
contrato. Esto es el PRINCIPIO DE SUSTITUCIÓN DE LISKOV (L de SOLID).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SINGLE RESPONSIBILITY PRINCIPLE (S de SOLID) aplicado aquí
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Antes de Fase 11, ClinicalAgent tenía DOS responsabilidades:
  1. Construir y ejecutar la chain RAG para análisis clínico
  2. Decidir qué LLM instanciar según la configuración

Eso viola SRP. Un módulo debe tener UNA razón para cambiar.

Con este factory, ClinicalAgent solo tiene UNA responsabilidad: la chain.
Este módulo tiene UNA responsabilidad: crear el LLM correcto.
Si cambia la lógica de selección de proveedor → cambiamos SOLO este archivo.
"""

import logging
from enum import Enum

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger


logger: logging.Logger = get_logger(__name__)


class LLMProvider(str, Enum):
    """
    Enum de proveedores de LLM soportados.

    ¿Por qué un Enum y no strings sueltos?
    ────────────────────────────────────────
    Los strings sueltos son propensos a typos silenciosos:
      llm_provider = "grooq"  ← error tipográfico, Python no se queja

    Con Enum, el tipo es seguro en tiempo de análisis estático (mypy/pyright).
    Además, el Enum actúa como documentación viva: al leerlo sabés exactamente
    cuáles son los valores válidos sin buscar en el código de configuración.

    ¿Por qué `str, Enum`?
    ──────────────────────
    La herencia múltiple `str, Enum` hace que cada miembro sea a la vez un
    string y un valor de Enum. Esto permite comparar directamente con strings:
      LLMProvider.GROQ == "groq"  → True

    Es el patrón estándar en Python para enums que necesitan interoperar con
    código que ya usa strings (como valores de .env o bases de datos).
    """

    OPENAI = "openai"
    GROQ = "groq"
    LMSTUDIO = "lmstudio"
    OPENAI_COMPATIBLE = "openai_compatible"


def create_llm(temperature: float = 0.2) -> BaseChatModel:
    """
    Factory que crea el LLM correcto según la configuración activa.

    ¿Qué hace exactamente?
    ──────────────────────
    Lee el proveedor configurado en Settings.llm_provider y construye la
    instancia correspondiente de BaseChatModel con las credenciales y
    parámetros correctos.

    El único parámetro que varía entre agentes es la temperature — todos los
    demás parámetros (api_key, model, base_url) vienen de Settings.

    Parámetros:
        temperature: controla la aleatoriedad de las respuestas (0.0–1.0).
            0.0 = determinista, sin creatividad (ideal para triage, decisiones)
            0.1 = casi determinista (ideal para urgencias, farmacología, ECG)
            0.2 = leve variabilidad (agentes clínicos generales)
            0.3 = más creativo (diagnóstico diferencial — busca hipótesis)

    Retorna:
        BaseChatModel — puede ser ChatGroq, ChatOpenAI, u otro proveedor.
        El tipo de retorno es la clase BASE, no la concreta. Así el caller
        no necesita saber qué proveedor se usó — solo sabe que tiene un LLM.

    Lanza:
        ValueError si el proveedor configurado no está soportado.
        Esto es fallo rápido (fail-fast) — mejor detectar la config inválida
        al iniciar que recibir un error críptico al invocar la chain.
    """
    settings = get_settings()
    provider = settings.llm_provider

    logger.info(
        "Creating LLM",
        extra={
            "provider": str(provider),
            "model": settings.llm_model,
            "temperature": temperature,
        },
    )

    # Importación diferida para evitar dependencia circular en tests:
    # callbacks.py → logging.py → (nada más de app.core)
    # llm.py → callbacks.py → logging.py
    # Si logging.py importara llm.py tendríamos un ciclo.
    # La importación local es la solución idiomática para ciclos opcionales.
    from app.core.callbacks import LoggingCallbackHandler
    callbacks = [LoggingCallbackHandler()]

    if provider == LLMProvider.GROQ:
        # ChatGroq — proveedor por defecto en este proyecto
        # Usa modelos Llama 3.x, Mixtral vía Groq Cloud
        # Requiere GROQ_API_KEY en .env
        return ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.llm_model,
            temperature=temperature,
            callbacks=callbacks,
        )

    if provider == LLMProvider.LMSTUDIO:
        # LM Studio — servidor local de modelos open source
        # Compatible con la API de OpenAI, pero sin costo de API
        # api_key="lm-studio" es el placeholder que exige la interfaz de LM Studio
        # base_url apunta a tu servidor local (default: http://localhost:1234/v1)
        return ChatOpenAI(
            base_url=settings.lmstudio_base_url,
            api_key="lm-studio",
            model=settings.llm_model,
            temperature=temperature,
            callbacks=callbacks,
        )

    if provider == LLMProvider.OPENAI:
        # OpenAI — GPT-4o, GPT-4-turbo, etc.
        # Requiere OPENAI_API_KEY en .env
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            temperature=temperature,
            callbacks=callbacks,
        )

    if provider == LLMProvider.OPENAI_COMPATIBLE:
        # Proveedor genérico compatible con la API de OpenAI.
        # Ejemplos: Nvidia NIM, DeepSeek, Mistral AI, Anyscale, etc.
        # Requiere LLM_BASE_URL y LLM_API_KEY en .env.
        # El cliente es ChatOpenAI pero apuntando a otro endpoint.
        return ChatOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=temperature,
            callbacks=callbacks,
        )

    # Proveedor desconocido — fallo rápido con mensaje claro
    # Es preferible un ValueError explícito a un comportamiento indefinido
    valid = [p.value for p in LLMProvider]
    raise ValueError(
        f"Proveedor de LLM no soportado: '{provider}'. "
        f"Valores válidos: {valid}. "
        f"Verificá LLM_PROVIDER en tu .env"
    )
