"""voiceqa.recon.run — reconcile one trade date.

Adapts DB rows to the pure engine (worker/recon/engine.py), writes
recon_items in the three requirement buckets, and carries reviewer
decisions forward from the previous run so confirm/reject/manual-link
work is never redone (keyed by transaction/recording identity).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import func, select
from voiceqa_shared.db_models import (
    AppSetting,
    Broker,
    Evaluation,
    IndustryTerm,
    Project,
    ReconItem,
    ReconRun,
    Recording,
    TradeInstruction,
    Transaction,
)

from worker.celery_app import app
from worker.db import SessionLocal
from worker.recon import engine
from worker.recon.engine import InstrView, Params, TxnView

HK = ZoneInfo("Asia/Hong_Kong")

_RECON_PARAM_KEYS = (
    "recon.weights",
    "recon.thresholds",
    "recon.time_window",
    "recon.phone_only",
    "recon.transaction_filters",
)


def enqueue_recon_run(session, trade_date) -> str | None:
    """Create + queue a reconciliation run for a trade date, using the trading
    project's saved recon params. Returns the run id, or None when no project has
    the trade_reconciliation module enabled (so it's a no-op for other tenants).
    """
    project = (
        session.execute(
            select(Project).where(Project.modules["trade_reconciliation"].astext == "true")
        )
        .scalars()
        .first()
    )
    if project is None:
        return None
    rows = {
        r.key: r.value
        for r in session.execute(
            select(AppSetting).where(
                AppSetting.project_id == project.id, AppSetting.key.in_(_RECON_PARAM_KEYS)
            )
        ).scalars()
    }
    snapshot = {
        "trade_date_from": trade_date.isoformat(),
        "trade_date_to": trade_date.isoformat(),
        "weights": rows.get("recon.weights"),
        "thresholds": rows.get("recon.thresholds"),
        "time_window": rows.get("recon.time_window"),
        "phone_only": rows.get("recon.phone_only", True),
        "transaction_filters": rows.get("recon.transaction_filters"),
    }
    run = ReconRun(trade_date=trade_date, params_snapshot=snapshot)
    session.add(run)
    session.flush()
    run_id = str(run.id)
    session.commit()
    app.send_task("voiceqa.recon.run", args=[run_id], queue="default")
    return run_id


def _params_from_snapshot(snapshot: dict) -> Params:
    weights = snapshot.get("weights") or {}
    thresholds = snapshot.get("thresholds") or {}
    window = snapshot.get("time_window") or {}
    return Params(
        weights={**engine.DEFAULT_WEIGHTS, **weights},
        auto_match=float(thresholds.get("auto_match", 0.75)),
        needs_review=float(thresholds.get("needs_review", 0.45)),
        before_hours=int(window.get("before_hours", 6)),
        after_minutes=int(window.get("after_minutes", 15)),
        phone_only=bool(snapshot.get("phone_only", True)),
    )


def _raw_value(raw, key: str) -> str:
    if not isinstance(raw, dict):
        return ""
    value = raw.get(key)
    return str(value).strip() if value is not None else ""


def _passes_transaction_filters(txn: Transaction, filters: dict | None) -> bool:
    if not isinstance(filters, dict):
        return True
    order_statuses = filters.get("order_statuses")
    execution_types = filters.get("execution_types")
    if isinstance(order_statuses, list) and _raw_value(txn.raw, "order_status") not in {
        str(v) for v in order_statuses
    }:
        return False
    return not (
        isinstance(execution_types, list)
        and _raw_value(txn.raw, "execution_type") not in {str(v) for v in execution_types}
    )


def _date_range_from_snapshot(trade_date: date, snapshot: dict | None) -> tuple[date, date]:
    snapshot = snapshot or {}
    raw_from = snapshot.get("trade_date_from")
    raw_to = snapshot.get("trade_date_to")
    date_from = date.fromisoformat(raw_from) if isinstance(raw_from, str) else trade_date
    date_to = date.fromisoformat(raw_to) if isinstance(raw_to, str) else date_from
    if date_to < date_from:
        date_to = date_from
    return date_from, date_to


def _load_views(
    session, trade_date_from, trade_date_to=None, transaction_filters: dict | None = None
) -> tuple[list[TxnView], list[InstrView], list[str]]:
    trade_date_to = trade_date_to or trade_date_from
    txns = [
        TxnView(
            id=str(t.id),
            anchor=t.ordered_at or t.executed_at,
            broker_code=t.broker_code,
            client_account=t.client_account,
            client_name=t.client_name,
            stock_code=t.stock_code,
            stock_name=t.stock_name,
            side=t.side,
            quantity=float(t.quantity) if t.quantity is not None else None,
            price=float(t.price) if t.price is not None else None,
            channel=t.channel,
        )
        for t in session.execute(
            select(Transaction).where(
                Transaction.trade_date >= trade_date_from,
                Transaction.trade_date <= trade_date_to,
            )
        ).scalars()
        if _passes_transaction_filters(t, transaction_filters)
    ]

    day_start = datetime.combine(trade_date_from, time.min, tzinfo=HK)
    day_end = datetime.combine(trade_date_to + timedelta(days=1), time.min, tzinfo=HK)
    recordings = (
        session.execute(
            select(Recording).where(
                Recording.status == "completed",
                Recording.call_started_at >= day_start,
                Recording.call_started_at < day_end,
            )
        )
        .scalars()
        .all()
    )

    # Latest completed evaluation per recording carries the instructions.
    latest_eval_ids = {}
    if recordings:
        rows = session.execute(
            select(Evaluation.recording_id, func.max(Evaluation.run_seq))
            .where(
                Evaluation.recording_id.in_([r.id for r in recordings]),
                Evaluation.status == "completed",
            )
            .group_by(Evaluation.recording_id)
        ).all()
        for rec_id, max_seq in rows:
            ev_id = session.execute(
                select(Evaluation.id).where(
                    Evaluation.recording_id == rec_id,
                    Evaluation.run_seq == max_seq,
                )
            ).scalar_one()
            latest_eval_ids[rec_id] = ev_id

    rec_by_id = {r.id: r for r in recordings}
    instrs: list[InstrView] = []
    recordings_with_instr: set[uuid.UUID] = set()
    if latest_eval_ids:
        rows = (
            session.execute(
                select(TradeInstruction).where(
                    TradeInstruction.evaluation_id.in_(latest_eval_ids.values())
                )
            )
            .scalars()
            .all()
        )
        for ti in rows:
            rec = rec_by_id.get(ti.recording_id)
            if rec is None:
                continue
            recordings_with_instr.add(rec.id)
            instrs.append(
                InstrView(
                    id=str(ti.id),
                    recording_id=str(rec.id),
                    call_started_at=rec.call_started_at,
                    broker_ext=rec.broker_ext,
                    stock_code=ti.stock_code,
                    stock_name_raw=ti.stock_name_raw,
                    side=ti.side,
                    quantity=float(ti.quantity) if ti.quantity is not None else None,
                    price=float(ti.price) if ti.price is not None else None,
                    price_type=ti.price_type,
                    client_name_raw=ti.client_name_raw,
                    client_account_raw=ti.client_account_raw,
                )
            )

    zero_instr = [
        str(r.id)
        for r in recordings
        if r.id in latest_eval_ids and r.id not in recordings_with_instr
    ]
    return txns, instrs, zero_instr


def _carry_forward_map(session, run: ReconRun) -> dict[tuple, ReconItem]:
    trade_date_from, trade_date_to = _date_range_from_snapshot(run.trade_date, run.params_snapshot)
    prev = session.execute(
        select(ReconRun)
        .where(
            ReconRun.trade_date == run.trade_date,
            ReconRun.id != run.id,
            ReconRun.status == "completed",
        )
        .order_by(ReconRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if prev is not None:
        prev_from, prev_to = _date_range_from_snapshot(prev.trade_date, prev.params_snapshot)
        if (prev_from, prev_to) != (trade_date_from, trade_date_to):
            prev = None
    if prev is None:
        return {}
    decided = (
        session.execute(
            select(ReconItem).where(
                ReconItem.run_id == prev.id,
                ReconItem.match_status.in_(("confirmed", "rejected", "manual_linked")),
            )
        )
        .scalars()
        .all()
    )
    return {
        (item.item_type, str(item.transaction_id), str(item.recording_id)): item for item in decided
    }


def _apply_decision(new_item: ReconItem, old: ReconItem | None) -> None:
    if old is None:
        return
    new_item.match_status = old.match_status
    new_item.review_note = old.review_note
    new_item.reviewed_by = old.reviewed_by
    new_item.reviewed_at = old.reviewed_at


@app.task(name="voiceqa.recon.run", bind=True, max_retries=1)
def run(self, run_id: str) -> None:
    with SessionLocal() as session:
        recon_run = session.get(ReconRun, uuid.UUID(run_id))
        if recon_run is None or recon_run.status != "running":
            return
        try:
            params = _params_from_snapshot(recon_run.params_snapshot)
            trade_date_from, trade_date_to = _date_range_from_snapshot(
                recon_run.trade_date,
                recon_run.params_snapshot,
            )
            txns, instrs, zero_instr = _load_views(
                session,
                trade_date_from,
                trade_date_to,
                (recon_run.params_snapshot or {}).get("transaction_filters"),
            )

            brokers = session.execute(select(Broker)).scalars().all()
            broker_extensions = {b.code: set(b.phone_extensions or []) for b in brokers}
            alias_map: dict[str, str] = {}
            for term in session.execute(
                select(IndustryTerm).where(IndustryTerm.active.is_(True))
            ).scalars():
                if term.stock_code:
                    for name in [term.canonical, *(term.aliases or [])]:
                        alias_map[engine.fold(name)] = term.stock_code

            result = engine.run_match(
                txns,
                instrs,
                zero_instr,
                params=params,
                alias_map=alias_map,
                broker_extensions=broker_extensions,
            )

            instr_by_id = {i.id: i for i in instrs}
            carried = _carry_forward_map(session, recon_run)
            carried_count = 0

            def make_item(**kwargs) -> ReconItem:
                nonlocal carried_count
                item = ReconItem(run_id=recon_run.id, **kwargs)
                key = (item.item_type, str(item.transaction_id), str(item.recording_id))
                old = carried.pop(key, None)
                if old is not None:
                    carried_count += 1
                _apply_decision(item, old)
                session.add(item)
                return item

            for pair in result.matched:
                make_item(
                    item_type="matched",
                    severity="info",
                    transaction_id=uuid.UUID(pair.txn_id),
                    recording_id=uuid.UUID(pair.recording_id),
                    trade_instruction_id=uuid.UUID(pair.instr_id),
                    score=pair.score,
                    score_breakdown=pair.breakdown,
                    match_status=pair.status,
                )
            for txn_id in result.txn_no_recording:
                make_item(
                    item_type="txn_no_recording",
                    severity="breach",
                    transaction_id=uuid.UUID(txn_id),
                    match_status="unmatched",
                    score_breakdown={"candidates": result.candidates.get(txn_id, [])},
                )
            for instr_id in result.suspicious_instructions:
                instr = instr_by_id[instr_id]
                make_item(
                    item_type="recording_no_txn",
                    severity="suspicious",
                    recording_id=uuid.UUID(instr.recording_id),
                    trade_instruction_id=uuid.UUID(instr_id),
                    match_status="unmatched",
                )
            for rec_id in result.info_recordings:
                make_item(
                    item_type="recording_no_txn",
                    severity="info",
                    recording_id=uuid.UUID(rec_id),
                    match_status="unmatched",
                )

            # Reviewer decisions whose pairs the engine no longer proposes
            # (manual links above all) survive as explicit items.
            for old in carried.values():
                if old.match_status in ("manual_linked", "confirmed"):
                    carried_count += 1
                    session.add(
                        ReconItem(
                            run_id=recon_run.id,
                            item_type="matched",
                            severity="info",
                            transaction_id=old.transaction_id,
                            recording_id=old.recording_id,
                            trade_instruction_id=old.trade_instruction_id,
                            score=old.score,
                            score_breakdown=old.score_breakdown,
                            match_status=old.match_status,
                            review_note=old.review_note,
                            reviewed_by=old.reviewed_by,
                            reviewed_at=old.reviewed_at,
                        )
                    )

            recon_run.stats = {**result.stats, "decisions_carried_forward": carried_count}
            recon_run.status = "completed"
            recon_run.completed_at = datetime.now(UTC)
            session.commit()
            logger.info("recon run {} completed: {}", run_id, recon_run.stats)
        except Exception as e:
            session.rollback()
            recon_run = session.get(ReconRun, uuid.UUID(run_id))
            if recon_run is not None:
                recon_run.status = "failed"
                recon_run.error = str(e)[:2000]
                session.commit()
            logger.exception("recon run {} failed", run_id)
            raise
