"""Upload batches: create -> upload files (audio or zip) -> finalize -> pipeline."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared import gcs
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import Recording, UploadBatch, User

from app import queue
from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import BATCHES_MANAGE, RECORDINGS_READ_ALL, require
from app.ratelimit import limiter
from app.schemas import (
    BatchCounts,
    BatchCreate,
    BatchListOut,
    BatchOut,
    RetryResult,
    UploadFileResult,
)

router = APIRouter(prefix="/api/batches", tags=["batches"])

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
MAX_AUDIO_BYTES = 200 * 1024 * 1024
MAX_ZIP_BYTES = 2 * 1024 * 1024 * 1024


async def _counts(session: AsyncSession, batch_id: uuid.UUID) -> BatchCounts:
    rows = (
        await session.execute(
            select(Recording.status, func.count())
            .where(Recording.batch_id == batch_id)
            .group_by(Recording.status)
        )
    ).all()
    return BatchCounts(**{status_: n for status_, n in rows})


def _out(batch: UploadBatch, counts: BatchCounts | None = None) -> BatchOut:
    return BatchOut(
        id=batch.id,
        name=batch.name,
        trade_date=batch.trade_date,
        status=batch.status,
        total_files=batch.total_files,
        created_at=batch.created_at,
        finalized_at=batch.finalized_at,
        counts=counts,
    )


@router.post("", response_model=BatchOut)
async def create_batch(
    payload: BatchCreate,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(BATCHES_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> BatchOut:
    batch = UploadBatch(
        project_id=project_id, name=payload.name, trade_date=payload.trade_date, created_by=user.id
    )
    session.add(batch)
    await session.flush()
    log_audit(
        session, action="batch.create", user_id=user.id, actor_email=user.email,
        object_type="batch", object_id=str(batch.id),
        details={"trade_date": str(payload.trade_date)}, ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return _out(batch)


@router.get("", response_model=BatchListOut)
async def list_batches(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    call_date_from: date | None = None,
    call_date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(RECORDINGS_READ_ALL)),
    session: AsyncSession = Depends(get_session),
) -> BatchListOut:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    stmt = select(UploadBatch).where(UploadBatch.project_id == project_id)
    if status_filter:
        stmt = stmt.where(UploadBatch.status == status_filter)
    if q:
        stmt = stmt.where(UploadBatch.name.ilike(f"%{q}%"))
    if call_date_from is not None:
        stmt = stmt.where(UploadBatch.trade_date >= call_date_from)
    if call_date_to is not None:
        stmt = stmt.where(UploadBatch.trade_date <= call_date_to)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    batches = (
        (
            await session.execute(
                stmt.order_by(UploadBatch.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = [_out(b, await _counts(session, b.id)) for b in batches]
    return BatchListOut(items=items, total=total, page=page, page_size=page_size)


async def _get_batch(session: AsyncSession, batch_id: uuid.UUID) -> UploadBatch:
    batch = await session.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "batch not found")
    return batch


@router.get("/{batch_id}", response_model=BatchOut)
async def get_batch(
    batch_id: uuid.UUID,
    user: User = Depends(require(RECORDINGS_READ_ALL)),
    session: AsyncSession = Depends(get_session),
) -> BatchOut:
    batch = await _get_batch(session, batch_id)
    return _out(batch, await _counts(session, batch.id))


def _purge_recording_audio(uris: list[str]) -> int:
    """Best-effort delete of GCS audio objects (object storage isn't transactional)."""
    return sum(1 for uri in uris if gcs.delete_uri(uri))


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_batch(
    batch_id: uuid.UUID,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(BATCHES_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> Response:
    """Delete a batch and (by cascade) its recordings, transcripts, evaluations and
    trade instructions, then purge their audio from object storage."""
    batch = await session.get(UploadBatch, batch_id)
    if batch is None or batch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "batch not found")
    recs = (
        await session.execute(select(Recording).where(Recording.batch_id == batch_id))
    ).scalars().all()
    uris = [
        u
        for r in recs
        for u in (r.gcs_uri_raw, r.gcs_uri_broker, r.gcs_uri_customer, r.gcs_uri_mono)
        if u
    ]
    log_audit(
        session, action="batch.delete", user_id=user.id, actor_email=user.email,
        object_type="batch", object_id=str(batch_id),
        details={"name": batch.name, "trade_date": str(batch.trade_date), "recordings": len(recs)},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.delete(batch)  # cascades to recordings + transcripts/evals/instructions
    await session.commit()
    if uris:
        await run_in_threadpool(_purge_recording_audio, uris)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{batch_id}/files", response_model=UploadFileResult)
@limiter.exempt
async def upload_file(
    batch_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(require(BATCHES_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> UploadFileResult:
    batch = await _get_batch(session, batch_id)
    if batch.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"batch is {batch.status}, not open")

    filename = Path(file.filename or "upload.bin").name
    ext = Path(filename).suffix.lower()
    is_zip = ext == ".zip"
    if not is_zip and ext not in AUDIO_EXTS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported file type {ext!r}; allowed: {sorted(AUDIO_EXTS)} or .zip",
        )
    limit = MAX_ZIP_BYTES if is_zip else MAX_AUDIO_BYTES

    # Stream to a temp file, hashing as we go.
    sha = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                Path(tmp_path).unlink(missing_ok=True)
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file exceeds {limit} bytes"
                )
            sha.update(chunk)
            tmp.write(chunk)
    digest = sha.hexdigest()

    try:
        if is_zip:
            await run_in_threadpool(
                gcs.upload_file, f"raw/{batch_id}/_zips/{filename}", tmp_path
            )
            return UploadFileResult(filename=filename, kind="zip", size_bytes=size)

        dup = (
            await session.execute(
                select(Recording.id).where(
                    Recording.batch_id == batch_id, Recording.sha256 == digest
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            return UploadFileResult(
                filename=filename, kind="audio", recording_id=dup, duplicate=True, size_bytes=size
            )

        rid = uuid.uuid4()
        raw_uri = await run_in_threadpool(
            gcs.upload_file, f"raw/{batch_id}/{rid}/{filename}", tmp_path
        )
        recording = Recording(
            id=rid,
            project_id=batch.project_id,
            batch_id=batch_id,
            original_filename=filename,
            sha256=digest,
            size_bytes=size,
            gcs_uri_raw=raw_uri,
        )
        session.add(recording)
        await session.commit()
        return UploadFileResult(filename=filename, kind="audio", recording_id=rid, size_bytes=size)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/{batch_id}/finalize", response_model=BatchOut)
async def finalize_batch(
    batch_id: uuid.UUID,
    user: User = Depends(require(BATCHES_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> BatchOut:
    batch = await _get_batch(session, batch_id)
    if batch.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"batch is {batch.status}, not open")
    batch.status = "processing"
    batch.finalized_at = datetime.now(UTC)
    log_audit(
        session, action="batch.finalize", user_id=user.id, actor_email=user.email,
        object_type="batch", object_id=str(batch.id), ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send("voiceqa.ingest.expand_batch", str(batch_id))
    return _out(batch)


@router.post("/{batch_id}/retry-failed", response_model=RetryResult)
async def retry_failed(
    batch_id: uuid.UUID,
    user: User = Depends(require(BATCHES_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> RetryResult:
    batch = await _get_batch(session, batch_id)
    failed = (
        (
            await session.execute(
                select(Recording).where(
                    Recording.batch_id == batch_id, Recording.status == "failed"
                )
            )
        )
        .scalars()
        .all()
    )
    plans: list[tuple[str, str]] = []
    for rec in failed:
        has_audio = rec.gcs_uri_broker or rec.gcs_uri_mono
        if rec.failed_stage in ("eval", "budget"):
            # Transcript already exists — resume at evaluation.
            stage, status_ = "eval", "evaluating"
        elif rec.failed_stage == "stt" and has_audio:
            stage, status_ = "stt", "transcribing"
            rec.stt_operation_name = None
        else:
            stage, status_ = "convert", "uploaded"
            rec.stt_operation_name = None
        rec.error = None
        rec.failed_stage = None
        rec.status = status_
        plans.append((str(rec.id), stage))
    if plans and batch.status == "completed_with_errors":
        batch.status = "processing"
    log_audit(
        session, action="batch.retry_failed", user_id=user.id, actor_email=user.email,
        object_type="batch", object_id=str(batch.id), details={"count": len(plans)},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    for rid, stage in plans:
        queue.send_pipeline_chain(rid, from_stage=stage)
    return RetryResult(retried=len(plans))
