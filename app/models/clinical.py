"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          MODELOS CLÍNICOS — Clinical AI Multi-Agent                         ║
║                                                                              ║
║  Fase 12: Advanced Pydantic Patterns                                         ║
║                                                                              ║
║  Este archivo es el CORAZÓN del contrato de datos de la API.                ║
║  Pensalo como los planos de un edificio: definen exactamente qué             ║
║  forma tienen los datos que entran y salen del sistema.                      ║
║                                                                              ║
║  ¿QUÉ ES PYDANTIC?                                                           ║
║  ─────────────────                                                           ║
║  Pydantic es una biblioteca de validación de datos para Python.              ║
║  A diferencia de los dataclasses básicos, Pydantic:                          ║
║    1. Valida y convierte tipos automáticamente (coerción)                    ║
║    2. Genera JSON Schema / OpenAPI automáticamente                           ║
║    3. Serializa/deserializa a/desde JSON de forma segura                     ║
║    4. Permite validators personalizados para reglas de negocio               ║
║                                                                              ║
║  PYDANTIC V1 vs V2:                                                          ║
║  ──────────────────                                                          ║
║  V1 (legado):                                                                ║
║    class Config:                                                             ║
║        orm_mode = True                                                       ║
║        schema_extra = {...}                                                  ║
║    @validator("campo")        # decorador viejo                              ║
║    def validar(cls, v): ...                                                  ║
║                                                                              ║
║  V2 (actual — lo que usamos):                                                ║
║    model_config = ConfigDict(from_attributes=True, ...)                     ║
║    @field_validator("campo")  # decorador nuevo, más claro                  ║
║    @model_validator(mode="after")  # validación cruzada entre campos        ║
║    @computed_field              # campos calculados que se serializan        ║
║                                                                              ║
║  La migración v1→v2 fue un breaking change ENORME. Por eso en el mundo      ║
║  real todavía ves mucho código v1. Siempre verificá la versión instalada.   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from pydantic import BaseModel, Field, field_validator, model_validator, computed_field, ConfigDict
from enum import Enum


# ─── Enums ───────────────────────────────────────────────────────────────────

class NivelUrgencia(str, Enum):
    """
    Niveles de urgencia clínica basados en el sistema de triage Manchester.

    ¿Por qué hereda de `str` Y de `Enum`?
    ─────────────────────────────────────
    Heredar de `str` hace que el enum sea directamente serializable a JSON
    como string. Sin esto, `json.dumps({"nivel": NivelUrgencia.CRITICO})`
    fallaría porque Enum no es JSON-serializable por defecto.

    Con la herencia doble:
        NivelUrgencia.CRITICO == "CRITICO"  → True
        str(NivelUrgencia.CRITICO) → "NivelUrgencia.CRITICO"  (usa __str__)
        NivelUrgencia.CRITICO.value → "CRITICO"
    """
    CRITICO = "CRITICO"
    MUY_URGENTE = "MUY_URGENTE"
    URGENTE = "URGENTE"
    NO_URGENTE = "NO_URGENTE"


# ─── Inputs ──────────────────────────────────────────────────────────────────

