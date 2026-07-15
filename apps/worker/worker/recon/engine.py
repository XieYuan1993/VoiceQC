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
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_WEIGHTS = {
    "stock": 0.35,
    "side": 0.15,
    "quantity": 0.20,
    "price": 0.10,
    "client": 0.15,
    "time": 0.05,
}
NO_BROKER_PENALTY = 0.85
HK = ZoneInfo("Asia/Hong_Kong")


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
    broker_name: str | None = None
    action_type: str | None = None
    previous_price: float | None = None
    source_trade_date: date | None = None


@dataclass
class InstrView:
    id: str
    recording_id: str
    call_started_at: datetime | None
    call_duration_seconds: float | None
    broker_ext: str | None
    stock_code: str | None
    stock_name_raw: str | None
    side: str
    quantity: float | None
    price: float | None
    price_type: str
    client_name_raw: str | None
    client_account_raw: str | None
    broker_name: str | None = None
    evidence_quote: str | None = None
    original_filename: str | None = None


@dataclass
class RecordingView:
    id: str
    call_started_at: datetime | None
    broker_ext: str | None
    broker_name: str | None
    original_filename: str | None = None


@dataclass
class Params:
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    auto_match: float = 0.75
    needs_review: float = 0.45
    before_hours: int = 6
    us_before_hours: int = 18
    after_minutes: int = 3
    phone_only: bool = True
    quantity_tolerance: float = 0.10
    price_tolerance: float = 0.02
    # PDF rule D1: order entry must occur during the call or within three
    # minutes after it ends. The flag preserves the score-only experiment.
    post_call_seconds: int = 180
    enforce_candidate_time_window: bool = True
    classify_unmatched_by_broker: bool = False


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
    # txn_id -> no_broker_recordings_day | no_recordings_in_window | no_matching_recording
    unmatched_reasons: dict[str, str] = field(default_factory=dict)


def fold(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^0-9a-z一-鿿]+", "", text)


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _person_key(value: str | None) -> str:
    folded = re.sub(
        r"[^0-9a-z\u3400-\u9fff]",
        "",
        unicodedata.normalize("NFKC", value or "").casefold(),
    )
    return "".join(sorted(folded))


def _identifying_broker_name(value: str | None) -> bool:
    normalized = unicodedata.normalize("NFKC", value or "")
    latin = re.sub(r"[^a-z]", "", normalized.casefold())
    cjk = re.findall(r"[\u3400-\u9fff]", normalized)
    return len(latin) >= 3 or len(cjk) >= 2


def _broker_name_matches(txn: TxnView, instr: InstrView) -> bool:
    if not _identifying_broker_name(txn.broker_name) or not _identifying_broker_name(
        instr.broker_name
    ):
        return False
    txn_key = _person_key(txn.broker_name)
    instr_key = _person_key(instr.broker_name)
    if not txn_key or not instr_key:
        return False
    if txn_key == instr_key:
        return True
    # Telephony and order exports often differ only by romanisation or a
    # missing vowel (Paul Leng / Paul Leung). Keep the threshold high because
    # a broker match is shortlist evidence, not a cosmetic display match.
    return SequenceMatcher(None, txn_key, instr_key).ratio() >= 0.9


def _txn_extensions(txn: TxnView, broker_extensions: dict[str, set[str]]) -> set[str]:
    """Resolve PBX extensions by order-system code or canonical broker name."""
    return {
        *broker_extensions.get(txn.broker_code or "", set()),
        *broker_extensions.get(fold(txn.broker_name), set()),
    }


def _broker_matches(
    txn: TxnView,
    broker_name: str | None,
    broker_ext: str | None,
    broker_extensions: dict[str, set[str]],
) -> bool:
    probe = InstrView(
        id="",
        recording_id="",
        call_started_at=None,
        call_duration_seconds=None,
        broker_ext=broker_ext,
        broker_name=broker_name,
        stock_code=None,
        stock_name_raw=None,
        side="unknown",
        quantity=None,
        price=None,
        price_type="unknown",
        client_name_raw=None,
        client_account_raw=None,
    )
    if _broker_name_matches(txn, probe):
        return True
    exts = _txn_extensions(txn, broker_extensions)
    return bool(exts and broker_ext in exts)


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
        via = (
            "name" if txn.stock_code == name_code and txn.stock_code != instr.stock_code else "code"
        )
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


def _uses_extended_before_window(txn: TxnView) -> bool:
    return bool(re.search(r"[A-Za-z]", txn.stock_code or ""))


