"""
Tests de observabilidad — Fase 10: logging estructurado y callbacks LLM.

¿Qué probamos acá?
───────────────────
1. StructuredFormatter: formatea LogRecords como JSON válido con los campos
   correctos, incluyendo campos extra y caracteres especiales del español.

2. setup_logging: idempotente (no duplica handlers), respeta el nivel debug.

3. get_logger: devuelve un logger con el nombre correcto.

4. LoggingCallbackHandler: registra llamadas LLM (start, end, error) y
   mantiene correctamente el estado interno de _start_times.

Herramientas de testing usadas:
────────────────────────────────
- caplog: fixture de pytest que captura LogRecords emitidos durante el test.
  Permite verificar que ciertos mensajes fueron logueados con cierto nivel.

- logging.LogRecord: clase de Python para construir records manuales,
  útil para testear el Formatter directamente sin usar un Logger.

- json.loads(): parseamos el output del Formatter para verificar el JSON.

¿Por qué caplog y no mock?
──────────────────────────
Mock intercepta las llamadas a funciones antes de que ocurran.
caplog captura los registros DESPUÉS de que el sistema de logging los procesa.
Para testear si "se logueó algo", caplog es la herramienta correcta.
Para testear "se llamó a X con Y argumentos", mock es la herramienta correcta.

En este módulo necesitamos ambas:
  - caplog para verificar que los mensajes llegan al logger
  - Instanciación directa de StructuredFormatter para testear el JSON output
"""

import json
import logging
import uuid
from unittest.mock import MagicMock

import pytest

from app.core.logging import StructuredFormatter, get_logger, setup_logging
from app.core.callbacks import LoggingCallbackHandler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_log_record(
    name: str = "test.logger",
    level: int = logging.INFO,
    msg: str = "mensaje de prueba",
    extra: dict | None = None,
) -> logging.LogRecord:
    """
    Construye un LogRecord con los valores dados.

    ¿Por qué construir LogRecord directamente?
    ───────────────────────────────────────────
    Para testear StructuredFormatter.format() necesitamos un LogRecord.
    Podríamos loguear a través de un Logger real, pero eso introduce
    dependencia en el sistema de logging global.

    Construir el record directamente nos da control total sobre sus campos
    y no depende del estado de handlers configurados.

    El parámetro extra se asigna manualmente porque LogRecord.__init__
    no acepta extra directamente — es un atributo que el Logger agrega
    DESPUÉS de crear el record. Lo replicamos manualmente.
    """
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test_logging.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if extra:
        for key, value in extra.items():
            setattr(record, key, value)
    return record


# ─── Tests: StructuredFormatter ────────────────────────────────────────────────

def test_structured_formatter_outputs_json():
    """
    StructuredFormatter produce una línea JSON válida y parseable.

    Verificamos que:
      1. El output es JSON parseado sin error (json.loads no lanza)
      2. Los campos obligatorios están presentes
      3. El nivel y el mensaje coinciden con el record original
    """
    formatter = StructuredFormatter()
    record = make_log_record(msg="evento de prueba", level=logging.INFO)

    output = formatter.format(record)

    # Debe ser JSON válido
    parsed = json.loads(output)

    # Campos obligatorios siempre presentes
    assert "timestamp" in parsed
    assert "level" in parsed
    assert "logger" in parsed
    assert "message" in parsed

    # Valores correctos
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "evento de prueba"
    assert parsed["logger"] == "test.logger"


def test_structured_formatter_includes_extra():
    """
    Los campos extra pasados al log aparecen en el JSON de salida.

    Verificamos que extra={"agent_name": "ClinicalAgent", "duration_ms": 123}
    se convierte en campos de primer nivel en el JSON — no anidados ni perdidos.

    Esto es crítico para que ELK/Datadog pueda indexar los campos extra.
    """
    formatter = StructuredFormatter()
    extra = {"agent_name": "ClinicalAgent", "duration_ms": 123, "confidence": 0.87}
    record = make_log_record(extra=extra)

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["agent_name"] == "ClinicalAgent"
    assert parsed["duration_ms"] == 123
    assert parsed["confidence"] == 0.87


def test_structured_formatter_handles_spanish_characters():
    """
    El formatter preserva caracteres especiales del español (ñ, á, é, etc.).

    json.dumps con ensure_ascii=True (default) escapa estos caracteres:
      "ñ" → "\\u00f1"
    Con ensure_ascii=False se preservan tal cual en el JSON.

    Esto importa porque logs con contenido clínico van a tener nombres de
    pacientes, síntomas y diagnósticos en español — no deben quedar ilegibles.
    """
    formatter = StructuredFormatter()
    record = make_log_record(msg="paciente con fiebre y ñoño diagnóstico")

    output = formatter.format(record)
    parsed = json.loads(output)

    # Los caracteres especiales deben sobrevivir el round-trip
    assert "ñ" in parsed["message"]
    assert "ó" in parsed["message"]
    # El output raw tampoco debe tener escapes unicode innecesarios
    assert "\\u00f1" not in output


