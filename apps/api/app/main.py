"""FastAPI app entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.db import engine
from app.ratelimit import limiter, rate_limit_handler
from app.routers import (
    admin,
    admin_sso,
    admin_users,
    asr_audio,
    auth,
    batches,
    checklist,
    config,
    criteria,
    evaluations,
    fields,
    health,
    insights,
    kb,
    me,
    projects,
    recon,
    recordings,
    terms,
    transactions,
)
from app.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api starting; database={}", settings.DATABASE_URL.split("@")[-1])
    yield
    await engine.dispose()
    logger.info("api stopped")


app = FastAPI(
    title="VoiceQA API",
    version="0.0.1",
    description="Call quality & compliance platform — Phase 0 (foundations).",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Rate limiting: a default cap on every route + per-route overrides
# (5/min on auth, declared in auth.py). Keyed by client IP.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(projects.router)
app.include_router(auth.router)
app.include_router(asr_audio.router)
app.include_router(batches.router)
app.include_router(recordings.router)
app.include_router(terms.router)
app.include_router(config.router)
app.include_router(criteria.router)
app.include_router(fields.router)
app.include_router(checklist.router)
app.include_router(evaluations.router)
app.include_router(insights.router)
app.include_router(kb.router)
app.include_router(transactions.router)
app.include_router(recon.router)
app.include_router(admin_sso.router)
app.include_router(admin_users.router)
app.include_router(admin.router)
