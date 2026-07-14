"""Recordings: list/detail/transcript/audio/reprocess.

Row-level scoping: the `broker` role sees only recordings whose broker_ext
maps (via user_broker_codes -> brokers.phone_extensions) to one of their AE
codes. Everyone else needs recordings:read_all. Audio playback and
transcript reads are audited — this is client PII.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import Select, and_, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared import gcs
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import (
    Broker,
    Evaluation,
    Recording,
    Transcript,
    TranscriptSegment,
    UploadBatch,
    User,
    UserBrokerCode,
)

from app import queue
from app.db import get_session
from app.deps import ClientMeta, client_meta, current_user, resolve_project_id
from app.permissions import (
    BATCHES_MANAGE,
    EVALS_REVIEW,
    RECORDINGS_READ_ALL,
    RECORDINGS_READ_OWN,
    TRANSCRIPTS_READ,
    has_perm,
    require,
)
from app.schemas import (
    BulkRerunOut,
    RecordingDetail,
    RecordingListOut,
    RecordingOut,
    RecordingReevaluateIn,
    SegmentOut,
    TranscriptOut,
)

router = APIRouter(prefix="/api/recordings", tags=["recordings"])

HK = ZoneInfo("Asia/Hong_Kong")

_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}


async def _scope_extensions(session: AsyncSession, user: User) -> set[str] | None:
    """None = unrestricted; set of recorder extensions for the broker role."""
    if has_perm(user.role, RECORDINGS_READ_ALL):
        return None
    if not has_perm(user.role, RECORDINGS_READ_OWN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no recordings access")
    rows = (
        await session.execute(
            select(Broker.phone_extensions)
            .join(UserBrokerCode, UserBrokerCode.broker_code == Broker.code)
            .where(UserBrokerCode.user_id == user.id)
        )
    ).scalars().all()
    return {ext for extensions in rows for ext in extensions}


def _apply_scope(stmt: Select, extensions: set[str] | None) -> Select:
    if extensions is None:
        return stmt
    if not extensions:
        return stmt.where(False)  # broker with no mapped AE codes sees nothing
    return stmt.where(Recording.broker_ext.in_(extensions))


def _attention_ids() -> Select:
    """Recording ids whose LATEST completed eval signals a review need: a
    complaint, an answer the KB contradicts, a critical risk flag, or weak
    script adherence."""
    latest = (
        select(
            Evaluation.recording_id.label("rid"),
            func.max(Evaluation.run_seq).label("seq"),
        )
        .where(Evaluation.status == "completed")
        .group_by(Evaluation.recording_id)
        .subquery()
    )
    return (
        select(Evaluation.recording_id)
        .join(
            latest,
            and_(Evaluation.recording_id == latest.c.rid, Evaluation.run_seq == latest.c.seq),
        )
        .where(
            or_(
                Evaluation.is_complaint.is_(True),
                Evaluation.checklist_score < 50,
                Evaluation.correctness_findings.op("@>")(cast('[{"verdict": "incorrect"}]', JSONB)),
                Evaluation.risk_flags.op("@>")(cast('[{"severity": "critical"}]', JSONB)),
            )
        )
    )


def _out(rec: Recording, has_transcript: bool, overall_score: float | None = None) -> RecordingOut:
    return RecordingOut(
        id=rec.id,
        batch_id=rec.batch_id,
        original_filename=rec.original_filename,
        status=rec.status,
        failed_stage=rec.failed_stage,
        error=rec.error,
        duration_seconds=float(rec.duration_seconds) if rec.duration_seconds is not None else None,
        broker_ext=rec.broker_ext,
        broker_name=rec.broker_name,
        caller_number=rec.caller_number,
        client_name=rec.client_name,
        client_account=rec.client_account,
        direction=rec.direction,
        call_started_at=rec.call_started_at,
        language_mode=rec.language_mode,
        has_transcript=has_transcript,
        overall_score=overall_score,
        created_at=rec.created_at,
    )


def _latest_eval_ids() -> Select:
    """Map each recording to the run_seq of its latest completed evaluation."""
    return (
        select(
            Evaluation.recording_id.label("rid"),
            func.max(Evaluation.run_seq).label("seq"),
        )
        .where(Evaluation.status == "completed")
        .group_by(Evaluation.recording_id)
    )


async def _latest_scores(
    session: AsyncSession, rec_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """overall_score from each recording's latest completed eval, for a page of rows."""
    if not rec_ids:
        return {}
    latest = _latest_eval_ids().where(Evaluation.recording_id.in_(rec_ids)).subquery()
    rows = (
        await session.execute(
            select(Evaluation.recording_id, Evaluation.overall_score).join(
                latest,
                and_(Evaluation.recording_id == latest.c.rid, Evaluation.run_seq == latest.c.seq),
            )
        )
    ).all()
    return {rid: float(s) for rid, s in rows if s is not None}


