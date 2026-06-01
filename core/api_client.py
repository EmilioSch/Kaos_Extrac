"""
core/api_client.py — Cliente Asíncrono Híbrido (MiniMax + DeepSeek)
====================================================================
PROPÓSITO: Maneja TODAS las comunicaciones con las APIs de MiniMax y DeepSeek.
            Implementa routing inteligente entre modelos según complejidad de tarea.
            DeepSeek se usa para tareas complejas (molecular, fusión).
            MiniMax se usa para tareas simples (extracción, validación).

CONCEPTOS CLAVE:
  - Async/Await: Las llamadas a la API son asíncronas → el pipeline puede hacer
    múltiples llamadas "simultáneamente" sin bloquear la CPU local.
  - Semaphore: Limita cuántas llamadas corren en paralelo (MAX_CONCURRENT_API_CALLS).
  - Rate Limiter: Asegura respetar los límites de ambas APIs.
  - Hybrid Routing: Las tareas se enrutan al modelo apropiado según complejidad.

USO:
  from core.api_client import APIClient
  client = APIClient()
  response = await client.chat(system_prompt="...", user_message="...")
"""

import asyncio
import time
from typing import Optional
from openai import AsyncOpenAI, RateLimitError, APIError
import config
from core.logger import get_logger

log = get_logger(__name__)


class RateLimiter:
    """
    Controla la tasa de peticiones a la API.

    Usa dos mecanismos complementarios:
    1. Semaphore: Limita peticiones SIMULTÁNEAS (ej: máximo N a la vez)
    2. Intervalo mínimo: Fuerza una pausa entre el inicio de cada petición

    Args:
        max_concurrent: Número máximo de requests simultáneos
        min_interval: Segundos mínimos entre el inicio de requests
    """

    def __init__(self, max_concurrent: int, min_interval: float):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request_time: float = 0.0
        self._time_lock = asyncio.Lock()
        self._min_interval = min_interval

    async def acquire(self):
        """Espera hasta que sea seguro hacer una nueva petición."""
        await self._semaphore.acquire()
        async with self._time_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                log.debug(f"Rate limiter: esperando {wait_time:.1f}s antes de la próxima petición")
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()

    def release(self):
        """Libera el slot del semaphore al terminar una petición."""
        self._semaphore.release()


