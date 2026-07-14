"""voiceqa.recon.run — reconcile one trade date.

Adapts DB rows to the pure engine (worker/recon/engine.py), writes
recon_items in the three requirement buckets, and carries reviewer
decisions forward from the previous run so confirm/reject/manual-link
work is never redone (keyed by transaction/recording identity).
"""

from __future__ import annotations

import uuid
from bisect import bisect_left, bisect_right
from collections import Counter
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
from worker.recon.engine import InstrView, Params, RecordingView, TxnView
from worker.trade_normalization import (
    MAX_SECURITY_CANDIDATES,
    infer_price_type,
    recover_stock_code,
)

HK = ZoneInfo("Asia/Hong_Kong")
PRESET_STATUSES = {"待報\uff08保價\uff09", "待報\uff08條件單\uff09"}

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
        us_before_hours=int(window.get("us_before_hours", 18)),
        after_minutes=int(window.get("after_minutes", 15)),
        phone_only=bool(snapshot.get("phone_only", True)),
    )


def _raw_value(raw, key: str) -> str:
    if not isinstance(raw, dict):
        return ""
    value = raw.get(key)
    return str(value).strip() if value is not None else ""


def _raw_first(raw, *keys: str) -> str:
    for key in keys:
        value = _raw_value(raw, key)
        if value:
            return value
    return ""


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


def _base_order_id(txn: Transaction) -> str:
    raw_id = _raw_first(txn.raw, "ext_txn_id", "訂單號", "订单号")
    return raw_id or (txn.ext_txn_id or str(txn.id))


def _raw_number(raw, *keys: str) -> float | None:
    text_value = _raw_first(raw, *keys)
    if not text_value:
        return None
    try:
        return float(text_value.replace(",", ""))
    except ValueError:
        return None


def _is_batch_expiry(txn: Transaction) -> bool:
    status = _raw_first(txn.raw, "order_status", "訂單狀態", "订单状态")
    upstream = _raw_first(txn.raw, "upstream_broker", "上手經紀商", "上手经纪商").upper()
    anchor = txn.ordered_at or txn.executed_at
    if status != "已過期" or anchor is None:
        return False
    local_time = anchor.astimezone(HK).time()
    if upstream == "HKEX" and time(16, 10, 0) <= local_time <= time(16, 10, 20):
        return True
    return upstream == "IB" and time(4, 0, 0) <= local_time <= time(4, 0, 30)


def _is_rms_reject(txn: Transaction) -> bool:
    info = _raw_first(txn.raw, "info", "信息").casefold()
    return "rms." in info or "expire_date_reject" in info


def _action_view(
    txn: Transaction, action_type: str, previous: Transaction | None = None
) -> TxnView:
    raw = txn.raw if isinstance(txn.raw, dict) else {}
    quantity = _raw_number(raw, "order_quantity", "委託數量")
    price = _raw_number(raw, "order_price", "委託價格")
    return TxnView(
        id=str(txn.id),
        anchor=txn.ordered_at or txn.executed_at,
        broker_code=txn.broker_code,
        client_account=txn.client_account,
        client_name=txn.client_name,
        stock_code=txn.stock_code,
        stock_name=txn.stock_name,
        side=txn.side,
        quantity=quantity
        if quantity is not None
        else (float(txn.quantity) if txn.quantity is not None else None),
        price=price if price is not None else (float(txn.price) if txn.price is not None else None),
        channel=txn.channel,
        broker_name=_raw_first(raw, "broker_name", "委託人", "委托人") or None,
        action_type=action_type,
        previous_price=(_raw_number(previous.raw, "order_price") if previous is not None else None),
    )