def _score_filtered_ids(min_score: float | None, max_score: float | None) -> Select:
    """Recording ids whose latest completed eval overall_score is in [min, max]."""
    latest = _latest_eval_ids().subquery()
    stmt = (
        select(Evaluation.recording_id)
        .join(
            latest,
            and_(Evaluation.recording_id == latest.c.rid, Evaluation.run_seq == latest.c.seq),
        )
        .where(Evaluation.overall_score.is_not(None))
    )
    if min_score is not None:
        stmt = stmt.where(Evaluation.overall_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(Evaluation.overall_score <= max_score)
    return stmt


@router.get("", response_model=RecordingListOut)
async def list_recordings(
    batch_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    broker_ext: str | None = None,
    call_date: date | None = None,
    q: str | None = Query(default=None, max_length=200),
    attention: bool = False,
    min_score: float | None = Query(default=None, ge=0, le=100),
    max_score: float | None = Query(default=None, ge=0, le=100),
    page: int = 1,
    page_size: int = 25,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordingListOut:
    extensions = await _scope_extensions(session, user)
    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    stmt = _apply_scope(select(Recording), extensions).where(Recording.project_id == project_id)
    if batch_id is not None:
        stmt = stmt.where(Recording.batch_id == batch_id)
    if status_filter:
        stmt = stmt.where(Recording.status == status_filter)
    if broker_ext:
        stmt = stmt.where(Recording.broker_ext == broker_ext)
    if call_date is not None:
        # The trade day is a Hong Kong calendar day.
        start = datetime.combine(call_date, time.min, tzinfo=HK)
        stmt = stmt.where(
            Recording.call_started_at >= start,
            Recording.call_started_at < start + timedelta(days=1),
        )
    if min_score is not None or max_score is not None:
        stmt = stmt.where(Recording.id.in_(_score_filtered_ids(min_score, max_score)))
    if q:
        transcript_match = exists(
            select(Transcript.id).where(
                Transcript.recording_id == Recording.id,
                Transcript.full_text.ilike(f"%{q}%"),
            )
        )
        stmt = stmt.where(or_(Recording.original_filename.ilike(f"%{q}%"), transcript_match))
    if attention:
        stmt = stmt.where(Recording.id.in_(_attention_ids()))

    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(
                    Recording.call_started_at.desc().nulls_last(),
                    Recording.created_at.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    with_transcript = set(
        (
            await session.execute(
                select(Transcript.recording_id).where(
                    Transcript.recording_id.in_([r.id for r in rows])
                )
            )
        )
        .scalars()
        .all()
    ) if rows else set()
    scores = await _latest_scores(session, [r.id for r in rows])
    return RecordingListOut(
        items=[_out(r, r.id in with_transcript, scores.get(r.id)) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/reevaluate", response_model=BulkRerunOut)
async def reevaluate_recordings(
    payload: RecordingReevaluateIn | None = Body(default=None),
    batch_id: uuid.UUID | None = None,
    attention: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(EVALS_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> BulkRerunOut:
    """Re-evaluate transcribed recordings under the current config.

    Scope can be the whole project, one batch, the attention set, or an explicit
    list of recording ids. Active pipeline rows stay untouched.
    """
    extensions = await _scope_extensions(session, user)
    recording_ids = payload.recording_ids if payload is not None else []
    stmt = _apply_scope(select(Recording), extensions).where(
        Recording.project_id == project_id,
        Recording.status.not_in(("uploaded", "converting", "transcribing", "evaluating")),
    )
    if recording_ids:
        stmt = stmt.where(Recording.id.in_(recording_ids))
    if batch_id is not None:
        stmt = stmt.where(Recording.batch_id == batch_id)
    if attention:
        stmt = stmt.where(Recording.id.in_(_attention_ids()))
    recs = (await session.execute(stmt)).scalars().all()
    with_t = (
        set(
            (
                await session.execute(
                    select(Transcript.recording_id).where(
                        Transcript.recording_id.in_([r.id for r in recs])
                    )
                )
            ).scalars().all()
        )
        if recs
        else set()
    )

    to_enqueue: list[str] = []
    batch_ids: set[uuid.UUID] = set()
    for r in recs:
        if r.id not in with_t:
            continue
        r.status = "evaluating"
        r.failed_stage = None
        r.error = None
        r.attempts = 0
        batch_ids.add(r.batch_id)
        to_enqueue.append(str(r.id))
    for bid in batch_ids:
        b = await session.get(UploadBatch, bid)
        if b is not None and b.status in ("completed", "completed_with_errors", "failed"):
            b.status = "processing"
    log_audit(
        session, action="evaluation.rerun_bulk", user_id=user.id, actor_email=user.email,
        object_type="project", object_id=str(project_id),
        details={
            "queued": len(to_enqueue),
            "batch_id": str(batch_id) if batch_id is not None else None,
            "recording_ids": len(recording_ids),
            "attention": attention,
        }, ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    for rid in to_enqueue:
        queue.send_pipeline_chain(rid, from_stage="eval")
    return BulkRerunOut(queued=len(to_enqueue))


@router.get("/export")
async def export_recordings(
    batch_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    attention: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Export the scoped + filtered recordings with their latest-run QA scores as CSV."""
    extensions = await _scope_extensions(session, user)
    latest = (
        select(
            Evaluation.recording_id.label("rid"),
            func.max(Evaluation.run_seq).label("seq"),
        )
        .where(Evaluation.status == "completed")
        .group_by(Evaluation.recording_id)
        .subquery()
    )
    stmt = (
        _apply_scope(
            select(
                Recording,
                Evaluation.overall_score,
                Evaluation.checklist_score,
                Evaluation.correctness_score,
                Evaluation.sentiment_label,
                Evaluation.customer_intent,
                Evaluation.is_complaint,
                Evaluation.review_status,
            ),
            extensions,
        )
        .outerjoin(latest, latest.c.rid == Recording.id)
        .outerjoin(
            Evaluation,
            and_(Evaluation.recording_id == latest.c.rid, Evaluation.run_seq == latest.c.seq),
        )
        .where(Recording.project_id == project_id)
    )
    if batch_id is not None:
        stmt = stmt.where(Recording.batch_id == batch_id)
    if status_filter:
        stmt = stmt.where(Recording.status == status_filter)
    if attention:
        stmt = stmt.where(Recording.id.in_(_attention_ids()))
    if q:
        stmt = stmt.where(Recording.original_filename.ilike(f"%{q}%"))
    stmt = stmt.order_by(
        Recording.call_started_at.desc().nulls_last(), Recording.created_at.desc()
    ).limit(10000)
    rows = (await session.execute(stmt)).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "filename", "agent", "direction", "call_time", "duration_s", "status",
        "overall_score", "adherence_pct", "correctness_pct", "sentiment", "intent",
        "complaint", "review_status",
    ])
    for rec, score, adh, corr, sentiment, intent, is_comp, review in rows:
        w.writerow([
            rec.original_filename,
            rec.broker_ext or "",
            rec.direction,
            rec.call_started_at.isoformat() if rec.call_started_at else "",
            float(rec.duration_seconds) if rec.duration_seconds is not None else "",
            rec.status,
            float(score) if score is not None else "",
            float(adh) if adh is not None else "",
            float(corr) if corr is not None else "",
            sentiment or "",
            intent or "",
            ("yes" if is_comp else "no") if is_comp is not None else "",
            review or "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=recordings.csv"},
    )


async def _get_scoped(
    session: AsyncSession, user: User, recording_id: uuid.UUID
) -> Recording:
    extensions = await _scope_extensions(session, user)
    rec = await session.get(Recording, recording_id)
    if rec is None or (extensions is not None and rec.broker_ext not in extensions):
        # 404, not 403 — don't leak existence to out-of-scope brokers.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recording not found")
    return rec


@router.get("/{recording_id}", response_model=RecordingDetail)
async def get_recording(
    recording_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordingDetail:
    rec = await _get_scoped(session, user, recording_id)
    has_transcript = (
        await session.execute(
            select(Transcript.id).where(Transcript.recording_id == rec.id)
        )
    ).scalar_one_or_none() is not None
    scores = await _latest_scores(session, [rec.id])
    base = _out(rec, has_transcript, scores.get(rec.id))
    return RecordingDetail(
        **base.model_dump(),
        sha256=rec.sha256,
        size_bytes=rec.size_bytes,
        sample_rate=rec.sample_rate,
        channels=rec.channels,
        format=rec.format,
    )


@router.get("/{recording_id}/transcript", response_model=TranscriptOut)
async def get_transcript(
    recording_id: uuid.UUID,
    user: User = Depends(require(TRANSCRIPTS_READ)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> TranscriptOut:
    rec = await _get_scoped(session, user, recording_id)
    transcript = (
        await session.execute(select(Transcript).where(Transcript.recording_id == rec.id))
    ).scalar_one_or_none()
    if transcript is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no transcript yet")
    segments = (
        (
            await session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == transcript.id)
                .order_by(TranscriptSegment.start_ms)
            )
        )
        .scalars()
        .all()
    )
    log_audit(
        session, action="transcript.view", user_id=user.id, actor_email=user.email,
        object_type="recording", object_id=str(rec.id), ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return TranscriptOut(
        recording_id=rec.id,
        stt_model=transcript.stt_model,
        language_detected=transcript.language_detected,
        billed_seconds=float(transcript.billed_seconds)
        if transcript.billed_seconds is not None
        else None,
        full_text=transcript.full_text,
        segments=[
            SegmentOut(
                channel_role=s.channel_role,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                text=s.text,
                language=s.language,
                confidence=s.confidence,
            )
            for s in segments
        ],
    )


_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


@router.get("/{recording_id}/audio")
async def get_audio(
    recording_id: uuid.UUID,
    range_header: str | None = Header(default=None, alias="Range"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    """Stream the raw audio through the API (with HTTP Range for seeking).

    Streaming — rather than redirecting to a GCS signed URL — keeps playback
    on the same CORS+credentials path as every other API call, so the browser
    <audio> element loads it; a cross-origin redirect to GCS fails credentialed
    CORS. (Signed-URL offload would require a separate fetch-then-set-src flow.)
    """
    rec = await _get_scoped(session, user, recording_id)
    if not rec.gcs_uri_raw:
        raise HTTPException(status.HTTP_410_GONE, "audio purged by retention policy")
    log_audit(
        session, action="recording.play_audio", user_id=user.id, actor_email=user.email,
        object_type="recording", object_id=str(rec.id), ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()

    media_type = _MEDIA_TYPES.get(Path(rec.original_filename).suffix.lower(), "application/octet-stream")
    total = await run_in_threadpool(gcs.object_size, rec.gcs_uri_raw)

    m = _RANGE_RE.match(range_header or "")
    if m:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else total - 1
        end = min(end, total - 1)
        if start > end:
            raise HTTPException(
                status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, "invalid range",
                headers={"Content-Range": f"bytes */{total}"},
            )
        chunk = await run_in_threadpool(gcs.read_uri_range, rec.gcs_uri_raw, start, end)
        return Response(
            chunk,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
            },
        )

    data = await run_in_threadpool(gcs.read_uri_bytes, rec.gcs_uri_raw)
    return Response(
        data,
        media_type=media_type,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(total)},
    )


@router.post("/{recording_id}/reprocess", response_model=RecordingOut)
async def reprocess(
    recording_id: uuid.UUID,
    from_stage: str = Query(default="convert", pattern="^(convert|stt|eval)$"),
    user: User = Depends(require(BATCHES_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> RecordingOut:
    rec = await _get_scoped(session, user, recording_id)
    if rec.status in ("converting", "transcribing", "evaluating"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"recording is busy ({rec.status})")
    if from_stage == "stt" and not (rec.gcs_uri_broker or rec.gcs_uri_mono):
        raise HTTPException(status.HTTP_409_CONFLICT, "no normalized audio; reprocess from convert")
    if from_stage == "eval":
        has_transcript = (
            await session.execute(select(Transcript.id).where(Transcript.recording_id == rec.id))
        ).scalar_one_or_none() is not None
        if not has_transcript:
            raise HTTPException(status.HTTP_409_CONFLICT, "no transcript; reprocess from stt")

    rec.error = None
    rec.failed_stage = None
    rec.attempts = 0
    if from_stage != "eval":
        rec.stt_operation_name = None
        rec.stt_started_at = None
    rec.status = {"convert": "uploaded", "stt": "transcribing", "eval": "evaluating"}[from_stage]
    # Reactivate the batch so the rollup task recomputes its status — otherwise
    # the batch stays frozen at its old terminal value while this recording reruns.
    batch = await session.get(UploadBatch, rec.batch_id)
    if batch is not None and batch.status in ("completed", "completed_with_errors", "failed"):
        batch.status = "processing"
    log_audit(
        session, action="recording.reprocess", user_id=user.id, actor_email=user.email,
        object_type="recording", object_id=str(rec.id), details={"from_stage": from_stage},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send_pipeline_chain(str(rec.id), from_stage=from_stage)
    return _out(rec, False)
