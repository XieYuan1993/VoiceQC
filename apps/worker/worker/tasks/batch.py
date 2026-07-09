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
from voiceqa_shared.db_models import Evaluation, Recording, UploadBatch

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


def _resume_after() -> timedelta:
    return timedelta(seconds=max(60, int(settings.RECORDING_RESUME_STALE_SECONDS)))


def _max_resume_attempts() -> int:
    return max(0, int(settings.RECORDING_RESUME_MAX_ATTEMPTS))


def _stage_for_status(status: str) -> str:
    return {"transcribing": "stt", "evaluating": "eval"}.get(status, "convert")


def _stage_has_started(session, rec: Recording) -> bool:
    if rec.status == "transcribing":
        return bool(rec.stt_operation_name)
    if rec.status == "evaluating":
        return (
            session.execute(
                select(Evaluation.id)
                .where(Evaluation.recording_id == rec.id, Evaluation.status == "running")
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )
    return True


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
    """Beat task: resume stale recordings, then fail them if they exceed timeout."""
    from worker.tasks.pipeline import normalize_audio, transcribe

    now = datetime.now(UTC)
    failed: list[tuple[str, str, str, int]] = []
    redispatched: list[tuple[str, str]] = []
    queued_redispatched: list[tuple[str, str]] = []
    resume_after = _resume_after()
    max_resume_attempts = _max_resume_attempts()
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
            stage_started = _stage_has_started(session, rec)
            if not stage_started:
                if age >= timeout:
                    status = rec.status
                    rec.updated_at = now
                    rec.error = None
                    rec.failed_stage = None
                    queued_redispatched.append((str(rec.id), status))
                continue

            timed_out = age >= timeout
            stale_exhausted = age >= resume_after and rec.attempts >= max_resume_attempts
            if timed_out or stale_exhausted:
                status = rec.status
                rec.failed_stage = _stage_for_status(status)
                rec.status = "failed"
                reason = (
                    f"timed out after {int(age.total_seconds() // 60)} minutes "
                    f"(limit {int(timeout.total_seconds() // 60)} minutes)"
                    if timed_out
                    else f"stale after {rec.attempts} recovery attempts"
                )
                rec.error = f"{status} {reason}"
                rec.stt_operation_name = None if status == "transcribing" else rec.stt_operation_name
                if status == "evaluating":
                    for ev in session.execute(
                        select(Evaluation).where(
                            Evaluation.recording_id == rec.id,
                            Evaluation.status == "running",
                        )
                    ).scalars():
                        ev.status = "failed"
                        ev.error = rec.error
                failed.append((str(rec.id), str(rec.batch_id), status, int(age.total_seconds())))
                continue

            if age >= resume_after:
                status = rec.status
                rec.updated_at = now
                rec.error = None
                rec.failed_stage = None
                rec.attempts += 1
                redispatched.append((str(rec.id), status))
        session.commit()

    for rid, status in [*queued_redispatched, *redispatched]:
        if status == "evaluating":
            from worker.tasks.evaluate import evaluate

            evaluate.delay(rid)
        elif status == "transcribing":
            transcribe.delay(rid)
        else:
            chain(normalize_audio.si(rid), transcribe.si(rid)).apply_async()
    for _rid, batch_id, _status, _age_seconds in failed:
        update_progress.delay(batch_id)
    if queued_redispatched or redispatched or failed:
        logger.warning(
            "sweep_stuck: {} queued redispatched, {} running redispatched, {} failed",
            len(queued_redispatched),
            len(redispatched),
            len(failed),
        )