def _transaction_action_views(
    rows: list[Transaction], transaction_filters: dict | None = None
) -> list[TxnView]:
    grouped: dict[str, list[Transaction]] = {}
    for txn in rows:
        if _is_batch_expiry(txn) or _is_rms_reject(txn):
            continue
        grouped.setdefault(_base_order_id(txn), []).append(txn)

    views: list[TxnView] = []
    for group in grouped.values():
        ordered = sorted(
            group,
            key=lambda t: t.ordered_at or t.executed_at or datetime.min.replace(tzinfo=UTC),
        )
        for index, txn in enumerate(ordered):
            execution_type = _raw_first(txn.raw, "execution_type", "執行類型", "执行类型")
            status = _raw_first(txn.raw, "order_status", "訂單狀態", "订单状态")
            if execution_type == "NewExec":
                previous = ordered[index - 1] if index > 0 else None
                prev_status = (
                    _raw_first(previous.raw, "order_status", "訂單狀態", "订单状态")
                    if previous
                    else ""
                )
                if prev_status in PRESET_STATUSES:
                    continue
                if _passes_transaction_filters(txn, transaction_filters):
                    views.append(_action_view(txn, "new"))
            elif execution_type == "ReplaceExec":
                if _passes_transaction_filters(txn, transaction_filters):
                    views.append(
                        _action_view(
                            txn,
                            "replace",
                            ordered[index - 1] if index > 0 else None,
                        )
                    )
            elif execution_type == "CanceledExec":
                if _passes_transaction_filters(txn, transaction_filters):
                    views.append(_action_view(txn, "cancel"))
            elif status in PRESET_STATUSES:
                if _passes_transaction_filters(txn, transaction_filters):
                    views.append(_action_view(txn, "preset"))
    return views


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
    session,
    trade_date_from,
    trade_date_to=None,
    transaction_filters: dict | None = None,
    params: Params | None = None,
) -> tuple[list[TxnView], list[InstrView], list[str], int, list[RecordingView]]:
    trade_date_to = trade_date_to or trade_date_from
    params = params or Params()
    txn_rows = list(
        session.execute(
            select(Transaction).where(
                Transaction.trade_date >= trade_date_from,
                Transaction.trade_date <= trade_date_to,
            )
        ).scalars()
    )
    txns = _transaction_action_views(txn_rows, transaction_filters)

    day_start = datetime.combine(trade_date_from, time.min, tzinfo=HK)
    day_end = datetime.combine(trade_date_to + timedelta(days=1), time.min, tzinfo=HK)
    max_before_hours = max(params.before_hours, params.us_before_hours)
    anchors = [t.anchor for t in txns if t.anchor is not None]
    if anchors:
        rec_start = min(day_start, min(anchors) - timedelta(hours=max_before_hours))
        rec_end = max(day_end, max(anchors) + timedelta(minutes=params.after_minutes))
    else:
        rec_start, rec_end = day_start, day_end
    recordings = (
        session.execute(
            select(Recording).where(
                Recording.status == "completed",
                Recording.call_started_at >= rec_start,
                Recording.call_started_at < rec_end,
            )
        )
        .scalars()
        .all()
    )

    # Latest completed evaluation per recording carries the instructions.
    latest_eval_ids = {}
    if recordings:
        latest_runs = (
            select(Evaluation.recording_id, func.max(Evaluation.run_seq).label("run_seq"))
            .where(
                Evaluation.recording_id.in_([r.id for r in recordings]),
                Evaluation.status == "completed",
            )
            .group_by(Evaluation.recording_id)
            .subquery()
        )
        rows = session.execute(
            select(Evaluation.recording_id, Evaluation.id).join(
                latest_runs,
                (Evaluation.recording_id == latest_runs.c.recording_id)
                & (Evaluation.run_seq == latest_runs.c.run_seq),
            )
        ).all()
        latest_eval_ids = dict(rows)

    rec_by_id = {r.id: r for r in recordings}
    instrs: list[InstrView] = []
    recordings_with_instr: set[uuid.UUID] = set()
    recovered_stock_count = 0
    candidates_by_recording: dict[uuid.UUID, list[tuple[str, str | None]]] = {}
    candidate_rows = sorted(
        (
            (anchor, txn.stock_code, txn.stock_name)
            for txn in txn_rows
            if txn.stock_code and (anchor := txn.ordered_at or txn.executed_at) is not None
        ),
        key=lambda row: row[0],
    )
    candidate_times = [row[0] for row in candidate_rows]
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
            candidates = candidates_by_recording.get(rec.id)
            if candidates is None:
                low = rec.call_started_at - timedelta(minutes=15)
                high = rec.call_started_at + timedelta(hours=max_before_hours)
                left = bisect_left(candidate_times, low)
                right = bisect_right(candidate_times, high)
                counts = Counter((code, name) for _at, code, name in candidate_rows[left:right])
                candidates = [
                    security for security, _count in counts.most_common(MAX_SECURITY_CANDIDATES)
                ]
                candidates_by_recording[rec.id] = candidates
            stock_code = ti.stock_code
            if stock_code is None:
                stock_code = recover_stock_code(
                    ti.evidence_quote,
                    candidates,
                    quantity=ti.quantity,
                    price=ti.price,
                )
                if stock_code is not None:
                    recovered_stock_count += 1
            recordings_with_instr.add(rec.id)
            instrs.append(
                InstrView(
                    id=str(ti.id),
                    recording_id=str(rec.id),
                    call_started_at=rec.call_started_at,
                    call_duration_seconds=float(rec.duration_seconds)
                    if rec.duration_seconds is not None
                    else None,
                    broker_ext=rec.broker_ext,
                    broker_name=rec.broker_name,
                    stock_code=stock_code,
                    stock_name_raw=ti.stock_name_raw,
                    side=ti.side,
                    quantity=float(ti.quantity) if ti.quantity is not None else None,
                    price=float(ti.price) if ti.price is not None else None,
                    price_type=infer_price_type(ti.price_type, ti.evidence_quote),
                    client_name_raw=ti.client_name_raw or rec.client_name,
                    client_account_raw=ti.client_account_raw or rec.client_account,
                    evidence_quote=ti.evidence_quote,
                    original_filename=rec.original_filename,
                )
            )

    zero_instr = [
        str(r.id)
        for r in recordings
        if r.id in latest_eval_ids and r.id not in recordings_with_instr
    ]
    recording_contexts = [
        RecordingView(
            id=str(rec.id),
            call_started_at=rec.call_started_at,
            broker_ext=rec.broker_ext,
            broker_name=rec.broker_name,
            original_filename=rec.original_filename,
        )
        for rec in recordings
    ]
    return txns, instrs, zero_instr, recovered_stock_count, recording_contexts


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
            txns, instrs, zero_instr, recovered_stock_count, recording_contexts = _load_views(
                session,
                trade_date_from,
                trade_date_to,
                (recon_run.params_snapshot or {}).get("transaction_filters"),
                params,
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
                recording_contexts=recording_contexts,
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
                    score_breakdown={
                        "unmatched_reason": result.unmatched_reasons.get(txn_id),
                        "candidates": result.candidates.get(txn_id, []),
                    },
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

            recon_run.stats = {
                **result.stats,
                "instructions_stock_recovered": recovered_stock_count,
                "decisions_carried_forward": carried_count,
            }
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