class TriageInput(BaseModel):
    """
    Datos de entrada para el endpoint /triage.

    ╔══════════════════════════════════════════════════════════════════╗
    ║  PATRÓN: json_schema_extra — Ejemplos en la documentación       ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  Pydantic genera JSON Schema a partir de los modelos.           ║
    ║  FastAPI expone ese schema en /docs (Swagger UI).               ║
    ║                                                                  ║
    ║  Con `json_schema_extra.examples`, agregamos ejemplos reales    ║
    ║  que aparecen en la documentación interactiva de la API.        ║
    ║                                                                  ║
    ║  ¿Por qué importa?                                               ║
    ║    - Los consumidores de la API ven datos reales, no vacíos     ║
    ║    - Se puede hacer "Try it out" con un click en Swagger UI     ║
    ║    - Mejora la experiencia del desarrollador (DX)               ║
    ║                                                                  ║
    ║  ¿Cómo fluye a OpenAPI?                                          ║
    ║    TriageInput → Pydantic schema → FastAPI → /openapi.json      ║
    ║    → Swagger UI at /docs muestra los ejemplos automáticamente   ║
    ╚══════════════════════════════════════════════════════════════════╝

    ╔══════════════════════════════════════════════════════════════════╗
    ║  PATRÓN: @model_validator(mode="after") — Validación de modelo  ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  @model_validator vs @field_validator:                           ║
    ║  ─────────────────────────────────────                          ║
    ║  @field_validator("campo"):                                      ║
    ║    - Opera sobre UN campo individual                             ║
    ║    - No puede ver otros campos del modelo                        ║
    ║    - Ideal para: formateo, normalización, rangos numéricos       ║
    ║                                                                  ║
    ║  @model_validator(mode="after"):                                 ║
    ║    - Opera sobre el modelo COMPLETO ya construido                ║
    ║    - Puede leer/escribir TODOS los campos                        ║
    ║    - Ideal para: validaciones cruzadas, auto-completar campos    ║
    ║                                                                  ║
    ║  mode="before" vs mode="after":                                  ║
    ║  ──────────────────────────────                                  ║
    ║  mode="before":                                                  ║
    ║    - Se ejecuta ANTES de que Pydantic valide/coerce los tipos    ║
    ║    - Recibe datos crudos (dict o lo que sea)                     ║
    ║    - Se usa para transformar la forma de los datos de entrada    ║
    ║    - Ejemplo: renombrar claves, aplanar estructuras anidadas     ║
    ║                                                                  ║
    ║  mode="after":                                                   ║
    ║    - Se ejecuta DESPUÉS de que los tipos fueron validados        ║
    ║    - Recibe la instancia del modelo (self) ya construida         ║
    ║    - Se usa para lógica que necesita los campos ya tipados       ║
    ║    - Ejemplo: derivar un campo a partir de otros campos          ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "texto_clinico": "Paciente de 62 años con dolor torácico opresivo de 30 minutos de evolución",
                    "sintomas": ["dolor torácico", "sudoración", "disnea"],
                    "contexto": "Antecedente de hipertensión y diabetes",
                }
            ]
        }
    )

    texto_clinico: str = Field(min_length=10, description="Descripción del caso clínico")
    sintomas: list[str] = Field(min_length=1, description="Lista de síntomas")
    contexto: str | None = Field(default=None, description="Contexto adicional del paciente")

    @model_validator(mode="after")
    def auto_contexto_for_chest_pain(self) -> "TriageInput":
        """
        Auto-completa el campo `contexto` cuando se detecta dolor torácico.

        ¿Por qué mode="after"?
        ──────────────────────
        Necesitamos acceder a `self.sintomas` (ya convertido a list[str])
        y a `self.contexto` (ya convertido a str | None).
        Si usáramos mode="before", recibiríamos datos crudos — podría ser
        un dict, podría no tener los campos todavía. Con mode="after",
        el modelo ya fue construido y los tipos están garantizados.

        Analogía del mundo real:
        ─────────────────────────
        Es como un médico que, al rellenar la historia clínica, automáticamente
        marca "requiere evaluación cardiológica" cuando el paciente menciona
        dolor en el pecho — sin que el paciente tenga que saber que existe
        ese campo.

        Returns:
            self: siempre devolvemos self en mode="after"
        """
        if self.contexto is None:
            chest_keywords = {"dolor torácico", "dolor toracico", "chest pain", "dolor de pecho"}
            sintomas_lower = {s.lower() for s in self.sintomas}
            if any(kw in s for kw in chest_keywords for s in sintomas_lower):
                self.contexto = "Evaluación cardiológica recomendada"
        return self


class AnalyzeInput(BaseModel):
    """
    Datos de entrada para el endpoint /analyze.

    ╔══════════════════════════════════════════════════════════════════╗
    ║  PATRÓN: Validación cruzada de múltiples campos                 ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  El validator auto_agents_for_urgent opera sobre la combinación ║
    ║  de DOS campos: nivel_urgencia y agentes_sugeridos.             ║
    ║                                                                  ║
    ║  Esto es IMPOSIBLE con @field_validator porque ese decorador    ║
    ║  solo ve un campo. @model_validator(mode="after") puede ver     ║
    ║  el estado completo del objeto.                                  ║
    ║                                                                  ║
    ║  Regla de negocio implementada:                                  ║
    ║    Si urgencia CRITICO o MUY_URGENTE y no hay agentes → asignar ║
    ║    agentes de emergencia por defecto.                            ║
    ║                                                                  ║
    ║  ¿Por qué esto es valioso?                                       ║
    ║    Garantiza que los casos críticos SIEMPRE tienen agentes       ║
    ║    asignados, incluso si el frontend omite ese campo.           ║
    ║    El sistema es robusto ante inputs incompletos.                ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "caso_clinico": "Paciente de 45 años con dolor torácico agudo irradiado al brazo izquierdo, diaforesis y disnea de 20 minutos de evolución",
                    "nivel_urgencia": "CRITICO",
                    "agentes_sugeridos": ["EmergencyAgent", "ClinicalAgent"],
                }
            ]
        }
    )

    caso_clinico: str = Field(min_length=10, description="Caso clínico completo")
    nivel_urgencia: NivelUrgencia | None = Field(default=None, description="Urgencia pre-calculada")
    agentes_sugeridos: list[str] | None = Field(default=None, description="Agentes del triage previo")

    @model_validator(mode="after")
    def auto_agents_for_urgent(self) -> "AnalyzeInput":
        """
        Asigna agentes de emergencia automáticamente para casos críticos.

        Regla de negocio:
        ─────────────────
        Si el nivel de urgencia es CRITICO o MUY_URGENTE Y no se especificaron
        agentes, asignamos ['EmergencyAgent', 'ClinicalAgent'] por defecto.

        ¿Por qué es un model_validator y no un field_validator?
        ─────────────────────────────────────────────────────────
        La lógica depende de DOS campos simultáneamente:
            - nivel_urgencia (¿es crítico?)
            - agentes_sugeridos (¿está vacío?)

        @field_validator solo puede operar sobre un campo a la vez.
        No puede ver nivel_urgencia mientras valida agentes_sugeridos.

        @model_validator(mode="after") ve el objeto completo — exactamente
        lo que necesitamos para esta validación cruzada.

        Esto es el equivalente clínico de un protocolo de activación:
        "Si el paciente viene en paro cardíaco (CRITICO) y no hay equipo
        asignado, llamar automáticamente a emergencias y cardiología."

        Returns:
            self: el modelo con agentes_sugeridos auto-asignados si aplica
        """
        urgent_levels = {NivelUrgencia.CRITICO, NivelUrgencia.MUY_URGENTE}
        if self.nivel_urgencia in urgent_levels and self.agentes_sugeridos is None:
            self.agentes_sugeridos = ["EmergencyAgent", "ClinicalAgent"]
        return self


