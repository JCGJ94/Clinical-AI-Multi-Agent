"""
Structured Logging — Fase 10: observabilidad con logging estructurado en JSON.

╔══════════════════════════════════════════════════════════════════════════════╗
║  ¿POR QUÉ LOGGING Y NO PRINT()?                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  La respuesta corta: print() es para prototipos. logging es para sistemas.  ║
║                                                                              ║
║  print() no tiene:                                                           ║
║    ✗ Niveles de severidad (¿es un debug? ¿un error crítico?)                 ║
║    ✗ Timestamps (¿cuándo pasó?)                                              ║
║    ✗ Contexto del módulo (¿qué archivo lo emitió?)                           ║
║    ✗ Filtrado (en producción no querés DEBUG, solo ERROR+)                   ║
║    ✗ Handlers múltiples (consola Y archivo Y CloudWatch simultáneamente)     ║
║    ✗ Formato configurable (texto plano vs JSON según el entorno)             ║
║                                                                              ║
║  Regla de oro de producción: NUNCA uses print() para observabilidad.        ║
╚══════════════════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
¿QUÉ ES LOGGING ESTRUCTURADO?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Logging NO estructurado (texto plano):
  2026-04-06 10:23:45 INFO ClinicalAgent completed in 1234ms with confidence 0.87

Logging ESTRUCTURADO (JSON):
  {
    "timestamp": "2026-04-06T10:23:45.123Z",
    "level": "INFO",
    "logger": "app.agents.clinical",
    "message": "Agent completed",
    "agent_name": "ClinicalAgent",
    "duration_ms": 1234,
    "confidence": 0.87
  }

¿Por qué JSON es mejor?
  1. MACHINE-PARSEABLE: Elasticsearch, Datadog, CloudWatch pueden indexar cada campo
  2. QUERYABLE: "dame todos los logs donde duration_ms > 5000" es trivial en JSON
  3. CONSISTENTE: no hay ambigüedad en el formato — cero parsing manual
  4. EXTENSIBLE: agregar un campo nuevo no rompe parsers existentes

Analogía real: es como la diferencia entre llevar notas en texto libre vs
una planilla Excel — la planilla es 100x más poderosa para análisis.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JERARQUÍA DE NIVELES DE LOGGING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  DEBUG    (10) — información de desarrollo, flujo interno, valores de variables
  INFO     (20) — eventos normales del sistema: inicio, fin, progreso
  WARNING  (30) — algo raro pasó pero el sistema sigue funcionando
  ERROR    (40) — algo falló, requiere atención, pero el sistema sobrevive
  CRITICAL (50) — fallo catastrófico, el sistema puede no poder continuar

La jerarquía es INCLUSIVA hacia arriba. Si configurás nivel=INFO, recibís
INFO + WARNING + ERROR + CRITICAL pero NO DEBUG.

En desarrollo → DEBUG (querés ver todo)
En producción → INFO o WARNING (solo lo relevante)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARQUITECTURA DEL SISTEMA DE LOGGING EN PYTHON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Python logging tiene tres conceptos clave:

  Logger: el punto de entrada que usás en tu código
    logger = logging.getLogger("app.agents.clinical")
    logger.info("mensaje", extra={"key": "value"})

  Handler: decides a DÓNDE van los mensajes
    - StreamHandler → consola (stdout/stderr)
    - FileHandler → archivo .log
    - (externo) CloudWatchHandler → AWS CloudWatch
    El mismo Logger puede tener MÚLTIPLES handlers simultáneamente.

  Formatter: decides el FORMATO de cada mensaje
    - logging.Formatter → texto plano con formato configurable
    - StructuredFormatter (nuestro) → JSON, el que implementamos acá

  Jerarquía de loggers:
    logging.root (root logger)
    └── "app"
        ├── "app.agents"
        │   ├── "app.agents.clinical"
        │   └── "app.agents.router"
        └── "app.services"
            └── "app.services.integrator"

  Los mensajes "burbujean" hacia arriba (propagation). Si configuramos
  el root logger, TODOS los sub-loggers heredan la configuración.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
¿QUÉ SON LOS "extra" FIELDS?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

El parámetro `extra` en logger.info() te permite inyectar campos adicionales
al LogRecord. Estos campos se convierten en atributos del record y nuestro
StructuredFormatter los incluye en el JSON de salida.

Ejemplo:
  logger.info("Agent completed", extra={"agent_name": "ClinicalAgent", "duration_ms": 1234})

Resultado JSON:
  {"timestamp": "...", "level": "INFO", "message": "Agent completed",
   "agent_name": "ClinicalAgent", "duration_ms": 1234}

Campos estándar de LogRecord (los ignoramos en extra porque ya los manejamos):
  name, levelname, pathname, lineno, funcName, process, thread, ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POR QUÉ setup_logging ES IDEMPOTENTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

El problema sin idempotencia:
  Si llamás setup_logging() dos veces (desde lifespan Y desde un test),
  el root logger acumula DOS handlers → cada log se escribe DOS veces.
  Resultado: líneas duplicadas en consola, confusión total.

La solución: verificar si ya hay handlers antes de agregar.
  if root_logger.handlers:
      return  # ya está configurado, salimos sin tocar nada

Esto permite que setup_logging sea llamado desde:
  - app/main.py lifespan (al arrancar el servidor)
  - conftest.py de tests (al correr pytest)
  - múltiples veces sin efectos secundarios

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ECOSISTEMA DE OBSERVABILIDAD — dónde encaja esto
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  App (Python) → JSON logs → stdout
                                   └── ELK Stack (Elasticsearch + Logstash + Kibana)
                                   └── AWS CloudWatch Logs
                                   └── Datadog Log Management
                                   └── Google Cloud Logging

Todos estos sistemas entienden JSON nativo. Con texto plano necesitarías
escribir parsers Grok (Logstash) o regexps para extraer los campos.
Con JSON: indexación automática, queries inmediatas, dashboards sin esfuerzo.

En este proyecto aprendemos stdlib logging + JSON format porque:
  1. Entendés los fundamentos antes de agregar librerías como loguru/structlog
  2. Los conceptos son 100% transferibles — loguru usa exactamente los mismos
  3. La stdlib está SIEMPRE disponible, sin dependencias externas
"""