def _before_hours(txn: TxnView, params: Params) -> int:
    if _uses_extended_before_window(txn):
        return max(params.before_hours, params.us_before_hours)
    return params.before_hours


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
    call_end = instr.call_started_at + timedelta(seconds=instr.call_duration_seconds or 0)
    if instr.call_started_at <= txn.anchor <= call_end:
        return 1.0
    if txn.anchor < instr.call_started_at:
        return 0.0
    delay_seconds = (txn.anchor - call_end).total_seconds()
    if delay_seconds > params.post_call_seconds:
        return 0.0
    return 1.0 - 0.5 * (delay_seconds / max(params.post_call_seconds, 1))


def _price_in_evidence(price: float | None, evidence: str | None) -> bool:
    if price is None or not evidence:
        return False
    compact = re.sub(r"\D", "", evidence)
    variants = {
        re.sub(r"\D", "", f"{price:g}"),
        re.sub(r"\D", "", f"{price:.2f}"),
        re.sub(r"\D", "", f"{price:.3f}"),
    }
    return any(len(value) >= 2 and value in compact for value in variants)


def _conflict_fields(
    txn: TxnView,
    instr: InstrView,
    components: dict[str, float],
    stock_conflict: bool,
    side_conflict: bool,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    if stock_conflict:
        conflicts.append(
            {"field": "stock", "transaction": txn.stock_code, "recording": instr.stock_code}
        )
    if side_conflict:
        conflicts.append({"field": "side", "transaction": txn.side, "recording": instr.side})
    for component_name, expected, actual in (
        ("quantity", txn.quantity, instr.quantity),
        ("price", txn.price, instr.price),
        (
            "client",
            txn.client_account or txn.client_name,
            instr.client_account_raw or instr.client_name_raw,
        ),
    ):
        if components[component_name] == 0.0 and expected is not None and actual is not None:
            conflicts.append(
                {"field": component_name, "transaction": expected, "recording": actual}
            )
    return conflicts


def _in_window(txn: TxnView, instr: InstrView, params: Params) -> bool:
    if txn.anchor is None or instr.call_started_at is None:
        return True  # cannot exclude on time — content must carry it
    call_end = instr.call_started_at + timedelta(seconds=instr.call_duration_seconds or 0)
    return (
        instr.call_started_at
        <= txn.anchor
        <= call_end + timedelta(seconds=params.post_call_seconds)
    )


def _recording_in_window(txn: TxnView, rec: RecordingView, params: Params) -> bool:
    if txn.anchor is None or rec.call_started_at is None:
        return True
    low = txn.anchor - timedelta(hours=_before_hours(txn, params))
    high = txn.anchor + timedelta(minutes=params.after_minutes)
    return low <= rec.call_started_at <= high


def score_pair(
    txn: TxnView,
    instr: InstrView,
    params: Params,
    alias_map: dict[str, str],
    broker_extensions: dict[str, set[str]],
) -> tuple[float, dict[str, Any]]:
    """Score a pair and retain contradictions for review diagnostics."""
    stock, dq_stock, stock_note = _stock_score(txn, instr, alias_map)
    side, dq_side = _side_score(txn, instr)
    if txn.action_type == "replace" and instr.side == "amend":
        side, dq_side = 1.0, False

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
    exts = _txn_extensions(txn, broker_extensions)
    broker_name_match = _broker_name_matches(txn, instr)
    broker_name_known = _identifying_broker_name(txn.broker_name) and _identifying_broker_name(
        instr.broker_name
    )
    ext_match = bool(exts and instr.broker_ext in exts)
    if not ext_match and not broker_name_match:
        score *= NO_BROKER_PENALTY
        evidence = "name mismatch" if broker_name_known else "mapping uncertain"
        penalty = f"broker {evidence} (x{NO_BROKER_PENALTY})"

    broker_match = ext_match or broker_name_match
    high_agreement = [
        name
        for name, matched in (
            ("broker", broker_match),
            ("time", components["time"] >= 0.7),
            ("side", components["side"] >= 0.999),
            ("quantity", components["quantity"] >= 0.9),
            ("price", components["price"] >= 0.9),
            ("client", components["client"] >= 0.8),
        )
        if matched
    ]
    amend_evidence = None
    if txn.action_type == "replace" and instr.side == "amend":
        amend_evidence = {
            "action_match": True,
            "account_match": components["client"] >= 0.8,
            "stock_match": components["stock"] >= 0.6,
            "new_price_match": components["price"] >= 0.9,
            "old_price_match": _price_in_evidence(txn.previous_price, instr.evidence_quote),
            "previous_price": txn.previous_price,
        }

    breakdown = {
        "components": {k: round(v, 3) for k, v in components.items()},
        "weights": weights,
        "stock_note": stock_note,
        "window_before_hours": _before_hours(txn, params),
        "post_call_seconds": params.post_call_seconds,
        "broker_name_match": broker_name_match,
        "broker_match": broker_match,
        "penalty": penalty,
        "hard_conflicts": [
            name for name, conflicts in (("stock", dq_stock), ("side", dq_side)) if conflicts
        ],
        "high_agreement_fields": high_agreement,
        "conflict_fields": _conflict_fields(txn, instr, components, dq_stock, dq_side),
    }
    if broker_name_known and not broker_match:
        breakdown["conflict_fields"].append(
            {
                "field": "broker",
                "transaction": txn.broker_name or txn.broker_code,
                "recording": instr.broker_name or instr.broker_ext,
            }
        )
    if amend_evidence is not None:
        breakdown["amend_evidence"] = amend_evidence
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
            zeroed = [k for k in ("quantity", "price", "client") if components[k] == 0.0]
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
    recording_contexts: list[RecordingView] | None = None,
) -> EngineResult:
    # Scope: phone-channel transactions need a recording; unknown channel is
    # treated as phone (conservative) so missing channel data fails loudly.
    if params.phone_only:
        in_scope = [t for t in txns if t.channel in ("phone", None)]
    else:
        in_scope = list(txns)
    excluded = len(txns) - len(in_scope)

    # Score every loaded instruction, then apply the compliance shortlist.
    # The legacy time-window gate remains available behind a disabled flag.
    pairs: list[tuple[float, TxnView, InstrView, dict, bool, int]] = []
    diagnostic_pairs: list[tuple[float, TxnView, InstrView, dict]] = []
    for txn in in_scope:
        exts = _txn_extensions(txn, broker_extensions)
        for instr in instrs:
            if params.enforce_candidate_time_window and not _in_window(txn, instr, params):
                continue
            broker_name_match = _broker_name_matches(txn, instr)
            ext_match = bool(exts and instr.broker_ext in exts)
            broker_conflict = not (ext_match or broker_name_match) and (
                (
                    _identifying_broker_name(txn.broker_name)
                    and _identifying_broker_name(instr.broker_name)
                )
                or bool(exts and instr.broker_ext is not None)
            )
            score, breakdown = score_pair(txn, instr, params, alias_map, broker_extensions)
            diagnostic_pairs.append((score, txn, instr, breakdown))
            hard_conflicts = set(breakdown["hard_conflicts"])
            stock_review = (
                "stock" in hard_conflicts and len(breakdown["high_agreement_fields"]) >= 4
            )
            amend_evidence = breakdown.get("amend_evidence") or {}
            amend_evidence_count = sum(
                bool(amend_evidence.get(field))
                for field in (
                    "account_match",
                    "stock_match",
                    "new_price_match",
                    "old_price_match",
                )
            )
            amend_review = bool(amend_evidence.get("action_match")) and amend_evidence_count >= 3
            force_review = stock_review or amend_review or broker_conflict
            # Broker identity is soft evidence: transfers and assisted orders
            # legitimately cross broker lines. Keep the score penalty, but let
            # sufficiently strong content surface for mandatory review.
            eligible = not hard_conflicts or stock_review or amend_review
            if not eligible:
                continue
            if stock_review:
                breakdown["capped"] = "stock conflict; surfaced because 4+ other fields agree"
            elif broker_conflict:
                breakdown["capped"] = "broker mismatch; score penalty applied and review required"
            if amend_review:
                breakdown["priority"] = "amend_replace"
            pairs.append(
                (
                    max(score, params.needs_review) if stock_review or amend_review else score,
                    txn,
                    instr,
                    breakdown,
                    force_review,
                    1 if amend_review else 0,
                )
            )

    # Greedy assignment, best score first.
    pairs.sort(key=lambda p: (p[5], p[0]), reverse=True)
    assigned_txns: set[str] = set()
    consumed_instrs: set[str] = set()
    matched: list[MatchPair] = []
    for score, txn, instr, breakdown, force_review, _priority in pairs:
        if txn.id in assigned_txns or score < params.needs_review:
            continue
        status = (
            "auto_matched" if score >= params.auto_match and not force_review else "needs_review"
        )
        # Compliance cap: a zeroed component means hard evidence DISAGREES
        # (booked qty far from instructed, limit price way off, client name
        # contradicts) — never auto-match those, whatever the total score.
        zeroed = [k for k in ("quantity", "price", "client") if breakdown["components"][k] == 0.0]
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
    by_txn: dict[str, list[tuple[float, InstrView, dict[str, Any]]]] = {}
    for score, txn, instr, breakdown in diagnostic_pairs:
        by_txn.setdefault(txn.id, []).append((score, instr, breakdown))
    candidates: dict[str, list[dict[str, Any]]] = {}
    unmatched_reasons: dict[str, str] = {}
    txn_by_id = {txn.id: txn for txn in in_scope}
    contexts = recording_contexts or [
        RecordingView(
            id=instr.recording_id,
            call_started_at=instr.call_started_at,
            broker_ext=instr.broker_ext,
            broker_name=instr.broker_name,
            original_filename=instr.original_filename,
        )
        for instr in instrs
    ]
    for tid in txn_no_recording:
        txn = txn_by_id[tid]
        if params.classify_unmatched_by_broker:
            broker_calls = [
                rec
                for rec in contexts
                if _broker_matches(txn, rec.broker_name, rec.broker_ext, broker_extensions)
            ]
            txn_day = txn.anchor.astimezone(HK).date() if txn.anchor else None
            day_calls = [
                rec
                for rec in broker_calls
                if txn_day is None
                or (
                    rec.call_started_at is not None
                    and rec.call_started_at.astimezone(HK).date() == txn_day
                )
            ]
            window_calls = [rec for rec in broker_calls if _recording_in_window(txn, rec, params)]
            if not day_calls:
                unmatched_reasons[tid] = "no_broker_recordings_day"
            elif not window_calls:
                unmatched_reasons[tid] = "no_recordings_in_window"
            else:
                unmatched_reasons[tid] = "no_matching_recording"
            fallback_calls = window_calls
        else:
            unmatched_reasons[tid] = "no_matching_recording"
            fallback_calls = contexts

        top = sorted(by_txn.get(tid, []), key=lambda x: x[0], reverse=True)[:3]
        candidates[tid] = [
            {
                "instruction_id": instr.id,
                "recording_id": instr.recording_id,
                "score": round(score, 4),
                "stock_code": instr.stock_code,
                "side": instr.side,
                "quantity": instr.quantity,
                "price": instr.price,
                "client": instr.client_name_raw,
                "broker_name": instr.broker_name,
                "original_filename": instr.original_filename,
                "call_started_at": instr.call_started_at.isoformat()
                if instr.call_started_at
                else None,
                "conflicts": breakdown.get("conflict_fields", []),
                "high_agreement_fields": breakdown.get("high_agreement_fields", []),
            }
            for score, instr, breakdown in top
        ]
        existing_recordings = {candidate["recording_id"] for candidate in candidates[tid]}
        nearest_calls = sorted(
            (rec for rec in fallback_calls if rec.id not in existing_recordings),
            key=lambda rec: (
                abs(((txn.anchor or rec.call_started_at) - rec.call_started_at).total_seconds())
                if rec.call_started_at
                else float("inf")
            ),
        )
        for rec in nearest_calls[: max(0, 3 - len(candidates[tid]))]:
            candidates[tid].append(
                {
                    "instruction_id": None,
                    "recording_id": rec.id,
                    "score": None,
                    "stock_code": None,
                    "side": None,
                    "quantity": None,
                    "price": None,
                    "client": None,
                    "broker_name": rec.broker_name,
                    "original_filename": rec.original_filename,
                    "call_started_at": rec.call_started_at.isoformat()
                    if rec.call_started_at
                    else None,
                    "conflicts": [],
                    "high_agreement_fields": [],
                }
            )

    suspicious_ids = set(suspicious)
    suspicious_recordings = {instr.recording_id for instr in instrs if instr.id in suspicious_ids}
    stats = {
        "txns_total": len(txns),
        "txns_excluded_channel": excluded,
        "instructions_total": len(instrs),
        "matched_auto": sum(1 for m in matched if m.status == "auto_matched"),
        "matched_needs_review": sum(1 for m in matched if m.status == "needs_review"),
        "txn_no_recording": len(txn_no_recording),
        "recording_no_txn_suspicious": len(suspicious_recordings),
        "recording_no_txn_suspicious_instructions": len(suspicious),
        "recording_no_txn_info": len(zero_instr_recordings),
    }
    return EngineResult(
        matched=matched,
        txn_no_recording=txn_no_recording,
        suspicious_instructions=suspicious,
        info_recordings=list(zero_instr_recordings),
        stats=stats,
        candidates=candidates,
        unmatched_reasons=unmatched_reasons,
    )
