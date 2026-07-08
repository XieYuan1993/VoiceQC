"""Rate limiting (slowapi), keyed by client IP, backed by Redis so the limit
holds across multiple API workers in production.

- Global default cap on every route (generous — this is an internal tool).
- Tight per-route caps on the browser-facing password-reset endpoints
  (declared in auth.py); credential verification is server-to-server (one IP
  for all users) so it relies on per-account lockout instead, not IP limits.
- The batch file-upload route is exempt (a day's batch is hundreds of calls);
  it is bounded by per-file size caps instead.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.settings import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300/minute"],
    storage_uri=settings.REDIS_URL,
    strategy="fixed-window",
    swallow_errors=True,
    in_memory_fallback=["300/minute"],
    in_memory_fallback_enabled=True,
)


def rate_limit_handler(request: Request, exc) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded; slow down and retry shortly"},
    )
