"""
╔══════════════════════════════════════════════════════════════════════════════╗
║     CONFIGURACIONES DE AGENTES — Fase 12: Discriminated Unions              ║
║                                                                              ║
║  Este archivo enseña uno de los patrones más poderosos de Pydantic v2:      ║
║  las UNIONES DISCRIMINADAS (Discriminated Unions).                           ║
║                                                                              ║
║  ¿QUÉ ES UNA UNIÓN DISCRIMINADA?                                             ║
║  ──────────────────────────────                                              ║
║  Una unión discriminada es un tipo que puede ser UNO de varios tipos,       ║
║  donde hay un campo especial (el "discriminador") que le dice a Pydantic    ║
║  cuál de las opciones usar para parsear los datos.                          ║
║                                                                              ║
║  SIN discriminador (unión regular):                                          ║
║    Pydantic prueba cada opción en orden hasta que una funcione:             ║
║                                                                              ║
║    Union[ClinicalConfig, EmergencyConfig, RouterConfig]                      ║
║    Input: {"agent_type": "emergency", "temperature": 0.3}                   ║
║      Intenta ClinicalConfig → falla                                         ║
║      Intenta EmergencyConfig → ¡funciona!                                   ║
║                                                                              ║
║    Problema: O(n) intentos — lento, propenso a errores silenciosos           ║
║                                                                              ║
║  CON discriminador (unión discriminada):                                     ║
║    Pydantic mira el campo discriminador primero → salta directo a la clase: ║
║                                                                              ║
║    Annotated[ClinicalConfig | EmergencyConfig | RouterConfig,               ║
║              Field(discriminator="agent_type")]                              ║
║    Input: {"agent_type": "emergency", "temperature": 0.3}                   ║
║      Lee agent_type = "emergency" → instantáneamente elige EmergencyConfig  ║
║                                                                              ║
║    Ventaja: O(1) — sin trial-and-error, validación exacta                   ║
║                                                                              ║
║  ¿CÓMO FUNCIONA EL DISCRIMINADOR?                                            ║
║  ──────────────────────────────────                                          ║
║  El truco está en el tipo `Literal`:                                         ║
║                                                                              ║
║    class ClinicalAgentConfig(BaseAgentConfig):                               ║
║        agent_type: Literal["clinical"] = "clinical"                         ║
║                                                                              ║
║  `Literal["clinical"]` dice: este campo SOLO puede tener el valor           ║
║  "clinical". No "CLINICAL", no "Clinical" — exactamente "clinical".         ║
║                                                                              ║
║  Pydantic usa este Literal como mapa: si el JSON trae                       ║
║  `{"agent_type": "clinical"}`, sabe que debe instanciar ClinicalAgentConfig ║
║                                                                              ║
║  JSON SCHEMA OUTPUT:                                                         ║
║  ────────────────────                                                        ║
║  La unión discriminada genera un schema OpenAPI correcto con `oneOf`:       ║
║                                                                              ║
║  {                                                                           ║
║    "oneOf": [                                                                ║
║      {"$ref": "#/components/schemas/ClinicalAgentConfig"},                  ║
║      {"$ref": "#/components/schemas/EmergencyAgentConfig"},                 ║
║      {"$ref": "#/components/schemas/RouterConfig"}                           ║
║    ],                                                                        ║
║    "discriminator": {                                                        ║
║      "propertyName": "agent_type",                                          ║
║      "mapping": {                                                            ║
║        "clinical": "#/components/schemas/ClinicalAgentConfig",             ║
║        "emergency": "#/components/schemas/EmergencyAgentConfig",            ║
║        "router": "#/components/schemas/RouterConfig"                        ║
║      }                                                                       ║
║    }                                                                         ║
║  }                                                                           ║
║                                                                              ║
║  Sin discriminador, generaría un `anyOf` sin mapeo — los clientes no        ║
║  saben cómo elegir el schema correcto.                                       ║
║                                                                              ║
║  DISCRIMINATED UNION vs HERENCIA POLIMÓRFICA:                                ║
║  ─────────────────────────────────────────────                              ║
║  Herencia polimórfica (OOP clásico):                                         ║
║    - Funciona bien en código Python puro                                     ║
║    - Pero al serializar/deserializar JSON, perdés el tipo                   ║
║    - No hay forma nativa de saber qué subclase reconstruir desde un dict    ║
║                                                                              ║
║  Discriminated Union (Pydantic):                                             ║
║    - El tipo se preserva en el JSON (campo agent_type)                      ║
║    - Deserialización instantánea y sin ambigüedad                           ║
║    - JSON Schema correcto para clientes TypeScript, etc.                    ║
║                                                                              ║
║  Usá discriminated unions cuando:                                            ║
║    ✓ Tenés un campo que identifica el "tipo" del objeto                     ║
║    ✓ Diferentes tipos tienen campos diferentes                              ║
║    ✓ Los datos vienen de JSON (APIs, eventos, mensajes)                     ║
║    ✓ Querés validación O(1) sin trial-and-error                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from typing import Annotated, Literal
from pydantic import BaseModel, Field


class BaseAgentConfig(BaseModel):
    """
    Configuración base compartida por TODOS los agentes.

    Esta clase nunca se instancia directamente — es una "clase abstracta de
    facto" que define los campos comunes. Cada agente concreto la extiende
    y agrega sus campos específicos.

    Analogía:
    ─────────
    Es como el plano base de un hospital: todos los pisos tienen escaleras,
    ascensores y salidas de emergencia. Cada piso agrega sus propias salas.

    Campos:
        temperature: controla la "creatividad" del LLM.
            0.0 = determinista (siempre la misma respuesta)
            1.0 = máxima variabilidad (respuestas creativas/random)
            Para clínica recomendamos 0.1-0.3 (precisión sobre creatividad)

        max_retries: cuántas veces reintentar si el LLM falla o devuelve
            JSON inválido. Con 3 retries, toleramos 2 fallos transitorios.

        timeout_seconds: tiempo máximo de espera por respuesta del LLM.
            30 segundos es razonable para modelos medianos (llama-3.3-70b).
            Para casos de emergencia, podrías querer reducirlo a 15s.
    """

    temperature: float = Field(ge=0.0, le=1.0, description="Temperatura del LLM (0=determinista, 1=creativo)")
    max_retries: int = Field(default=3, ge=1, description="Reintentos ante fallo del LLM")
    timeout_seconds: float = Field(default=30.0, gt=0, description="Timeout en segundos para llamadas al LLM")


class ClinicalAgentConfig(BaseAgentConfig):
    """
    Configuración para ClinicalAgent — análisis clínico general con RAG.

    ╔══════════════════════════════════════════════════════════════════╗
    ║  EL ROL DEL CAMPO `agent_type: Literal["clinical"]`             ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  `Literal["clinical"]` es el DISCRIMINADOR.                     ║
    ║                                                                  ║
    ║  Significa: "este campo SIEMPRE tiene el valor 'clinical',      ║
    ║  nunca otro". Esto le permite a Pydantic hacer el mapeo:        ║
    ║                                                                  ║
    ║    JSON: {"agent_type": "clinical", ...}                        ║
    ║      → Pydantic ve "clinical" en el discriminador               ║
    ║      → Instancia ClinicalAgentConfig directamente               ║
    ║      → Sin trial-and-error, sin ambigüedad                      ║
    ║                                                                  ║
    ║  El valor por defecto `= "clinical"` hace que al crear la clase ║
    ║  en Python no tengas que especificar agent_type manualmente:    ║
    ║                                                                  ║
    ║    ClinicalAgentConfig(temperature=0.2, rag_k=5)               ║
    ║    # agent_type="clinical" ya está seteado por defecto          ║
    ╚══════════════════════════════════════════════════════════════════╝

    El ClinicalAgent usa RAG (Retrieval Augmented Generation) para
    contextualizar sus respuestas con documentación médica real.
    `rag_k` controla cuántos documentos recuperar del vector store.
    """

    agent_type: Literal["clinical"] = "clinical"
    rag_k: int = Field(default=3, ge=1, description="Documentos a recuperar del vector store")


class EmergencyAgentConfig(BaseAgentConfig):
    """
    Configuración para EmergencyAgent — emergencias críticas con RAG y prioridad.

    El EmergencyAgent combina RAG (como el ClinicalAgent) con un boost de
    prioridad que eleva el nivel de urgencia de los hallazgos. Está diseñado
    para casos CRITICO o MUY_URGENTE donde la velocidad y la precisión son
    más importantes que la exhaustividad.

    Campos adicionales:
        priority_boost: si True, el agente pone énfasis extra en protocolos
            de emergencia y posibles diagnósticos que amenazan la vida.
            En la práctica, esto se inyecta en el system prompt.
    """

    agent_type: Literal["emergency"] = "emergency"
    rag_k: int = Field(default=3, ge=1, description="Documentos a recuperar del vector store")
    priority_boost: bool = Field(default=True, description="Activa protocolos de emergencia en el prompt")


class RouterConfig(BaseAgentConfig):
    """
    Configuración para AgentRouter — enrutamiento de casos a agentes especialistas.

    El Router NO usa RAG. Su función es determinar qué agentes deben
    analizar un caso clínico, basándose únicamente en el texto del caso
    y el nivel de urgencia.

    ¿Por qué no necesita RAG?
    ─────────────────────────
    El Router hace una tarea de clasificación/routing, no de análisis médico.
    No necesita recuperar documentación clínica — solo necesita identificar
    qué agentes son relevantes para el caso.

    Dar RAG al Router sería un desperdicio de tokens y latencia.
    """

    agent_type: Literal["router"] = "router"


# ─── Discriminated Union ──────────────────────────────────────────────────────

"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AgentConfig — El Discriminated Union completo                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Syntaxis:                                                                   ║
║    AgentConfig = Annotated[                                                  ║
║        ClinicalAgentConfig | EmergencyAgentConfig | RouterConfig,           ║
║        Field(discriminator="agent_type"),                                   ║
║    ]                                                                         ║
║                                                                              ║
║  `Annotated[T, metadata]` es la forma de Python de decir:                  ║
║    "el tipo es T, con metadata adicional".                                   ║
║  Pydantic interpreta el Field(discriminator=...) en el metadata             ║
║  para saber qué campo usar como discriminador.                              ║
║                                                                              ║
║  Para validar un dict como AgentConfig, usás TypeAdapter:                   ║
║                                                                              ║
║    from pydantic import TypeAdapter                                          ║
║    adapter = TypeAdapter(AgentConfig)                                        ║
║                                                                              ║
║    config = adapter.validate_python({                                        ║
║        "agent_type": "clinical",                                            ║
║        "temperature": 0.2,                                                  ║
║        "rag_k": 5,                                                          ║
║    })                                                                        ║
║    # config es una instancia de ClinicalAgentConfig                         ║
║    assert isinstance(config, ClinicalAgentConfig)  # True                  ║
║                                                                              ║
║  Si mandás un agent_type inválido:                                          ║
║    adapter.validate_python({"agent_type": "inexistente", ...})              ║
║    → ValidationError: Input tag 'inexistente' found using 'agent_type'      ║
║      doesn't match any of the expected tags: 'clinical', 'emergency',       ║
║      'router'                                                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

AgentConfig = Annotated[
    ClinicalAgentConfig | EmergencyAgentConfig | RouterConfig,
    Field(discriminator="agent_type"),
]