import json
import logging
import datetime


# Campos del LogRecord que son "internos" de Python y NO queremos
# incluir en el JSON extra — son ruido en el output estructurado.
# Esta lista es parte del contrato de StructuredFormatter.
_BUILTIN_RECORD_FIELDS: frozenset[str] = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message",
})


class StructuredFormatter(logging.Formatter):
    """
    Formatter que serializa cada LogRecord a una línea JSON.

    ¿Qué es un Formatter?
    ─────────────────────
    En Python logging, Formatter es la clase responsable de TRANSFORMAR
    un LogRecord (objeto Python con todos los datos del evento) en un
    string listo para ser escrito por el Handler.

    La clase base logging.Formatter produce texto plano como:
      "2026-04-06 10:23:45,123 - INFO - app.agents - mensaje"

    StructuredFormatter sobreescribe format() para producir JSON en su lugar.

    ¿Por qué heredamos de logging.Formatter?
    ─────────────────────────────────────────
    Para integrarnos con el sistema de logging estándar sin cambiar cómo
    funciona el resto: el Logger sigue usando .info(), .error(), etc.
    Solo el paso final (serialización) cambia.

    Campos siempre presentes en el JSON:
      - timestamp: ISO 8601 UTC (ej: "2026-04-06T10:23:45.123456Z")
      - level:     nombre del nivel (DEBUG, INFO, WARNING, ERROR, CRITICAL)
      - logger:    nombre del logger que emitió el mensaje
      - message:   el mensaje formateado

    Campos adicionales: todo lo que el caller pasó en `extra={...}`.

    ensure_ascii=False:
    ───────────────────
    json.dumps con ensure_ascii=True (default) escapa caracteres no-ASCII:
      "ñ" → "\\u00f1"
      "á" → "\\u00e1"
    Eso rompe legibilidad de logs con contenido en español.
    ensure_ascii=False preserva los caracteres Unicode tal cual.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Convierte un LogRecord en una línea JSON.

        Flujo:
          1. Formatear el mensaje (aplica % formatting si hay args)
          2. Construir el dict base con campos estándar
          3. Agregar los campos "extra" del record
          4. Serializar a JSON
          5. Si hay excepción, agregar el traceback como campo "exc_info"

        ¿Por qué llamamos a super().format(record) primero?
        ─────────────────────────────────────────────────────
        La clase base maneja el % formatting del mensaje y prepara el
        exc_info string si hay una excepción activa. Necesitamos que eso
        ocurra antes de construir nuestro dict.
        """
        # Procesamos el mensaje base y cualquier exc_info
        super().format(record)

        # Timestamp en ISO 8601 UTC — formato estándar para sistemas de logs
        # datetime.UTC es la forma explícita y correcta en Python 3.11+
        ts = datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
        timestamp = ts.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

        log_dict: dict = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Incluir campos extra que NO son atributos internos del LogRecord
        for key, value in record.__dict__.items():
            if key not in _BUILTIN_RECORD_FIELDS:
                log_dict[key] = value

        # Si hay excepción, la incluimos como string para legibilidad
        if record.exc_text:
            log_dict["exc_info"] = record.exc_text

        return json.dumps(log_dict, ensure_ascii=False, default=str)


