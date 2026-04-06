"""
Retry con backoff exponencial — Resiliencia ante fallos transitorios.

¿Qué es un "fallo transitorio"?
─────────────────────────────────
Un fallo que desaparece si esperás un momento y volvés a intentar:
  - Rate limit de la API (429): espera → el límite se reinicia
  - Timeout de red (408): espera → la conexión se reestablece
  - Servicio momentáneamente no disponible (503): espera → el servicio vuelve

Vs. un fallo permanente que NO mejora con reintentos:
  - Clave API inválida (401): reintentar es inútil, siempre va a fallar
  - Datos de entrada malformados: el LLM siempre va a rechazarlos
  - Bug en tu código: reintentar no lo arregla

La clave del retry es: SOLO reintentar errores transitorios.
Por eso el parámetro retryable_exceptions filtra qué errores justifican un reintento.

¿Por qué backoff EXPONENCIAL y no lineal?
──────────────────────────────────────────
Imaginate que el servidor de Groq está bajo alta carga (muchos clientes).
Si todos los clientes que reciben un 429 reintentan al mismo segundo:

  SIN backoff:
    t=0: todos reciben 429
    t=1: todos reintentan al mismo tiempo → server más sobrecargado → todos reciben 429
    t=2: todos reintentan al mismo tiempo → loop infinito

  CON backoff exponencial:
    Intento 1: espera 1s   (base * 2^0 = 1 * 1)
    Intento 2: espera 2s   (base * 2^1 = 1 * 2)
    Intento 3: espera 4s   (base * 2^2 = 1 * 4)
    Los clientes se distribuyen en el tiempo → el servidor se recupera

Este fenómeno se llama "thundering herd problem" y el exponential backoff es
la solución estándar. AWS, GCP, Stripe — todos lo usan en sus SDKs.

¿Por qué implementarlo manualmente y no usar tenacity?
───────────────────────────────────────────────────────
1. APRENDIZAJE: entender la mecánica del retry es fundamental.
   tenacity es ~500 líneas que hacen exactamente esto — si lo entendés,
   podés usar cualquier librería de retry sin sorpresas.

2. CONTROL: esta implementación es exactamente lo que necesitamos.
   Sin features que no usamos, sin overhead, sin magia.

3. DEPENDENCIAS: menos dependencias = menos cosas que pueden fallar.

En un proyecto real con más casos de uso (jitter, dead letter queue, etc.),
usarías tenacity o stamina. Para aprender, esto es perfecto.

Uso:
    @async_retry(max_retries=3, backoff_base=1.0, retryable_exceptions=(LLMProviderError,))
    async def call_llm(prompt: str) -> str:
        ...

    # O como función wrapping:
    result = await async_retry(max_retries=3)(mi_funcion)(arg1, arg2)
"""

import asyncio
import logging
import functools
from collections.abc import Callable, Awaitable
from typing import Any, TypeVar

from app.core.exceptions import LLMProviderError

logger = logging.getLogger(__name__)

# TypeVar para preservar el tipo de retorno de la función decorada.
# Sin este TypeVar, el decorator retornaría `Any` y perdería la tipificación.
# F = TypeVar que captura la firma completa de la función async.
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def async_retry(
    max_retries: int = 3,
    backoff_base: float = 1.0,
    retryable_exceptions: tuple[type[Exception], ...] = (LLMProviderError,),
) -> Callable[[F], F]:
    """
    Decorator que reintenta funciones async ante fallos transitorios.

    ¿Cómo funciona internamente?
    ─────────────────────────────
    Es un decorator de orden superior: una función que devuelve un decorator.

    async_retry(max_retries=3)     → devuelve un decorator
    decorator(mi_funcion)          → devuelve wrapper
    wrapper(args...)               → ejecuta la lógica de retry

    Tres niveles de anidado:
      1. async_retry(...)  → configura los parámetros
      2. decorator(func)   → recibe la función a decorar
      3. wrapper(...)      → ejecuta con lógica de retry

    Parámetros:
      max_retries: número máximo de reintentos (no incluye el intento inicial)
        total de intentos = max_retries + 1
        max_retries=3 → 1 intento inicial + 3 reintentos = 4 intentos totales

      backoff_base: segundos base para el backoff exponencial
        backoff_base=1.0, intento 0 → espera 1s
        backoff_base=1.0, intento 1 → espera 2s
        backoff_base=1.0, intento 2 → espera 4s
        backoff_base=2.0, intento 0 → espera 2s
        backoff_base=2.0, intento 1 → espera 4s

      retryable_exceptions: tupla de tipos de excepción que justifican reintento.
        Si la excepción NO está en esta tupla → se propaga inmediatamente, sin reintento.
        Ejemplo: ValueError (datos inválidos) nunca debe reintentarse.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """
            Wrapper que implementa la lógica de retry.

            El loop va de 0 a max_retries (inclusive) — eso da max_retries + 1 intentos.
            En cada fallo retryable, espera backoff_base * 2^attempt segundos.
            Si el fallo NO es retryable, propaga inmediatamente.
            Si se agotan los reintentos, relanza el último error.
            """
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except retryable_exceptions as exc:
                    last_exception = exc
                    is_last_attempt = attempt == max_retries

                    if is_last_attempt:
                        # Se agotaron los reintentos — propagamos el último error.
                        # No envolvemos en otro tipo: si era LLMProviderError, sigue siendo LLMProviderError.
                        # El caller puede atraparlo y tomar decisiones.
                        logger.error(
                            "Función '%s' falló después de %d intentos. Último error: %s",
                            func.__name__,
                            max_retries + 1,
                            exc,
                        )
                        raise

                    # Calculamos el tiempo de espera con backoff exponencial.
                    # 2 ** attempt: potencia de 2 según el número de intento
                    #   attempt=0 → 2^0=1  → espera 1 * backoff_base
                    #   attempt=1 → 2^1=2  → espera 2 * backoff_base
                    #   attempt=2 → 2^2=4  → espera 4 * backoff_base
                    wait_seconds = backoff_base * (2 ** attempt)

                    logger.warning(
                        "Función '%s' falló en intento %d/%d. Reintentando en %.1fs. Error: %s",
                        func.__name__,
                        attempt + 1,
                        max_retries + 1,
                        wait_seconds,
                        exc,
                    )

                    await asyncio.sleep(wait_seconds)

                except Exception as exc:
                    # Excepción NO retryable — propagamos inmediatamente.
                    # No tiene sentido reintentar algo que no va a cambiar.
                    logger.error(
                        "Función '%s' lanzó excepción no-retryable: %s",
                        func.__name__,
                        exc,
                    )
                    raise

            # Este punto nunca se alcanza porque el loop siempre termina
            # con un `return` o un `raise`. El assert es para el type checker.
            assert last_exception is not None
            raise last_exception

        return wrapper  # type: ignore[return-value]

    return decorator
