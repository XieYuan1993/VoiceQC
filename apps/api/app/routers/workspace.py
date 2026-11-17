"""Project-scoped overview and transcript amendment history."""

import uuid
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.db_models import (
    AuditLog,
    Evaluation,
    Recording,
    Transcript,
    TranscriptSegment,
    User,
)

from app.db import get_session
from app.deps import resolve_project_id
from app.permissions import TRANSCRIPTS_READ, require
from app.routers.recordings import _apply_scope, _scope_extensions
from app.routers.risks import risk_conditions

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def amendment_query(project_id, extensions):
    return _apply_scope(
        select(AuditLog, Recording.original_filename, Recording.id.label("recording_id"))
        .outerjoin(Transcript, AuditLog.object_id == cast(Transcript.id, Text))
        .join(
            Recording,
            or_(
                Recording.id == Transcript.recording_id,
                cast(Recording.id, Text) == AuditLog.details["recording_id"].astext,
            ),
        )
        .where(
            Recording.project_id == project_id,
            AuditLog.object_type == "transcript",
            AuditLog.action == "transcript.edit",
        ),
        extensions,
    )


@router.get("/amendments")
async def amendments(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    recording_id: uuid.UUID | None = None,
    q: str = Query("", max_length=200),
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(TRANSCRIPTS_READ)),
    session: AsyncSession = Depends(get_session),
):
    stmt = amendment_query(project_id, await _scope_extensions(session, user))
    if recording_id:
        stmt = stmt.where(Recording.id == recording_id)
    if q.strip():
        stmt = stmt.where(Recording.original_filename.ilike(f"%{q.strip()}%"))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": audit.id,
                "recording_id": rid,
                "filename": filename,
                "occurred_at": audit.occurred_at,
                "actor": audit.actor_email,
                **{
                    key: (audit.details or {}).get(key)
                    for key in ("segment_id", "start_ms", "before", "after")
                },
            }
            for audit, filename, rid in rows
        ],
    }


def summarize_enquiries(payloads):
    categories = Counter()
    calls = 0
    for payload in payloads:
        crs = (payload or {}).get("crs") or {}
        if crs.get("mode") != "crs_classification":
            continue
        calls += 1
        for event in crs.get("events") or []:
            categories[event.get("category") or "Unclassified"] += 1
    return (
        calls,
        sum(categories.values()),
        [{"label": label, "count": count} for label, count in categories.most_common()],
    )


@router.get("/overview")
async def overview(
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(TRANSCRIPTS_READ)),
    session: AsyncSession = Depends(get_session),
):
    extensions = await _scope_extensions(session, user)
    scope = _apply_scope(select(Recording.id).where(Recording.project_id == project_id), extensions)
    states = (
        await session.execute(
            select(Recording.status, func.count())
            .where(Recording.id.in_(scope))
            .group_by(Recording.status)
        )
    ).all()
    statuses = dict(states)
    risks = (
        select(Transcript.recording_id)
        .join(TranscriptSegment, TranscriptSegment.transcript_id == Transcript.id)
        .where(*risk_conditions())
        .distinct()
    )
    risk_count = (
        await session.execute(
            select(func.count())
            .select_from(Recording)
            .where(Recording.id.in_(scope), Recording.id.in_(risks))
        )
    ).scalar_one()
    latest = (
        select(Evaluation.recording_id.label("rid"), func.max(Evaluation.run_seq).label("seq"))
        .where(Evaluation.recording_id.in_(scope), Evaluation.status == "completed")
        .group_by(Evaluation.recording_id)
        .subquery()
    )
    payloads = (
        (
            await session.execute(
                select(Evaluation.extracted_call_fields).join(
                    latest,
                    and_(
                        Evaluation.recording_id == latest.c.rid, Evaluation.run_seq == latest.c.seq
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    classified, enquiries, categories = summarize_enquiries(payloads)
    edit_count = (
        await session.execute(
            select(func.count()).select_from(amendment_query(project_id, extensions).subquery())
        )
    ).scalar_one()
    return {
        "recordings": sum(statuses.values()),
        "completed": statuses.get("completed", 0),
        "failed": statuses.get("failed", 0),
        "processing": sum(n for state, n in states if state not in ("completed", "failed")),
        "risk_recordings": risk_count,
        "classified_calls": classified,
        "enquiries": enquiries,
        "enquiry_categories": categories,
        "amendments": edit_count,
    }