class APIClient:
    """
    Cliente híbrido para MiniMax y DeepSeek.

    routinga inteligentes entre modelos:
    - DeepSeek: Tareas complejas (molecular, fusión, análisis profundo)
    - MiniMax: Tareas simples (extracción, validación, formateo)

    Punto de entrada único para TODAS las llamadas a la API en el pipeline.
    No crear múltiples instancias; usar una sola durante toda la ejecución.
    """

    def __init__(self):
        if not config.MINIMAX_API_KEY and not config.DEEPSEEK_API_KEY:
            raise ValueError(
                "No hay API keys configuradas. "
                "Crea el archivo .env con MINIMAX_API_KEY y/o DEEPSEEK_API_KEY"
            )

        self._minimax = None
        self._deepseek = None

        if config.MINIMAX_API_KEY:
            self._minimax = AsyncOpenAI(
                api_key=config.MINIMAX_API_KEY,
                base_url=config.MINIMAX_BASE_URL,
            )
            self._minimax_limiter = RateLimiter(
                config.MAX_CONCURRENT_API_CALLS,
                config.MIN_REQUEST_INTERVAL,
            )

        if config.DEEPSEEK_API_KEY:
            self._deepseek = AsyncOpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_BASE_URL,
            )
            self._deepseek_limiter = RateLimiter(
                config.DEEPSEEK_MAX_CONCURRENT,
                config.DEEPSEEK_MIN_INTERVAL,
            )

        self._request_count: int = 0
        self.total_tokens_used: int = 0
        self._use_hybrid = config.USE_HYBRID_MODEL and config.DEEPSEEK_API_KEY

    def _should_use_deepseek(self, label: str) -> bool:
        if not self._use_hybrid:
            return False
        complex_keywords = [
            'molecular', 'fusion', 'thinking', 'clinica', 'examen',
            'analisis', 'modulo', 'sintesis', 'profundo'
        ]
        return any(kw in label.lower() for kw in complex_keywords)

    async def _call_api(
        self,
        client: AsyncOpenAI,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float,
        label: str,
        thinking: bool = False,
        reasoning_effort: str = "high",
    ) -> Optional[str]:
        """Ejecuta una llamada a la API con reintentos."""
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                extra_kwargs = {}
                if thinking and model.startswith("deepseek"):
                    extra_kwargs = {
                        "thinking": {"type": "enabled"},
                        "reasoning_effort": reasoning_effort,
                    }

                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_message},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_body=extra_kwargs if extra_kwargs else None,
                )

                message = response.choices[0].message
                content = message.content if hasattr(message, 'content') else str(message)
                # If thinking mode is enabled, reasoning might be in a separate field
                if hasattr(message, 'reasoning') and message.reasoning:
                    log.debug(f"[API] {label} — Thinking chain: {len(message.reasoning)} chars")
                
                # Strip out <think>...</think> tags if they leaked into the content string
                # DeepSeek-R1 / V4-Pro often outputs reasoning inside the content field
                import re
                if content:
                    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

                tokens_used = response.usage.total_tokens if response.usage else 0
                if isinstance(tokens_used, int) and tokens_used > 0:
                    self.total_tokens_used += tokens_used
                log.info(f"[API #{self._request_count}] {label} — ✓ Completado ({tokens_used} tokens)")
                return content, tokens_used

            except RateLimitError:
                log.warning(
                    f"[API] {label} — Error 429 (rate limit). "
                    f"Esperando {config.RETRY_DELAY_ON_RATE_LIMIT}s antes de reintentar..."
                )
                await asyncio.sleep(config.RETRY_DELAY_ON_RATE_LIMIT)

            except APIError as e:
                log.error(f"[API] {label} — Error de API (intento {attempt}/{config.MAX_RETRIES}): {e}")
                if attempt < config.MAX_RETRIES:
                    await asyncio.sleep(5 * attempt)

            except Exception as e:
                log.error(f"[API] {label} — Error inesperado: {e}")
                if attempt < config.MAX_RETRIES:
                    await asyncio.sleep(5)

        log.error(f"[API] {label} — FALLÓ después de {config.MAX_RETRIES} intentos.")
        return None, 0

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        label: str = "request",
        use_deepseek: Optional[bool] = None,
        max_tokens_override: Optional[int] = None,
        return_tokens: bool = False,
    ) -> Optional[str] | tuple[Optional[str], int]:
        """
        Envía un mensaje a la API y retorna la respuesta como texto.

        Args:
            system_prompt: Instrucciones del sistema (rol, reglas, formato).
            user_message:  El mensaje/pregunta del usuario con el contenido a analizar.
            label:         Nombre descriptivo para los logs (ej: "Murray-Extracción").
            use_deepseek:  Override para forzar DeepSeek (True) o MiniMax (False).
                          None = routing automático por etiqueta.
            return_tokens: Si es True, retorna (content, tokens_used).

        Returns:
            Texto de la respuesta del modelo, o None si falló después de MAX_RETRIES.
            Si return_tokens es True, retorna un tuple (texto, tokens).
        """
        self._request_count += 1

        if use_deepseek is None:
            use_deepseek = self._should_use_deepseek(label)

        log.info(f"[API #{self._request_count}] {label} — Enviando petición...")

        if use_deepseek and self._deepseek:
            # DeepSeek para tareas complejas
            await self._deepseek_limiter.acquire()
            try:
                result = await self._call_api(
                    client=self._deepseek,
                    model=config.DEEPSEEK_MODEL,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    max_tokens=config.DEEPSEEK_MAX_TOKENS,
                    temperature=config.DEEPSEEK_TEMPERATURE,
                    label=label,
                    thinking=True,
                    reasoning_effort="high",
                )
            finally:
                self._deepseek_limiter.release()
            return result if return_tokens else result[0]

        elif self._minimax:
            # MiniMax para tareas simples
            await self._minimax_limiter.acquire()
            try:
                result = await self._call_api(
                    client=self._minimax,
                    model=config.MINIMAX_MODEL,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    max_tokens=max_tokens_override or config.MAX_TOKENS,
                    temperature=config.TEMPERATURE,
                    label=label,
                )
            finally:
                self._minimax_limiter.release()
            return result if return_tokens else result[0]

        elif self._deepseek:
            # Fallback: usar DeepSeek si MiniMax no está disponible
            await self._deepseek_limiter.acquire()
            try:
                result = await self._call_api(
                    client=self._deepseek,
                    model=config.DEEPSEEK_MODEL,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    max_tokens=config.DEEPSEEK_MAX_TOKENS,
                    temperature=config.DEEPSEEK_TEMPERATURE,
                    label=label,
                    thinking=True,
                    reasoning_effort="high",
                )
            finally:
                self._deepseek_limiter.release()
            return result if return_tokens else result[0]

        log.error(f"[API] {label} — No hay API disponible")
        return (None, 0) if return_tokens else None

    @property
    def total_requests(self) -> int:
        """Retorna el número total de peticiones realizadas en esta sesión."""
        return self._request_count