def setup_logging(debug: bool = False) -> None:
    """
    Configura el root logger con StructuredFormatter en un StreamHandler.

    Esta función es el PUNTO DE ENTRADA del sistema de logging.
    Se llama una sola vez en el arranque de la app (lifespan) y en conftest.py.

    ¿Por qué configurar el ROOT logger?
    ────────────────────────────────────
    El root logger es el ancestro de todos los loggers en Python.
    Al configurarlo, todos los sub-loggers (app.agents.*, app.services.*, etc.)
    heredan el handler y el formatter automáticamente — sin que cada módulo
    tenga que configurar su propio handler.

    Es el equivalente a configurar una "plantilla" global que todos usan.

    Parámetros:
        debug: si True → nivel DEBUG (ves todo, ideal para desarrollo)
               si False → nivel INFO (eventos normales, ideal para producción)

    Idempotencia:
        Si el root logger ya tiene handlers, retorna sin hacer nada.
        Esto evita handlers duplicados si setup_logging se llama múltiples veces
        (por ejemplo: una vez desde lifespan, otra desde conftest.py de tests).
    """
    root_logger = logging.getLogger()

    # Idempotencia: si ya está configurado, no agregamos handlers de nuevo
    if root_logger.handlers:
        return

    level = logging.DEBUG if debug else logging.INFO
    root_logger.setLevel(level)

    # StreamHandler escribe en stderr por defecto — estándar para logs de apps
    # En contenedores Docker, stderr se redirige a los logs del contenedor
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(StructuredFormatter())

    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Retorna un logger con el nombre dado.

    Patrón idiomático para uso en módulos:

        # Al principio del archivo, fuera de clases y funciones:
        logger = get_logger(__name__)

        # Después usás logger en cualquier función del módulo:
        logger.info("mensaje", extra={"campo": "valor"})

    ¿Por qué __name__?
    ──────────────────
    __name__ en Python es el nombre completo del módulo actual.
    En app/agents/clinical.py → __name__ == "app.agents.clinical"
    En app/services/integrator.py → __name__ == "app.services.integrator"

    Usar __name__ crea una jerarquía de loggers que refleja la estructura
    de tu paquete — exactamente la jerarquía que necesitás para filtrar
    logs por subsistema (solo logs de "app.agents.*", por ejemplo).

    Parámetros:
        name: nombre del logger — típicamente el __name__ del módulo.

    Retorna:
        logging.Logger — el logger nombrado. Si no existe, Python lo crea.
        Si ya existe, devuelve la instancia existente (los loggers son singletons
        dentro del sistema de logging).
    """
    return logging.getLogger(name)
