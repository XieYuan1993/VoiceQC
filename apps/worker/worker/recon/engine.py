"""Reconciliation matching engine — pure functions, no DB.

DESIGN.md §6: metadata narrows (broker extension + time window around the
order/execution time), content confirms (weighted score over stock, side,
quantity, price, client identity, timing). Greedy assignment: a transaction
consumes at most one instruction; an instruction may serve several
transactions (split fills); a recording may serve many transactions
(multi-trade calls).

One deliberate refinement over the original spec: a stock-code mismatch is
only a hard disqualifier when the instruction's code evidence is consistent.
ASR garbles digits ("2318" heard as "1318"), so when the instruction's stock
NAME resolves via the glossary to the transaction's code, the name evidence
wins and the pair scores 1.0 on stock.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

DEFAULT_WEIGHTS = {
    "stock": 0.35,
    "side": 0.15,
    "quantity": 0.20,
    "price": 0.10,
    "client": 0.15,
    "time": 0.05,
}
NO_BROKER_PENALTY = 0.85


@dataclass
class TxnView:
    id: str
    anchor: datetime | None  # COALESCE(ordered_at, executed_at)
    broker_code: str | None
    client_account: str | None
    client_name: str | None
    stock_code: str | None
    stock_name: str | None
    side: str
    quantity: float | None
    price: float | None
    channel: str | None


@dataclass
class InstrView:
    id: str
    recording_id: str
    call_started_at: datetime | None
    broker_ext: str | None
    stock_code: str | None
    stock_name_raw: str | None
    side: str
    quantity: float | None
    price: float | None
    price_type: str
    client_name_raw: str | None
    client_account_raw: str | None


@dataclass
class Params:
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    auto_match: float = 0.75
    needs_review: float = 0.45
    before_hours: int = 6
    after_minutes: int = 15
    phone_only: bool = True
    quantity_tolerance: float = 0.10
    price_tolerance: float = 0.02


@dataclass
class MatchPair:
    txn_id: str
    instr_id: str
    recording_id: str
    score: float
    status: str  # auto_matched | needs_review
    breakdown: dict[str, Any]


@dataclass
class EngineResult:
    matched: list[MatchPair]
    txn_no_recording: list[str]  # transaction ids, severity=breach
    suspicious_instructions: list[str]  # instruction ids, severity=suspicious
    info_recordings: list[str]  # recording ids with zero instructions
    stats: dict[str, int]
    # txn_id -> top candidate calls (reviewer suggestions for an unmatched trade)
    candidates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def fold(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^0-9a-z一-鿿]+", "", text)


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _name_similarity(a: str | None, b: str | None) -> float:
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    if fa in fb or fb in fa:
        return 0.9
    return SequenceMatcher(None, fa, fb).ratio()


def _stock_score(
    txn: TxnView, instr: InstrView, alias_map: dict[str, str]
) -> tuple[float, bool, str]:
    """(score, hard_disqualify, note)."""
    name_code = alias_map.get(fold(instr.stock_name_raw)) if instr.stock_name_raw else None
    codes = {c for c in (instr.stock_code, name_code) if c}
    if txn.stock_code and txn.stock_code in codes:
        via = "name" if txn.stock_code == name_code and txn.stock_code != instr.stock_code else "code"
        return 1.0, False, f"matched via {via}"
    if txn.stock_code and codes:
        # Codes disagree and the glossary name didn't rescue it — try names.
        sim = _name_similarity(instr.stock_name_raw, txn.stock_name)
        if sim >= 0.6:
            return 0.6, False, f"code mismatch, name similarity {sim:.2f}"
        return 0.0, True, f"code mismatch ({sorted(codes)} vs {txn.stock_code})"
    sim = _name_similarity(instr.stock_name_raw, txn.stock_name)
    if sim >= 0.6:
        return 0.6, False, f"name similarity {sim:.2f}"
    # No stock extracted from the call is "unknown", not a contradiction — score
    # it neutral (like a missing client/quantity) so a strong qty/side/time match
    # still surfaces for review instead of being killed by stock's 35% weight.
    return 0.3, False, "no stock evidence (neutral)"


def _side_score(txn: TxnView, instr: InstrView) -> tuple[float, bool]:
    if instr.side in ("unknown", "amend", "cancel"):
        return 0.5, False
    if instr.side == txn.side:
        return 1.0, False
    return 0.0, True  # buy vs sell — hard disqualify


def _quantity_score(txn: TxnView, instr: InstrView, tol: float) -> float:
    if instr.quantity is None or txn.quantity is None:
        return 0.3
    if instr.quantity <= 0:
        return 0.3
    diff = abs(float(txn.quantity) - float(instr.quantity)) / (float(instr.quantity) * tol)
    return max(0.0, 1.0 - min(diff, 1.0) * 1.0) if diff <= 1.0 else 0.0


def _price_score(txn: TxnView, instr: InstrView, tol: float) -> float:
    if instr.price_type == "market" or instr.price is None or txn.price is None:
        return 0.5
    if float(instr.price) <= 0:
        return 0.5
    rel = abs(float(txn.price) - float(instr.price)) / float(instr.price)
    if rel <= tol:
        return 1.0
    if rel <= 2 * tol:
        return 1.0 - (rel - tol) / tol
    return 0.0


def _client_score(txn: TxnView, instr: InstrView) -> float:
    txn_acct, instr_acct = _digits(txn.client_account), _digits(instr.client_account_raw)
    account_contradicts = False
    if txn_acct and instr_acct:
        if txn_acct == instr_acct:
            return 1.0
        if len(instr_acct) >= 4 and txn_acct.endswith(instr_acct[-4:]):
            return 0.8
        account_contradicts = True
    sim = _name_similarity(instr.client_name_raw, txn.client_name)
    if sim >= 0.9:
        return 0.85
    if sim >= 0.75:
        return 0.7
    if account_contradicts:
        return 0.0  # hard evidence disagrees — triggers the review cap
    if not instr_acct and not fold(instr.client_name_raw):
        return 0.3  # instruction carries no client evidence — neutral
    # Name present but dissimilar: ASR garbles names routinely, so this is
    # soft evidence only — low score, but above the hard-discrepancy floor.
    return 0.15


def _time_score(txn: TxnView, instr: InstrView, params: Params) -> float:
    if txn.anchor is None or instr.call_started_at is None:
        return 0.2
    gap = txn.anchor - instr.call_started_at
    if gap >= timedelta(0):
        frac = gap / timedelta(hours=params.before_hours)
    else:
        frac = -gap / timedelta(minutes=params.after_minutes)
    return max(0.2, 1.0 - 0.8 * min(float(frac), 1.0))


def _in_window(txn: TxnView, instr: InstrView, params: Params) -> bool:
    if txn.anchor is None or instr.call_started_at is None:
        return True  # cannot exclude on time — content must carry it
    low = txn.anchor - timedelta(hours=params.before_hours)
    high = txn.anchor + timedelta(minutes=params.after_minutes)
    return low <= instr.call_started_at <= high


def score_pair(
    txn: TxnView,
    instr: InstrView,
    params: Params,
    alias_map: dict[str, str],
    broker_extensions: dict[str, set[str]],
) -> tuple[float, dict[str, Any]] | None:
    """Weighted score for one candidate pair; None when hard-disqualified."""
    stock, dq_stock, stock_note = _stock_score(txn, instr, alias_map)
    if dq_stock:
        return None
    side, dq_side = _side_score(txn, instr)
    if dq_side:
        return None

    components = {
        "stock": stock,
        "side": side,
        "quantity": _quantity_score(txn, instr, params.quantity_tolerance),
        "price": _price_score(txn, instr, params.price_tolerance),
        "client": _client_score(txn, instr),
        "time": _time_score(txn, instr, params),
    }
    weights = {**DEFAULT_WEIGHTS, **(params.weights or {})}
    total_weight = sum(weights.values()) or 1.0
    score = sum(weights[k] * components[k] for k in components) / total_weight

    penalty = None
    exts = broker_extensions.get(txn.broker_code or "")
    if not exts or instr.broker_ext not in exts:
        score *= NO_BROKER_PENALTY
        penalty = f"broker mapping uncertain (x{NO_BROKER_PENALTY})"

    breakdown = {
        "components": {k: round(v, 3) for k, v in components.items()},
        "weights": weights,
        "stock_note": stock_note,
        "penalty": penalty,
    }
    return round(score, 4), breakdown


def _lift_split_fills(
    matched: list[MatchPair],
    txns: list[TxnView],
    instrs: list[InstrView],
    params: Params,
) -> None:
    """Split fills: one instruction executed as several transactions.

    Pairwise, each fill's quantity disagrees with the instructed total and
    gets demoted by the material-discrepancy cap. When the fills assigned to
    one instruction SUM to the instructed quantity (within tolerance), the
    instruction is jointly satisfied — restore quantity to 1.0 for the group
    and re-derive scores/statuses.
    """
    txn_by_id = {t.id: t for t in txns}
    instr_by_id = {i.id: i for i in instrs}
    groups: dict[str, list[MatchPair]] = {}
    for pair in matched:
        groups.setdefault(pair.instr_id, []).append(pair)

    for instr_id, group in groups.items():
        if len(group) < 2:
            continue
        instr = instr_by_id.get(instr_id)
        if instr is None or not instr.quantity:
            continue
        quantities = [txn_by_id[p.txn_id].quantity for p in group]
        if any(q is None for q in quantities):
            continue
        total = sum(float(q) for q in quantities)
        if abs(total - float(instr.quantity)) > float(instr.quantity) * params.quantity_tolerance:
            continue
        for pair in group:
            components = pair.breakdown["components"]
            components["quantity"] = 1.0
            pair.breakdown["split_fill"] = f"{len(group)} fills sum to {total:g}"
            weights = pair.breakdown["weights"]
            total_weight = sum(weights.values()) or 1.0
            score = sum(weights[k] * components[k] for k in components) / total_weight
            if pair.breakdown.get("penalty"):
                score *= NO_BROKER_PENALTY
            pair.score = round(score, 4)
            zeroed = [
                k for k in ("quantity", "price", "client") if components[k] == 0.0
            ]
            if pair.score >= params.auto_match and not zeroed:
                pair.status = "auto_matched"
                pair.breakdown.pop("capped", None)
            elif pair.score >= params.needs_review:
                pair.status = "needs_review"


def run_match(
    txns: list[TxnView],
    instrs: list[InstrView],
    zero_instr_recordings: list[str],
    *,
    params: Params,
    alias_map: dict[str, str],
    broker_extensions: dict[str, set[str]],
) -> EngineResult:
    # Scope: phone-channel transactions need a recording; unknown channel is
    # treated as phone (conservative) so missing channel data fails loudly.
    if params.phone_only:
        in_scope = [t for t in txns if t.channel in ("phone", None)]
    else:
        in_scope = list(txns)
    excluded = len(txns) - len(in_scope)

    # Shortlist by broker + time window, score candidates.
    pairs: list[tuple[float, TxnView, InstrView, dict]] = []
    for txn in in_scope:
        exts = broker_extensions.get(txn.broker_code or "")
        for instr in instrs:
            if exts and instr.broker_ext is not None and instr.broker_ext not in exts:
                continue
            if not _in_window(txn, instr, params):
                continue
            scored = score_pair(txn, instr, params, alias_map, broker_extensions)
            if scored is not None:
                pairs.append((scored[0], txn, instr, scored[1]))

    # Greedy assignment, best score first.
    pairs.sort(key=lambda p: p[0], reverse=True)
    assigned_txns: set[str] = set()
    consumed_instrs: set[str] = set()
    matched: list[MatchPair] = []
    for score, txn, instr, breakdown in pairs:
        if txn.id in assigned_txns or score < params.needs_review:
            continue
        status = "auto_matched" if score >= params.auto_match else "needs_review"
        # Compliance cap: a zeroed component means hard evidence DISAGREES
        # (booked qty far from instructed, limit price way off, client name
        # contradicts) — never auto-match those, whatever the total score.
        zeroed = [
            k for k in ("quantity", "price", "client")
            if breakdown["components"][k] == 0.0
        ]
        if status == "auto_matched" and zeroed:
            status = "needs_review"
            breakdown["capped"] = f"material discrepancy in {', '.join(zeroed)}"
        matched.append(
            MatchPair(
                txn_id=txn.id,
                instr_id=instr.id,
                recording_id=instr.recording_id,
                score=score,
                status=status,
                breakdown=breakdown,
            )
        )
        assigned_txns.add(txn.id)
        consumed_instrs.add(instr.id)

    _lift_split_fills(matched, in_scope, instrs, params)

    txn_no_recording = [t.id for t in in_scope if t.id not in assigned_txns]
    suspicious = [i.id for i in instrs if i.id not in consumed_instrs]

    # Top candidate calls per unmatched transaction (reviewer suggestions) — from
    # the same scored pairs, including those below the match threshold.
    by_txn: dict[str, list[tuple[float, InstrView]]] = {}
    for score, txn, instr, _bd in pairs:
        by_txn.setdefault(txn.id, []).append((score, instr))
    candidates: dict[str, list[dict[str, Any]]] = {}
    for tid in txn_no_recording:
        top = sorted(by_txn.get(tid, []), key=lambda x: x[0], reverse=True)[:3]
        candidates[tid] = [
            {
                "instruction_id": instr.id,
                "recording_id": instr.recording_id,
                "score": round(score, 4),
                "stock_code": instr.stock_code,
                "side": instr.side,
                "quantity": instr.quantity,
                "client": instr.client_name_raw,
                "call_started_at": instr.call_started_at.isoformat()
                if instr.call_started_at
                else None,
            }
            for score, instr in top
        ]

    stats = {
        "txns_total": len(txns),
        "txns_excluded_channel": excluded,
        "instructions_total": len(instrs),
        "matched_auto": sum(1 for m in matched if m.status == "auto_matched"),
        "matched_needs_review": sum(1 for m in matched if m.status == "needs_review"),
        "txn_no_recording": len(txn_no_recording),
        "recording_no_txn_suspicious": len(suspicious),
        "recording_no_txn_info": len(zero_instr_recordings),
    }
    return EngineResult(
        matched=matched,
        txn_no_recording=txn_no_recording,
        suspicious_instructions=suspicious,
        info_recordings=list(zero_instr_recordings),
        stats=stats,
        candidates=candidates,
    )