# ─── Outputs ─────────────────────────────────────────────────────────────────

class TriageOutput(BaseModel):
    """
    Resultado del triage clínico.

    ╔══════════════════════════════════════════════════════════════════╗
    ║  PATRÓN: Strict Mode — ConfigDict(strict=True)                  ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  ¿Qué es el modo estricto?                                       ║
    ║  ──────────────────────────                                      ║
    ║  Por defecto, Pydantic es "lax" (permisivo) — coerce tipos:     ║
    ║    "0.5"  → float (convierte el string)                         ║
    ║    1      → bool  (convierte el entero)                         ║
    ║    "true" → bool  (parsea el string)                            ║
    ║                                                                  ║
    ║  Con strict=True, Pydantic RECHAZA coerciones:                  ║
    ║    "0.5"  → ValidationError (string no es float)                ║
    ║    1      → ValidationError (int no es bool)                    ║
    ║                                                                  ║
    ║  ConfigDict (v2) vs class Config (v1):                           ║
    ║  ──────────────────────────────────────                         ║
    ║  # Pydantic v1 — LEGADO, no usar:                               ║
    ║  class TriageOutput(BaseModel):                                  ║
    ║      class Config:                                               ║
    ║          strict = True                                           ║
    ║                                                                  ║
    ║  # Pydantic v2 — CORRECTO:                                       ║
    ║  class TriageOutput(BaseModel):                                  ║
    ║      model_config = ConfigDict(strict=True)                      ║
    ║                                                                  ║
    ║  ¿Cuándo usar strict=True?                                       ║
    ║  ───────────────────────────                                     ║
    ║  → OUTPUTS de LLMs: el LLM debe devolver el tipo exacto.        ║
    ║    Si el LLM devuelve "CRITICO" (string) cuando esperamos        ║
    ║    el enum, queremos saber que algo está mal en el prompt.       ║
    ║                                                                  ║
    ║  ¿Cuándo usar lax (modo default)?                                ║
    ║  ──────────────────────────────────                              ║
    ║  → INPUTS de formularios/APIs: los usuarios mandan strings       ║
    ║    y Pydantic los convierte al tipo correcto.                    ║
    ║    "62" → int, "0.87" → float, "CRITICO" → NivelUrgencia.       ║
    ║                                                                  ║
    ║  NOTA PRÁCTICA para este proyecto:                               ║
    ║    El LangChain JsonOutputParser devuelve un dict con strings,   ║
    ║    no enums. Por eso usamos strict=True solo para documentar     ║
    ║    la intención, no como validación rígida en producción.        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    # NOTA PRÁCTICA: No activamos strict=True aquí aunque lo documentamos arriba.
    # LangChain's PydanticOutputParser llama model_validate(dict) donde el dict
    # viene de json.loads() — todos los valores son strings, no enums.
    # Con strict=True, "MUY_URGENTE" (str) no sería aceptado como NivelUrgencia.
    # La coerción lax es exactamente lo que necesitamos en el output del LLM.
    # Ver StrictExample en tests/test_pydantic_advanced.py para un ejemplo
    # funcional de strict=True aislado del sistema de producción.

    nivel_urgencia: NivelUrgencia
    agentes_sugeridos: list[str]
    razonamiento: str


class AgentOutput(BaseModel):
    """
    Resultado de un agente especializado (Cardiology, Emergency, etc.).

    ╔══════════════════════════════════════════════════════════════════╗
    ║  PATRÓN: @field_validator — Validación de un campo individual   ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  @field_validator("confidence") opera sobre el campo confidence ║
    ║  en aislamiento. No necesita ver otros campos.                   ║
    ║                                                                  ║
    ║  @field_validator vs @model_validator:                           ║
    ║  ──────────────────────────────────────                         ║
    ║  Usá @field_validator cuando:                                    ║
    ║    ✓ La validación aplica a UN solo campo                       ║
    ║    ✓ No necesitás ver el estado de otros campos                 ║
    ║    ✓ Es reutilizable (podés aplicarlo a múltiples campos)       ║
    ║    Ejemplos: normalizar strings, redondear floats, rangos       ║
    ║                                                                  ║
    ║  Usá @model_validator cuando:                                    ║
    ║    ✓ La validación involucra MÚLTIPLES campos                   ║
    ║    ✓ Querés derivar un campo a partir de otro                   ║
    ║    ✓ La validación es una regla de negocio de alto nivel        ║
    ║    Ejemplos: si A entonces B, campos mutuamente excluyentes     ║
    ║                                                                  ║
    ║  @classmethod es OBLIGATORIO en @field_validator (v2):          ║
    ║    Los validators de campo son métodos de clase porque se       ║
    ║    ejecutan antes de que exista una instancia del objeto.        ║
    ║    En mode="after" de @model_validator, ya hay instancia         ║
    ║    (self), por eso no necesita @classmethod.                    ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "agent_name": "<agent-class-name>",
                    "summary": "Presentación compatible con síndrome coronario agudo tipo IAM",
                    "findings": ["dolor torácico opresivo", "irradiación a brazo izquierdo", "diaforesis"],
                    "red_flags": ["posible IAM STEMI", "inestabilidad hemodinámica"],
                    "recommendations": ["ECG urgente de 12 derivaciones", "troponina I seriada", "AAS 300mg inmediato"],
                    "confidence": 0.92,
                    "context_sources": ["ESC Guidelines 2023 - ACS", "Harrison Cardiología Cap. 14"],
                }
            ]
        }
    )

    agent_name: str
    summary: str
    findings: list[str]
    red_flags: list[str]
    recommendations: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    context_sources: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        """
        Redondea el score de confianza a 4 decimales.

        ¿Por qué 4 decimales?
        ─────────────────────
        Los LLMs devuelven floats con mucha precisión (ej: 0.8567890123456789)
        que son artefactos de floating-point sin significado real.
        Un médico no puede distinguir entre 0.8568 y 0.8567890123456789 —
        son exactamente lo mismo en la práctica clínica.

        Redondear a 4 decimales:
            - Hace los valores más legibles en la API response
            - Reduce el tamaño del JSON
            - Elimina artefactos de precisión flotante

        Args:
            v: el float original antes de redondear

        Returns:
            float redondeado a 4 decimales
        """
        return round(v, 4)


