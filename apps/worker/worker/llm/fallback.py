"""FallbackLLM: tries a primary adapter, falls back to a secondary on connectivity failures.

Connectivity failures (timeout, unreachable, service unavailable) trigger the
fallback; API-level errors (bad request, invalid JSON, permission denied) propagate
as-is so the caller can handle them normally.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

# Errors that indicate the primary endpoint is unreachable rather than a
# caller mistake — trigger fallback on these.
_CONNECTIVITY_MARKERS = (
    "timed out",
    "ConnectTimeout",
    "ReadTimeout",
    "DeadlineExceeded",
    "UNAVAILABLE",
    "ServiceUnavailable",
    "Failed to establish a new connection",
    "Max retries exceeded",
    "Connection refused",
    "Network is unreachable",
    "Connection reset by peer",
    "RemoteDisconnected",
)


def _is_connectivity_error(exc: Exception) -> bool:
    msg = str(exc)
    return any(marker in msg for marker in _CONNECTIVITY_MARKERS)


class FallbackLLM:
    """Try `primary`; on connectivity/availability errors switch to `fallback`.

    The caller passes the primary model name (e.g. "gemini-3.5-flash") via the
    `model` kwarg.  The fallback model is fixed at construction time so it can
    differ from the primary model (e.g. "qwen3.7-max").
    """

    provider = "fallback"

    def __init__(
        self,
        primary: Any,
        fallback: Any,
        *,
        fallback_model: str,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._fallback_model = fallback_model

    def generate_structured(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.2,
    ) -> tuple[dict[str, Any], int, int]:
        try:
            return self._primary.generate_structured(
                prompt, response_schema, model=model, temperature=temperature
            )
        except Exception as e:
            if not _is_connectivity_error(e):
                raise
            logger.warning(
                "Primary LLM ({} / {}) unreachable — switching to fallback ({} / {}). "
                "Error: {}",
                self._primary.provider,
                model,
                self._fallback.provider,
                self._fallback_model,
                e,
            )
            return self._fallback.generate_structured(
                prompt,
                response_schema,
                model=self._fallback_model,
                temperature=temperature,
            )
