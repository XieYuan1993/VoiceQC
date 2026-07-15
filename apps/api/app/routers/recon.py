"""Reconciliation runs, the three-bucket item lists, review actions, export."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import (
    AppSetting,
    ReconItem,
    ReconRun,
    Recording,
    TradeInstruction,
    Transaction,
    User,
)

from app import queue
from app.db import get_session
from app.deps import ClientMeta, client_meta, require_project_module, resolve_project_id
from app.permissions import RECON_REVIEW, RECON_RUN, TXNS_READ, require
from app.routers.evaluations import _trade_out
from app.schemas import (
    ManualLinkIn,
    ReconItemListOut,
    ReconItemOut,
    ReconRecordingBrief,
    ReconRunCreate,
    ReconRunOut,
    ReconTxnBrief,
    ReviewNoteIn,
)

router = APIRouter(
    prefix="/api/recon",
    tags=["recon"],
    dependencies=[Depends(require_project_module("trade_reconciliation"))],
)

PARAM_KEYS = (
    "recon.weights",
    "recon.thresholds",
    "recon.time_window",
    "recon.phone_only",
    "recon.transaction_filters",
)
HK = ZoneInfo("Asia/Hong_Kong")
ACTIVE_RECORDING_STATUSES = ("uploaded", "converting", "transcribing", "evaluating")


def _run_out(r: ReconRun) -> ReconRunOut:
    snapshot = dict(r.params_snapshot or {})
    trade_date_from = snapshot.get("trade_date_from") or r.trade_date.isoformat()
    trade_date_to = snapshot.get("trade_date_to") or r.trade_date.isoformat()
    return ReconRunOut(
        id=r.id,
        trade_date=r.trade_date,
        trade_date_from=trade_date_from,
        trade_date_to=trade_date_to,
        status=r.status,
        params_snapshot=snapshot,
        stats=dict(r.stats) if r.stats else None,
        error=r.error,
        started_at=r.started_at,
        completed_at=r.completed_at,
    )


async def build_recon_run(
    session,
    project_id,
    trade_date,
    started_by=None,
    transaction_filters: dict | None = None,
    trade_date_to=None,
) -> ReconRun:
    """Create (flush, not commit/queue) a recon run snapshotting the project's
    saved recon params. Caller commits and queues. Shared by create_run and the
    delete-import re-reconcile path."""
    settings_rows = {
        row.key: row.value
        for row in (
            await session.execute(
                select(AppSetting).where(
                    AppSetting.project_id == project_id, AppSetting.key.in_(PARAM_KEYS)
                )
            )
        ).scalars()
    }
    snapshot = {
        "trade_date_from": trade_date.isoformat(),
        "trade_date_to": (trade_date_to or trade_date).isoformat(),
        "weights": settings_rows.get("recon.weights"),
        "thresholds": settings_rows.get("recon.thresholds"),
        "time_window": settings_rows.get("recon.time_window"),
        "phone_only": settings_rows.get("recon.phone_only", True),
        "transaction_filters": transaction_filters
        if transaction_filters is not None
        else settings_rows.get("recon.transaction_filters"),
    }
    run = ReconRun(trade_date=trade_date, params_snapshot=snapshot, started_by=started_by)
    session.add(run)
    await session.flush()
    return run


@router.post("/runs", response_model=ReconRunOut)
async def create_run(
    payload: ReconRunCreate,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(RECON_RUN)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ReconRunOut:
    trade_date_from = payload.trade_date_from or payload.trade_date
    trade_date_to = payload.trade_date_to or trade_date_from
    if trade_date_from is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "trade_date is required")
    if trade_date_to < trade_date_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "trade_date_to must be >= trade_date_from"
        )
    day_start = datetime.combine(trade_date_from, time.min, tzinfo=HK)
    day_end = datetime.combine(trade_date_to + timedelta(days=1), time.min, tzinfo=HK)
    active_recordings = (
        await session.execute(
            select(func.count())
            .select_from(Recording)
            .where(
                Recording.project_id == project_id,
                Recording.call_started_at >= day_start,
                Recording.call_started_at < day_end,
                Recording.status.in_(ACTIVE_RECORDING_STATUSES),
            )
        )
    ).scalar_one()
    if active_recordings:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{active_recordings} recordings in this date range are still processing; "
            "wait for evaluation to finish before reconciliation",
        )
    run = await build_recon_run(
        session,
        project_id,
        trade_date_from,
        user.id,
        payload.transaction_filters.model_dump() if payload.transaction_filters else None,
        trade_date_to,
    )
    log_audit(
        session,
        action="recon.run",
        user_id=user.id,
        actor_email=user.email,
        object_type="recon_run",
        object_id=str(run.id),
        details={
            "trade_date_from": str(trade_date_from),
            "trade_date_to": str(trade_date_to),
            "transaction_filters": run.params_snapshot.get("transaction_filters"),
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send("voiceqa.recon.run", str(run.id))
    return _run_out(run)


@router.get("/runs", response_model=list[ReconRunOut])
async def list_runs(
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ReconRunOut]:
    rows = (
        await session.execute(select(ReconRun).order_by(ReconRun.started_at.desc()).limit(50))
    ).scalars()
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=ReconRunOut)
async def get_run(
    run_id: uuid.UUID,
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
) -> ReconRunOut:
    run = await session.get(ReconRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return _run_out(run)


async def _item_out(session: AsyncSession, item: ReconItem) -> ReconItemOut:
    txn = await session.get(Transaction, item.transaction_id) if item.transaction_id else None
    rec = await session.get(Recording, item.recording_id) if item.recording_id else None
    instr = (
        await session.get(TradeInstruction, item.trade_instruction_id)
        if item.trade_instruction_id
        else None
    )
    txn_raw = txn.raw if txn is not None and isinstance(txn.raw, dict) else {}

    def raw_number(key: str, fallback) -> float | None:
        value = txn_raw.get(key)
        if value not in (None, ""):
            try:
                return float(str(value).replace(",", ""))
            except ValueError:
                pass
        return float(fallback) if fallback is not None else None

    return ReconItemOut(
        id=item.id,
        item_type=item.item_type,
        severity=item.severity,
        match_status=item.match_status,
        score=float(item.score) if item.score is not None else None,
        score_breakdown=dict(item.score_breakdown or {}),
        review_note=item.review_note,
        reviewed_at=item.reviewed_at,
        transaction=ReconTxnBrief(
            id=txn.id,
            ext_txn_id=txn.ext_txn_id,
            broker_code=txn.broker_code,
            client_name=txn.client_name,
            client_account=txn.client_account,
            stock_code=txn.stock_code,
            stock_name=txn.stock_name,
            side=txn.side,
            quantity=raw_number("order_quantity", txn.quantity),
            price=raw_number("order_price", txn.price),
            ordered_at=txn.ordered_at,
            executed_at=txn.executed_at,
            channel=txn.channel,
            order_status=str(txn_raw.get("order_status") or "").strip() or None,
            execution_type=str(txn_raw.get("execution_type") or "").strip() or None,
        )
        if txn
        else None,
        recording=ReconRecordingBrief(
            id=rec.id,
            original_filename=rec.original_filename,
            broker_ext=rec.broker_ext,
            broker_name=rec.broker_name,
            call_started_at=rec.call_started_at,
        )
        if rec
        else None,
        instruction=_trade_out(instr) if instr else None,
    )


@router.get("/runs/{run_id}/items", response_model=ReconItemListOut)
async def list_items(
    run_id: uuid.UUID,
    bucket: str | None = Query(
        default=None, pattern="^(matched|txn_no_recording|recording_no_txn)$"
    ),
    match_status: str | None = None,
    severity: str | None = Query(default=None, pattern="^(info|suspicious)$"),
    unmatched_reason: str | None = Query(
        default=None,
        pattern="^(no_broker_recordings_day|no_recordings_in_window|no_matching_recording)$",
    ),
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
) -> ReconItemListOut:
    page, page_size = max(1, page), min(max(1, page_size), 200)
    stmt = select(ReconItem).where(ReconItem.run_id == run_id)
    if bucket:
        stmt = stmt.where(ReconItem.item_type == bucket)
    if match_status:
        stmt = stmt.where(ReconItem.match_status == match_status)
    if severity:
        stmt = stmt.where(ReconItem.severity == severity)
    if unmatched_reason:
        stmt = stmt.where(ReconItem.score_breakdown["unmatched_reason"].astext == unmatched_reason)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(ReconItem.severity.desc(), ReconItem.score.desc().nulls_last())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return ReconItemListOut(
        items=[await _item_out(session, i) for i in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _get_item(session: AsyncSession, item_id: uuid.UUID) -> ReconItem:
    item = await session.get(ReconItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return item


async def _review(
    session: AsyncSession,
    item: ReconItem,
    user: User,
    meta: ClientMeta,
    new_status: str,
    note: str | None,
) -> None:
    item.match_status = new_status
    item.review_note = note
    item.reviewed_by = user.id
    item.reviewed_at = datetime.now(UTC)
    log_audit(
        session,
        action=f"recon_item.{new_status}",
        user_id=user.id,
        actor_email=user.email,
        object_type="recon_item",
        object_id=str(item.id),
        details={"note": note},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    await session.commit()


@router.post("/items/{item_id}/confirm", response_model=ReconItemOut)
async def confirm_item(
    item_id: uuid.UUID,
    payload: ReviewNoteIn,
    user: User = Depends(require(RECON_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ReconItemOut:
    item = await _get_item(session, item_id)
    await _review(session, item, user, meta, "confirmed", payload.note)
    return await _item_out(session, item)


@router.post("/items/{item_id}/reject", response_model=ReconItemOut)
async def reject_item(
    item_id: uuid.UUID,
    payload: ReviewNoteIn,
    user: User = Depends(require(RECON_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ReconItemOut:
    item = await _get_item(session, item_id)
    await _review(session, item, user, meta, "rejected", payload.note)
    return await _item_out(session, item)


@router.post("/items/{item_id}/manual-link", response_model=ReconItemOut)
async def manual_link(
    item_id: uuid.UUID,
    payload: ManualLinkIn,
    user: User = Depends(require(RECON_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ReconItemOut:
    """Link a transaction and a recording by reviewer judgement.

    Works from either bucket: a txn_no_recording item gains a recording, a
    recording_no_txn item gains a transaction. Sibling items in the same run
    referencing the counterpart are resolved as manual_linked too.
    """
    item = await _get_item(session, item_id)
    if payload.transaction_id is None and item.transaction_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "transaction_id required for this item")

    item.recording_id = payload.recording_id
    if payload.transaction_id is not None:
        item.transaction_id = payload.transaction_id
    if payload.trade_instruction_id is not None:
        item.trade_instruction_id = payload.trade_instruction_id
    item.item_type = "matched"
    item.severity = "info"

    # Resolve counterpart items (e.g. the suspicious instruction we just linked).
    siblings = (
        await session.execute(
            select(ReconItem).where(
                ReconItem.run_id == item.run_id,
                ReconItem.id != item.id,
                ReconItem.match_status == "unmatched",
                (
                    ReconItem.trade_instruction_id == payload.trade_instruction_id
                    if payload.trade_instruction_id
                    else ReconItem.recording_id == payload.recording_id
                ),
            )
        )
    ).scalars()
    for sibling in siblings:
        sibling.match_status = "manual_linked"
        sibling.transaction_id = item.transaction_id
        sibling.reviewed_by = user.id
        sibling.reviewed_at = datetime.now(UTC)

    await _review(session, item, user, meta, "manual_linked", payload.note)
    return await _item_out(session, item)


@router.get("/runs/{run_id}/export.csv")
async def export_run(
    run_id: uuid.UUID,
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    run = await session.get(ReconRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    items = (
        (
            await session.execute(
                select(ReconItem).where(ReconItem.run_id == run_id).order_by(ReconItem.item_type)
            )
        )
        .scalars()
        .all()
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "item_type",
            "severity",
            "match_status",
            "score",
            "txn_ref",
            "broker",
            "client",
            "stock",
            "side",
            "quantity",
            "price",
            "recording",
            "call_time",
            "note",
        ]
    )
    for item in items:
        out = await _item_out(session, item)
        txn, rec, instr = out.transaction, out.recording, out.instruction
        writer.writerow(
            [
                out.item_type,
                out.severity,
                out.match_status,
                out.score,
                txn.ext_txn_id if txn else "",
                txn.broker_code if txn else "",
                txn.client_name if txn else (instr.client_name_raw if instr else ""),
                (txn.stock_code if txn else None) or (instr.stock_code if instr else ""),
                (txn.side if txn else None) or (instr.side if instr else ""),
                (txn.quantity if txn else None) or (instr.quantity if instr else ""),
                (txn.price if txn else None) or (instr.price if instr else ""),
                rec.original_filename if rec else "",
                rec.call_started_at.isoformat() if rec and rec.call_started_at else "",
                out.review_note or "",
            ]
        )
    log_audit(
        session,
        action="recon.export",
        user_id=user.id,
        actor_email=user.email,
        object_type="recon_run",
        object_id=str(run_id),
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    await session.commit()
    snapshot = dict(run.params_snapshot or {})
    date_from = snapshot.get("trade_date_from") or run.trade_date.isoformat()
    date_to = snapshot.get("trade_date_to") or date_from
    date_label = date_from if date_from == date_to else f"{date_from}_{date_to}"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=recon_{date_label}_{str(run_id)[:8]}.csv"
        },
    )