def test_structured_formatter_timestamp_is_iso8601():
    """
    El timestamp del JSON sigue el formato ISO 8601 UTC.

    Formato esperado: "2026-04-06T10:23:45.123456Z"
    - 'T' separa fecha y hora (estándar ISO 8601)
    - 'Z' indica UTC
    - Sin offset timezone (+00:00) para mantener el formato simple

    Los sistemas de observabilidad (ELK, Datadog) reconocen este formato
    automáticamente para indexar y ordenar eventos por tiempo.
    """
    formatter = StructuredFormatter()
    record = make_log_record()

    output = formatter.format(record)
    parsed = json.loads(output)

    timestamp = parsed["timestamp"]
    assert "T" in timestamp
    assert timestamp.endswith("Z")
    # Formato básico: YYYY-MM-DDTHH:MM:SS...Z (al menos 20 chars)
    assert len(timestamp) > 20


# ─── Tests: setup_logging ──────────────────────────────────────────────────────

def test_setup_logging_is_idempotent():
    """
    Llamar setup_logging() dos veces no duplica los handlers.

    El problema sin idempotencia: si setup_logging se llama desde lifespan
    Y desde conftest.py, el root logger tendría DOS handlers → duplicados.

    La solución: si ya hay handlers, retornar inmediatamente.
    Este test verifica que el número de handlers no crece con múltiples llamadas.
    """
    root = logging.getLogger()
    # Limpiamos primero para tener estado controlado
    original_handlers = root.handlers[:]
    root.handlers.clear()

    try:
        setup_logging()
        count_after_first = len(root.handlers)

        setup_logging()
        count_after_second = len(root.handlers)

        # La segunda llamada NO debe agregar handlers
        assert count_after_first == count_after_second
        assert count_after_first == 1  # exactamente un handler
    finally:
        # Restauramos el estado original para no romper otros tests
        root.handlers.clear()
        root.handlers.extend(original_handlers)


