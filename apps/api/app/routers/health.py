"""/api/healthz (liveness, no DB) + /api/readyz (DB + Redis)."""

from __future__ import annotations

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.settings import settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> dict:
    db_ok: bool
    try:
        result = await session.execute(text("SELECT 1"))
        db_ok = result.scalar() == 1
    except Exception:
        db_ok = False

    redis_ok: bool
    try:
        client = redis_async.from_url(settings.REDIS_URL)
        redis_ok = bool(await client.ping())
        await client.aclose()
    except Exception:
        redis_ok = False

    overall = db_ok and redis_ok
    return {"ok": overall, "db": db_ok, "redis": redis_ok}
