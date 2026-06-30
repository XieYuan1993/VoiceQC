"""Placeholder task — verifies broker/worker wiring end-to-end."""

from __future__ import annotations

from loguru import logger

from worker.celery_app import app


@app.task(name="voiceqa.ping")
def ping() -> str:
    logger.info("voiceqa.ping received")
    return "pong"
