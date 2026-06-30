"""Audit explorer + usage dashboards (read-only, compliance/audit roles)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import (
    AppSetting,
    AuditLog,
    LlmUsage,
    Recording,
    SttUsage,
    TxnImport,
    User,
)

from app import queue
from app.db import get_session
from app.deps import ClientMeta, client_meta
from app.permissions import AUDIT_READ, CONFIG_READ, CONFIG_WRITE, USAGE_READ, require
from app.schemas import AuditEntryOut, AuditListOut, UsageDay, UsageOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/audit", response_model=AuditListOut)
async def list_audit(
    action: str | None = None,
    actor_email: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    since: date | None = None,
    until: date | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require(AUDIT_READ)),
    session: AsyncSession = Depends(get_session),
) -> AuditListOut:
    page, page_size = max(1, page), min(max(1, page_size), 200)
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
    if actor_email:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor_email}%"))
    if object_type:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if object_id:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if since:
        stmt = stmt.where(AuditLog.occurred_at >= datetime.combine(since, datetime.min.time(), UTC))
    if until:
        stmt = stmt.where(
            AuditLog.occurred_at < datetime.combine(until + timedelta(days=1), datetime.min.time(), UTC)
        )
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return AuditListOut(
        items=[
            AuditEntryOut(
                id=r.id,
                occurred_at=r.occurred_at,
                actor_email=r.actor_email,
                action=r.action,
                object_type=r.object_type,
                object_id=r.object_id,
                details=r.details,
                ip=str(r.ip) if r.ip is not None else None,
                user_agent=r.user_agent,
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _setting_int(session: AsyncSession, key: str, default: int) -> int:
    from app.deps import default_project_id

    pid = await default_project_id(session)
    row = await session.get(AppSetting, (pid, key))
    try:
        return int(row.value) if row is not None else default
    except (TypeError, ValueError):
        return default


@router.get("/usage", response_model=UsageOut)
async def usage(
    days: int = Query(default=30, ge=1, le=180),
    user: User = Depends(require(USAGE_READ)),
    session: AsyncSession = Depends(get_session),
) -> UsageOut:
    today = datetime.now(UTC).date()
    since = today - timedelta(days=days - 1)

    llm_rows = (
        (
            await session.execute(
                select(LlmUsage).where(LlmUsage.day >= since).order_by(LlmUsage.day)
            )
        )
        .scalars()
        .all()
    )
    stt_rows = (
        (
            await session.execute(
                select(SttUsage).where(SttUsage.day >= since).order_by(SttUsage.day)
            )
        )
        .scalars()
        .all()
    )
    llm_today = sum(
        r.input_tokens + r.output_tokens for r in llm_rows if r.day == today
    )
    stt_today = sum(r.audio_seconds for r in stt_rows if r.day == today)

    return UsageOut(
        llm=[
            UsageDay(
                day=r.day,
                callsite=r.callsite,
                model=r.model,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                requests=r.requests,
            )
            for r in llm_rows
        ],
        stt=[
            UsageDay(
                day=r.day,
                model=r.model,
                audio_seconds=r.audio_seconds,
                requests=r.requests,
            )
            for r in stt_rows
        ],
        llm_today_tokens=int(llm_today),
        stt_today_seconds=int(stt_today),
        llm_daily_budget=await _setting_int(session, "budget.llm_daily_tokens", 10_000_000),
        stt_daily_budget=await _setting_int(session, "budget.stt_daily_seconds", 180_000),
    )


@router.get("/retention/preview")
async def retention_preview(
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """What the next retention sweep would purge (no changes)."""
    days = await _setting_int(session, "retention.days", 365)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    recs = (
        await session.execute(
            select(func.count())
            .select_from(Recording)
            .where(Recording.call_started_at < cutoff, Recording.gcs_uri_raw.is_not(None))
        )
    ).scalar_one()
    txn_files = (
        await session.execute(
            select(func.count())
            .select_from(TxnImport)
            .where(TxnImport.trade_date < cutoff.date(), TxnImport.gcs_uri.is_not(None))
        )
    ).scalar_one()
    return {
        "retention_days": days,
        "cutoff": cutoff.date().isoformat(),
        "recordings_to_purge": recs,
        "txn_files_to_purge": txn_files,
    }


@router.post("/retention/run", status_code=status.HTTP_202_ACCEPTED)
async def retention_run(
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> dict:
    """Trigger a retention sweep now (in addition to the daily schedule)."""
    log_audit(
        session, action="retention.run", user_id=user.id, actor_email=user.email,
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send("voiceqa.maintenance.apply_retention")
    return {"status": "queued"}
