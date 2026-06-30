"""Batch rollup + zombie recovery.

Progress is an aggregate query, not a chord — one bad file can never wedge
the batch, and redeliveries can't double-count.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from celery import chain
from loguru import logger
from sqlalchemy import func, select
from voiceqa_shared.db_models import Recording, UploadBatch

from worker.celery_app import app
from worker.db import SessionLocal

NON_TERMINAL = ("uploaded", "converting", "transcribing", "evaluating")
STUCK_AFTER = timedelta(hours=4)
MAX_ATTEMPTS = 10


@app.task(name="voiceqa.batch.update_progress")
def update_progress(batch_id: str) -> None:
    with SessionLocal() as session:
        batch = session.get(UploadBatch, uuid.UUID(batch_id))
        if batch is None or batch.finalized_at is None or batch.status != "processing":
            return
        counts = dict(
            session.execute(
                select(Recording.status, func.count())
                .where(Recording.batch_id == uuid.UUID(batch_id))
                .group_by(Recording.status)
            ).all()
        )
        if any(counts.get(s, 0) for s in NON_TERMINAL):
            return
        batch.status = "completed_with_errors" if counts.get("failed", 0) else "completed"
        session.commit()
        logger.info("batch {} -> {} ({})", batch_id, batch.status, counts)


@app.task(name="voiceqa.batch.sweep_stuck")
def sweep_stuck() -> None:
    """Beat task: re-dispatch or fail recordings stuck in a non-terminal state."""
    from worker.tasks.pipeline import normalize_audio, transcribe

    cutoff = datetime.now(UTC) - STUCK_AFTER
    redispatched, failed = [], []
    with SessionLocal() as session:
        rows = (
            session.execute(
                select(Recording).where(
                    Recording.status.in_(NON_TERMINAL),
                    Recording.updated_at < cutoff,
                )
            )
            .scalars()
            .all()
        )
        for rec in rows:
            if rec.attempts >= MAX_ATTEMPTS:
                rec.failed_stage = {"transcribing": "stt", "evaluating": "eval"}.get(
                    rec.status, "convert"
                )
                rec.status = "failed"
                rec.error = f"stuck after {MAX_ATTEMPTS} attempts"
                failed.append((str(rec.id), str(rec.batch_id)))
            else:
                rec.attempts += 1
                redispatched.append((str(rec.id), rec.status))
        session.commit()

    for rid, status in redispatched:
        if status == "evaluating":
            from worker.tasks.evaluate import evaluate

            evaluate.delay(rid)
        elif status == "transcribing":
            transcribe.delay(rid)
        else:
            chain(normalize_audio.si(rid), transcribe.si(rid)).apply_async()
    for _rid, batch_id in failed:
        update_progress.delay(batch_id)
    if redispatched or failed:
        logger.warning("sweep_stuck: {} redispatched, {} failed", len(redispatched), len(failed))