class AnalyzeOutput(BaseModel):
    """
    Resultado completo del análisis multi-agente.

    ╔══════════════════════════════════════════════════════════════════╗
    ║  PATRÓN: @computed_field — Campos calculados que se serializan  ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║                                                                  ║
    ║  En Python, podés definir @property para calcular valores:      ║
    ║                                                                  ║
    ║    @property                                                      ║
    ║    def total_agents(self) -> int:                                ║
    ║        return len(self.agentes_activados)                        ║
    ║                                                                  ║
    ║  El PROBLEMA con @property en Pydantic:                         ║
    ║    model.total_agents  → funciona ✓                             ║
    ║    model.model_dump()  → NO incluye total_agents ✗              ║
    ║    model.model_dump_json() → NO incluye total_agents ✗          ║
    ║    JSON Schema / OpenAPI → NO documenta total_agents ✗          ║
    ║                                                                  ║
    ║  Con @computed_field (Pydantic v2):                              ║
    ║    model.total_agents        → funciona ✓                       ║
    ║    model.model_dump()        → incluye total_agents ✓           ║
    ║    model.model_dump_json()   → incluye total_agents ✓           ║
    ║    JSON Schema / OpenAPI     → documenta total_agents ✓         ║
    ║                                                                  ║
    ║  ¿Cuándo usar @computed_field vs almacenar el valor?            ║
    ║  ──────────────────────────────────────────────────────         ║
    ║  Usá @computed_field cuando:                                     ║
    ║    ✓ El valor puede derivarse de otros campos (no hay "truth"   ║
    ║      extra — es solo una vista diferente de los datos)          ║
    ║    ✓ Querés que aparezca en el JSON sin pedirlo explícitamente  ║
    ║    ✓ No tiene sentido enviarlo desde el cliente (es calculado)  ║
    ║                                                                  ║
    ║  Almacená el valor (campo normal) cuando:                       ║
    ║    ✓ El valor NO puede derivarse de otros campos                ║
    ║    ✓ Es enviado directamente por el cliente                     ║
    ║    ✓ Necesita ser persistido en la base de datos               ║
    ║                                                                  ║
    ║  Ejemplo práctico:                                               ║
    ║    success_rate: calculado → @computed_field                    ║
    ║    confidence: valor del LLM → campo normal                     ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    case_id: int | None = Field(default=None, description="ID del caso persistido en DB")
    summary: str
    findings: list[str]
    red_flags: list[str]
    recommendations: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    agentes_activados: list[str]
    agent_outputs: list[AgentOutput]
    failed_agents: list[str] = Field(default_factory=list, description="Agentes que fallaron durante el análisis")
    warnings: list[str] = Field(default_factory=list, description="Advertencias no críticas del análisis")

    @computed_field  # type: ignore[misc]
    @property
    def total_agents(self) -> int:
        """
        Total de agentes que participaron exitosamente en el análisis.

        Derivado de len(agentes_activados). Este campo aparece en el JSON
        de respuesta automáticamente gracias a @computed_field.

        Útil para clientes que necesitan saber cuántos agentes participaron
        sin contar los elementos de la lista manualmente.
        """
        return len(self.agentes_activados)

    @computed_field  # type: ignore[misc]
    @property
    def has_red_flags(self) -> bool:
        """
        Indica si el análisis identificó banderas rojas (señales de alarma).

        En medicina, las "red flags" o banderas rojas son síntomas o hallazgos
        que sugieren una condición potencialmente grave que requiere atención
        inmediata. Ejemplos: signos de infarto, shock séptico, hemorragia.

        Este campo computed permite a los clientes hacer un check rápido
        (if data["has_red_flags"]) sin evaluar la lista ellos mismos.
        """
        return len(self.red_flags) > 0

    @computed_field  # type: ignore[misc]
    @property
    def success_rate(self) -> float:
        """
        Ratio de agentes exitosos vs total de agentes invocados.

        Fórmula:
            total_invocados = len(agentes_activados) + len(failed_agents)
            success_rate = len(agentes_activados) / total_invocados

        Casos especiales:
            - Si no se invocó ningún agente → devuelve 0.0 (evita división por cero)
            - 1.0 = todos los agentes completaron exitosamente
            - 0.5 = la mitad de los agentes falló
            - 0.0 = todos fallaron o no hubo agentes

        El resultado se redondea a 2 decimales para legibilidad.
        """
        total = len(self.agentes_activados) + len(self.failed_agents)
        if total == 0:
            return 0.0
        return round(len(self.agentes_activados) / total, 2)


class ClinicalCaseRead(BaseModel):
    """Respuesta del GET /clinical-case/{case_id} — sin agent_outputs (verbose)."""
    id: int
    caso_clinico: str
    agentes_sugeridos: list[str] | None
    summary: str
    findings: list[str]
    red_flags: list[str]
    recommendations: list[str]
    confidence: float
    agentes_activados: list[str]
    created_at: str  # ISO 8601
