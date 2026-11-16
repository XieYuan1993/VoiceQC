"""Project- and user-scoped risk recording inbox, derived from saved transcripts."""

import re
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.complaint_risks import NEGATION, PHRASES, detect_risk, risk_type
from voiceqa_shared.db_models import Recording, Transcript, TranscriptSegment, User

from app.db import get_session
from app.deps import resolve_project_id
from app.permissions import TRANSCRIPTS_READ, require
from app.routers.recordings import _apply_scope, _scope_extensions

router = APIRouter(prefix="/api/risks", tags=["risks"])


def risk_conditions(kind=None):
    text = func.regexp_replace(TranscriptSegment.text, "[[:space:]]+", "", "g")
    terms = [term for term in PHRASES if not kind or risk_type(term) == kind]
    return (
        TranscriptSegment.channel_role == "customer",
        text.op("~")("|".join(re.escape(term) for term in terms)),
        ~text.op("~")(NEGATION),
    )


@router.get("")
async def list_risks(
    page: int = Query(1, ge=1),
    q: str = Query("", max_length=200),
    kind: str | None = Query(None, pattern="^(complaint|supervisor|dissatisfaction)$"),
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(TRANSCRIPTS_READ)),
    session: AsyncSession = Depends(get_session),
):
    extensions = await _scope_extensions(session, user)
    candidates = (
        select(Transcript.recording_id)
        .join(TranscriptSegment, TranscriptSegment.transcript_id == Transcript.id)
        .where(*risk_conditions(kind))
        .distinct()
    )
    statement = _apply_scope(select(Recording), extensions).where(
        Recording.project_id == project_id, Recording.id.in_(candidates)
    )
    if q.strip():
        statement = statement.where(Recording.original_filename.ilike(f"%{q.strip()}%"))
    total = (
        await session.execute(select(func.count()).select_from(statement.subquery()))
    ).scalar_one()
    recordings = (
        (
            await session.execute(
                statement.order_by(Recording.call_started_at.desc().nulls_last(), Recording.id)
                .offset((page - 1) * 25)
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    if not recordings:
        return {"total": total, "page": page, "page_size": 25, "items": []}
    segments = (
        await session.execute(
            select(Transcript.recording_id, TranscriptSegment)
            .join(TranscriptSegment, TranscriptSegment.transcript_id == Transcript.id)
            .where(Transcript.recording_id.in_([rec.id for rec in recordings]), *risk_conditions())
            .order_by(TranscriptSegment.start_ms, TranscriptSegment.id)
        )
    ).all()
    hits = {}
    for recording_id, segment in segments:
        risk = detect_risk(segment.text, kind)
        if risk and (not kind or risk["risk_type"] == kind):
            hits.setdefault(recording_id, []).append(
                {
                    **risk,
                    "text": segment.text,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                }
            )
    return {
        "total": total,
        "page": page,
        "page_size": 25,
        "items": [
            {
                "recording_id": rec.id,
                "filename": rec.original_filename,
                "call_started_at": rec.call_started_at,
                "status": rec.status,
                "hits": hits.get(rec.id, []),
            }
            for rec in recordings
        ],
    }
