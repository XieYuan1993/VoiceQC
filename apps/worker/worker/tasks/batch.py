"""Batch rollup + zombie recovery.

Progress is an aggregate query, not a chord — one bad file can never wedge
the batch, and redeliveries can't double-count.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from voiceqa_shared.db_models import Recording, UploadBatch

from worker.celery_app import app
from worker.db import SessionLocal
from worker.settings import settings

NON_TERMINAL = ("uploaded", "converting", "transcribing", "evaluating")


def _timeout_for_status(status: str) -> timedelta:
    seconds = {
        "uploaded": settings.RECORDING_CONVERT_TIMEOUT_SECONDS,
        "converting": settings.RECORDING_CONVERT_TIMEOUT_SECONDS,
        "transcribing": settings.RECORDING_STT_TIMEOUT_SECONDS,
        "evaluating": settings.RECORDING_EVAL_TIMEOUT_SECONDS,
    }.get(status, settings.RECORDING_CONVERT_TIMEOUT_SECONDS)
    return timedelta(seconds=max(60, int(seconds)))


def _stage_for_status(status: str) -> str:
    return {"transcribing": "stt", "evaluating": "eval"}.get(status, "convert")


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
    """Beat task: fail recordings stuck in a non-terminal state past timeout."""
    now = datetime.now(UTC)
    failed: list[tuple[str, str, str, int]] = []
    with SessionLocal() as session:
        rows = (
            session.execute(
                select(Recording)
                .join(UploadBatch, Recording.batch_id == UploadBatch.id)
                .where(
                    Recording.status.in_(NON_TERMINAL),
                    UploadBatch.status == "processing",
                )
            )
            .scalars()
            .all()
        )
        for rec in rows:
            age = now - rec.updated_at
            timeout = _timeout_for_status(rec.status)
            if age < timeout:
                continue
            status = rec.status
            rec.failed_stage = _stage_for_status(status)
            rec.status = "failed"
            rec.error = (
                f"{status} timed out after {int(age.total_seconds() // 60)} minutes "
                f"(limit {int(timeout.total_seconds() // 60)} minutes)"
            )
            rec.stt_operation_name = None if status == "transcribing" else rec.stt_operation_name
            failed.append((str(rec.id), str(rec.batch_id), status, int(age.total_seconds())))
        session.commit()

    for _rid, batch_id in failed:
        update_progress.delay(batch_id)
    if failed:
        logger.warning("sweep_stuck: {} recording(s) failed by timeout: {}", len(failed), failed)