def test_setup_logging_respects_debug_level():
    """
    debug=True configura nivel DEBUG, debug=False configura nivel INFO.

    Esto permite tener logs verbosos en desarrollo y solo eventos importantes
    en producción — sin cambiar código, solo cambiando la configuración.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    root.handlers.clear()

    try:
        setup_logging(debug=True)
        assert root.level == logging.DEBUG

        root.handlers.clear()
        setup_logging(debug=False)
        assert root.level == logging.INFO
    finally:
        root.handlers.clear()
        root.handlers.extend(original_handlers)
        root.setLevel(original_level)


def test_get_logger_returns_named_logger():
    """
    get_logger("mi.modulo") devuelve un logger con el nombre correcto.

    ¿Por qué importa el nombre?
    ───────────────────────────
    El nombre del logger aparece en el JSON ("logger": "app.agents.clinical").
    Permite filtrar logs por subsistema en herramientas de observabilidad.
    Si el nombre estuviera mal, los filtros no funcionarían.
    """
    logger = get_logger("app.agents.test")
    assert logger.name == "app.agents.test"


def test_get_logger_same_name_returns_same_instance():
    """
    Dos llamadas a get_logger con el mismo nombre devuelven el MISMO objeto.

    Los loggers en Python son singletons por nombre — logging.getLogger(name)
    siempre devuelve la misma instancia para el mismo name.
    Esto es importante para no tener instancias duplicadas consumiendo memoria.
    """
    logger_a = get_logger("app.test.singleton")
    logger_b = get_logger("app.test.singleton")
    assert logger_a is logger_b


# ─── Tests: LoggingCallbackHandler ─────────────────────────────────────────────

def test_logging_callback_handler_on_llm_start(caplog):
    """
    on_llm_start guarda el tiempo de inicio y logúea el evento.

    Verificamos dos comportamientos:
      1. El run_id se agrega a _start_times (estado interno correcto)
      2. Se logúea "LLM call started" con los campos extra esperados

    caplog captura los LogRecords emitidos por cualquier logger durante
    la ejecución del test. with caplog.at_level(logging.INFO) asegura
    que los mensajes INFO sean capturados (por defecto caplog puede
    filtrar según el nivel configurado del logger).
    """
    handler = LoggingCallbackHandler()
    run_id = uuid.uuid4()

    with caplog.at_level(logging.INFO):
        handler.on_llm_start(
            serialized={"name": "ChatGroq"},
            prompts=["prompt 1", "prompt 2"],
            run_id=run_id,
        )

    # El tiempo de inicio fue guardado
    assert run_id in handler._start_times

    # Se logúeó el mensaje correcto
    assert any("LLM call started" in r.message for r in caplog.records)


def test_logging_callback_handler_on_llm_end_logs_duration(caplog):
    """
    on_llm_end calcula la duración y logúea el evento de finalización.

    El flujo esperado:
      1. on_llm_start → guarda start_time en _start_times[run_id]
      2. on_llm_end → calcula duration = now - start_time, logúea, elimina del dict

    Verificamos que:
      - El mensaje "LLM call completed" aparece en los logs
      - El run_id se elimina de _start_times después del end
    """
    handler = LoggingCallbackHandler()
    run_id = uuid.uuid4()

    # Primero simulamos el start para que haya un tiempo guardado
    with caplog.at_level(logging.INFO):
        handler.on_llm_start(
            serialized={},
            prompts=["prompt"],
            run_id=run_id,
        )
        # Creamos un LLMResult mock
        mock_response = MagicMock()
        handler.on_llm_end(
            response=mock_response,
            run_id=run_id,
        )

    # El mensaje de completado fue logueado
    assert any("LLM call completed" in r.message for r in caplog.records)

    # El run_id fue eliminado del dict de tiempos
    assert run_id not in handler._start_times


def test_logging_callback_handler_on_llm_error_logs_error(caplog):
    """
    on_llm_error logúea el error con nivel ERROR.

    Verificamos:
      - El mensaje "LLM call failed" aparece en los logs
      - El nivel del log es ERROR (no WARNING ni INFO)
    """
    handler = LoggingCallbackHandler()
    run_id = uuid.uuid4()
    error = RuntimeError("timeout de API")

    with caplog.at_level(logging.ERROR):
        handler.on_llm_error(
            error=error,
            run_id=run_id,
        )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("LLM call failed" in r.message for r in error_records)


def test_logging_callback_handler_cleans_up_on_error():
    """
    on_llm_error elimina el run_id de _start_times — sin memory leaks.

    Si on_llm_error no limpiara _start_times, cada llamada fallida
    acumularía una entrada que nunca se eliminaría.
    En un sistema con millones de llamadas, eso sería un memory leak real.

    Verificamos que después del error, _start_times queda vacío.
    """
    handler = LoggingCallbackHandler()
    run_id = uuid.uuid4()

    # Agregamos manualmente el tiempo de inicio (como haría on_llm_start)
    import time
    handler._start_times[run_id] = time.perf_counter()

    # Ahora simulamos el error
    handler.on_llm_error(
        error=ValueError("error de prueba"),
        run_id=run_id,
    )

    # El estado interno debe estar limpio
    assert run_id not in handler._start_times
    assert len(handler._start_times) == 0


def test_logging_callback_handler_on_llm_end_without_prior_start(caplog):
    """
    on_llm_end funciona incluso sin un on_llm_start previo (defensive coding).

    En condiciones normales siempre hay un start antes del end.
    Pero si por un bug del sistema el end llega sin start, no debe explotar.
    .pop(run_id, None) maneja este caso — devuelve None si la clave no existe.

    Verificamos que no se lanza KeyError y el log se escribe igual.
    """
    handler = LoggingCallbackHandler()
    run_id = uuid.uuid4()
    mock_response = MagicMock()

    # No llamamos on_llm_start — llamamos on_llm_end directamente
    with caplog.at_level(logging.INFO):
        # No debe lanzar KeyError
        handler.on_llm_end(response=mock_response, run_id=run_id)

    # El mensaje de completado fue logueado igual
    assert any("LLM call completed" in r.message for r in caplog.records)


def test_logging_callback_handler_tracks_multiple_concurrent_runs():
    """
    El handler rastrea múltiples runs concurrentes correctamente.

    En asyncio.gather con 3 agentes en paralelo, se disparan 3 on_llm_start
    antes de que llegue cualquier on_llm_end. El handler debe mantener
    todos los tiempos de inicio correctamente.

    Verificamos que _start_times puede contener múltiples run_ids simultáneos.
    """
    import time

    handler = LoggingCallbackHandler()
    run_ids = [uuid.uuid4() for _ in range(3)]

    # Simulamos 3 starts concurrentes
    for run_id in run_ids:
        handler.on_llm_start(
            serialized={},
            prompts=["prompt"],
            run_id=run_id,
        )

    # Los 3 deben estar en _start_times
    assert len(handler._start_times) == 3
    for run_id in run_ids:
        assert run_id in handler._start_times

    # Al finalizar uno, los otros deben seguir
    mock_response = MagicMock()
    handler.on_llm_end(response=mock_response, run_id=run_ids[0])

    assert run_ids[0] not in handler._start_times
    assert run_ids[1] in handler._start_times
    assert run_ids[2] in handler._start_times
