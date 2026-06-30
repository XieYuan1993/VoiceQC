"""Insights: conversation-analytics rollups for the management / RCA dashboard.

Aggregates the LATEST completed evaluation per recording in the active project
(respecting the broker row-level scope) into sentiment mix, complaint rate +
top categories, top topics and intents, and a daily trend.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.db_models import Broker, Evaluation, Recording, User

from app.db import get_session
from app.deps import current_user, resolve_project_id
from app.routers.recordings import _apply_scope, _attention_ids, _scope_extensions
from app.schemas import (
    AgentDetailOut,
    AgentScorecard,
    AgentScorecardsOut,
    AgentSummary,
    AgentTrendPoint,
    AnalyticsOut,
    LabelCount,
    ReviewQueueCounts,
    ReviewQueueItem,
    ReviewQueueOut,
    TrendPoint,
)

router = APIRouter(prefix="/api/insights", tags=["insights"])

HK = ZoneInfo("Asia/Hong_Kong")
_MIN_DT = datetime.min.replace(tzinfo=timezone.utc)  # sort sentinel for null call times

# Sentiment buckets in a fixed worst -> best display order.
_SENTIMENT_ORDER = ["frustrated", "negative", "mixed", "neutral", "positive"]


def _norm_intent(s: str) -> str:
    """Light normalisation so free-text intents that differ only by case,
    whitespace or a trailing period collapse into one bucket."""
    return " ".join(s.strip().rstrip(".").lower().split())


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalyticsOut:
    extensions = await _scope_extensions(session, user)

    # Latest completed run per recording in the project (+ broker row-level scope).
    latest = (
        select(
            Evaluation.recording_id.label("rid"),
            func.max(Evaluation.run_seq).label("seq"),
        )
        .join(Recording, Recording.id == Evaluation.recording_id)
        .where(Recording.project_id == project_id, Evaluation.status == "completed")
        .group_by(Evaluation.recording_id)
    )
    latest = _apply_scope(latest, extensions)
    sub = latest.subquery()

    rows = (
        await session.execute(
            select(
                Evaluation.sentiment_label,
                Evaluation.sentiment_score,
                Evaluation.is_complaint,
                Evaluation.complaint_category,
                Evaluation.topics,
                Evaluation.customer_intent,
                Evaluation.checklist_score,
                Evaluation.correctness_score,
                Evaluation.correctness_findings,
                Recording.call_started_at,
            )
            .join(
                sub,
                and_(
                    Evaluation.recording_id == sub.c.rid,
                    Evaluation.run_seq == sub.c.seq,
                ),
            )
            .join(Recording, Recording.id == Evaluation.recording_id)
        )
    ).all()

    sentiment_c: Counter[str] = Counter()
    category_c: Counter[str] = Counter()
    topic_c: Counter[str] = Counter()
    intent_c: Counter[str] = Counter()
    score_sum = 0.0
    score_n = 0
    complaint_count = 0
    analyzed = 0  # calls whose latest run carries analytics (non-null sentiment)
    adh_sum = 0.0
    adh_n = 0
    corr_sum = 0.0
    corr_n = 0
    incorrect_calls = 0
    trend: dict[str, dict[str, float]] = {}

    for (
        label, score, is_comp, category, topics, intent,
        adherence, correctness, corr_findings, started,
    ) in rows:
        if label:
            sentiment_c[label] += 1
            analyzed += 1
        if adherence is not None:
            adh_sum += float(adherence)
            adh_n += 1
        if correctness is not None:
            corr_sum += float(correctness)
            corr_n += 1
        if corr_findings and any(
            isinstance(f, dict) and f.get("verdict") == "incorrect" for f in corr_findings
        ):
            incorrect_calls += 1
        if score is not None:
            score_sum += float(score)
            score_n += 1
        if is_comp:
            complaint_count += 1
            if category:
                category_c[category.strip()] += 1
        for t in topics or []:
            if isinstance(t, str) and t.strip():
                topic_c[t.strip()] += 1
        if intent and intent.strip():
            intent_c[_norm_intent(intent)] += 1
        if started is not None:
            key = started.date().isoformat()
            b = trend.setdefault(key, {"calls": 0, "complaints": 0, "ssum": 0.0, "sn": 0})
            b["calls"] += 1
            if is_comp:
                b["complaints"] += 1
            if score is not None:
                b["ssum"] += float(score)
                b["sn"] += 1

    evaluated = len(rows)
    return AnalyticsOut(
        evaluated_calls=evaluated,
        analyzed_calls=analyzed,
        avg_sentiment=round(score_sum / score_n, 2) if score_n else None,
        sentiment=[
            LabelCount(label=lbl, count=sentiment_c[lbl])
            for lbl in _SENTIMENT_ORDER
            if sentiment_c[lbl]
        ],
        complaint_count=complaint_count,
        complaint_rate=round(complaint_count / analyzed, 3) if analyzed else 0.0,
        complaint_categories=[LabelCount(label=k, count=v) for k, v in category_c.most_common(8)],
        top_topics=[LabelCount(label=k, count=v) for k, v in topic_c.most_common(10)],
        top_intents=[LabelCount(label=k, count=v) for k, v in intent_c.most_common(8)],
        trend=[
            TrendPoint(
                date=d,
                calls=int(b["calls"]),
                complaints=int(b["complaints"]),
                avg_sentiment=round(b["ssum"] / b["sn"], 2) if b["sn"] else None,
            )
            for d, b in sorted(trend.items())
        ],
        avg_adherence=round(adh_sum / adh_n, 1) if adh_n else None,
        avg_correctness=round(corr_sum / corr_n, 1) if corr_n else None,
        incorrect_answer_calls=incorrect_calls,
    )


def _latest_completed_sub(project_id: uuid.UUID, extensions: set[str] | None):
    """Subquery: (recording_id, run_seq) of each recording's latest completed run
    in the project, honouring the broker row-level scope."""
    latest = (
        select(
            Evaluation.recording_id.label("rid"),
            func.max(Evaluation.run_seq).label("seq"),
        )
        .join(Recording, Recording.id == Evaluation.recording_id)
        .where(Recording.project_id == project_id, Evaluation.status == "completed")
        .group_by(Evaluation.recording_id)
    )
    return _apply_scope(latest, extensions).subquery()


def _review_reasons(is_comp, checklist, corr_findings, risk_flags) -> list[str]:
    """The review-need signals an evaluation carries; mirrors recordings._attention_ids()."""
    reasons: list[str] = []
    if is_comp:
        reasons.append("complaint")
    if corr_findings and any(
        isinstance(f, dict) and f.get("verdict") == "incorrect" for f in corr_findings
    ):
        reasons.append("wrong_answer")
    if risk_flags and any(
        isinstance(f, dict) and f.get("severity") == "critical" for f in risk_flags
    ):
        reasons.append("critical_risk")
    if checklist is not None and checklist < 50:
        reasons.append("low_adherence")
    return reasons


async def _agent_rollup(
    session: AsyncSession,
    project_id: uuid.UUID,
    extensions: set[str] | None,
    only_agent: str | None = None,
) -> dict[str, dict]:
    """Aggregate each recording's latest run by broker extension, with per-day buckets."""
    sub = _latest_completed_sub(project_id, extensions)
    rows = (
        await session.execute(
            select(
                Recording.broker_ext,
                Evaluation.overall_score,
                Evaluation.checklist_score,
                Evaluation.correctness_score,
                Evaluation.is_complaint,
                Evaluation.correctness_findings,
                Recording.call_started_at,
            )
            .join(sub, and_(Evaluation.recording_id == sub.c.rid, Evaluation.run_seq == sub.c.seq))
            .join(Recording, Recording.id == Evaluation.recording_id)
        )
    ).all()

    agg: dict[str, dict] = {}
    for broker_ext, score, adherence, correctness, is_comp, corr_findings, started in rows:
        agent = broker_ext or "unknown"
        if only_agent is not None and agent != only_agent:
            continue
        a = agg.setdefault(
            agent,
            {"calls": 0, "ssum": 0.0, "sn": 0, "adh": 0.0, "adhn": 0,
             "corr": 0.0, "corrn": 0, "comp": 0, "inc": 0, "days": {}},
        )
        a["calls"] += 1
        if score is not None:
            a["ssum"] += float(score)
            a["sn"] += 1
        if adherence is not None:
            a["adh"] += float(adherence)
            a["adhn"] += 1
        if correctness is not None:
            a["corr"] += float(correctness)
            a["corrn"] += 1
        if is_comp:
            a["comp"] += 1
        if corr_findings and any(
            isinstance(f, dict) and f.get("verdict") == "incorrect" for f in corr_findings
        ):
            a["inc"] += 1
        if started is not None:
            d = started.date().isoformat()
            b = a["days"].setdefault(d, {"calls": 0, "ssum": 0.0, "sn": 0})
            b["calls"] += 1
            if score is not None:
                b["ssum"] += float(score)
                b["sn"] += 1
    return agg


def _scorecard(agent: str, a: dict, trend_limit: int | None = None) -> AgentScorecard:
    days = sorted(a["days"].items())
    if trend_limit is not None:
        days = days[-trend_limit:]
    trend = [
        AgentTrendPoint(
            date=d,
            calls=b["calls"],
            avg_score=round(b["ssum"] / b["sn"], 1) if b["sn"] else None,
        )
        for d, b in days
    ]
    return AgentScorecard(
        agent=agent,
        calls=a["calls"],
        avg_score=round(a["ssum"] / a["sn"], 1) if a["sn"] else None,
        avg_adherence=round(a["adh"] / a["adhn"], 1) if a["adhn"] else None,
        avg_correctness=round(a["corr"] / a["corrn"], 1) if a["corrn"] else None,
        complaint_rate=round(a["comp"] / a["calls"], 3) if a["calls"] else 0.0,
        incorrect_answer_calls=a["inc"],
        trend=trend,
    )


@router.get("/agents", response_model=AgentScorecardsOut)
async def agent_scorecards(
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentScorecardsOut:
    """Per-agent (broker extension) QA rollup from each recording's latest run."""
    extensions = await _scope_extensions(session, user)
    agg = await _agent_rollup(session, project_id, extensions)
    cards = [_scorecard(agent, a, trend_limit=30) for agent, a in agg.items()]
    # Worst average score first, so the agents needing review surface at the top.
    cards.sort(key=lambda c: c.avg_score if c.avg_score is not None else 999.0)

    weighted = sum((c.avg_score or 0.0) * c.calls for c in cards if c.avg_score is not None)
    weight_n = sum(c.calls for c in cards if c.avg_score is not None)
    in_queue = (
        await session.execute(
            select(func.count()).select_from(
                _apply_scope(select(Recording.id), extensions)
                .where(Recording.project_id == project_id, Recording.id.in_(_attention_ids()))
                .subquery()
            )
        )
    ).scalar_one()
    summary = AgentSummary(
        agents=len(cards),
        calls=sum(c.calls for c in cards),
        team_avg_score=round(weighted / weight_n, 1) if weight_n else None,
        in_review_queue=int(in_queue),
    )
    return AgentScorecardsOut(agents=cards, summary=summary)


@router.get("/agents/{broker_ext}", response_model=AgentDetailOut)
async def agent_detail(
    broker_ext: str,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentDetailOut:
    """One agent's scorecard + full daily trend, for the drill-down header."""
    extensions = await _scope_extensions(session, user)
    if extensions is not None and broker_ext not in extensions:
        # 404, not 403 — don't leak agent existence to out-of-scope brokers.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    agg = await _agent_rollup(session, project_id, extensions, only_agent=broker_ext)
    a = agg.get(broker_ext)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no evaluated calls for this agent")
    card = _scorecard(broker_ext, a)  # full trend, not capped
    name: str | None = None
    if broker_ext and broker_ext != "unknown":
        name = (
            await session.execute(
                select(Broker.name).where(Broker.phone_extensions.any(broker_ext))
            )
        ).scalar_one_or_none()
    return AgentDetailOut(**card.model_dump(), name=name)


@router.get("/review-queue", response_model=ReviewQueueOut)
async def review_queue(
    reason: str | None = Query(default=None),
    broker_ext: str | None = Query(default=None),
    call_date: date | None = Query(default=None),
    sort: str = Query(default="score", pattern="^(score|recent|severity)$"),
    page: int = 1,
    page_size: int = 25,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewQueueOut:
    """Calls whose latest run needs a human check, with the reason(s) and score —
    filterable by reason / agent / date, sortable, paginated."""
    extensions = await _scope_extensions(session, user)
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    sub = _latest_completed_sub(project_id, extensions)
    stmt = (
        select(
            Recording,
            Evaluation.overall_score,
            Evaluation.checklist_score,
            Evaluation.is_complaint,
            Evaluation.correctness_findings,
            Evaluation.risk_flags,
        )
        .select_from(Evaluation)
        .join(sub, and_(Evaluation.recording_id == sub.c.rid, Evaluation.run_seq == sub.c.seq))
        .join(Recording, Recording.id == Evaluation.recording_id)
    )
    if broker_ext:
        stmt = stmt.where(Recording.broker_ext == broker_ext)
    if call_date is not None:
        start = datetime.combine(call_date, time.min, tzinfo=HK)
        stmt = stmt.where(
            Recording.call_started_at >= start,
            Recording.call_started_at < start + timedelta(days=1),
        )
    rows = (await session.execute(stmt)).all()

    # (recording, score, reasons) for every flagged call under the agent/date filter.
    kept: list[tuple] = []
    for rec, score, checklist, is_comp, corr_findings, risk_flags in rows:
        reasons = _review_reasons(is_comp, checklist, corr_findings, risk_flags)
        if reasons:
            kept.append((rec, float(score) if score is not None else None, reasons))

    counts = ReviewQueueCounts(
        all=len(kept),
        complaint=sum(1 for _, _, rs in kept if "complaint" in rs),
        wrong_answer=sum(1 for _, _, rs in kept if "wrong_answer" in rs),
        critical_risk=sum(1 for _, _, rs in kept if "critical_risk" in rs),
        low_adherence=sum(1 for _, _, rs in kept if "low_adherence" in rs),
    )

    if reason:
        kept = [t for t in kept if reason in t[2]]

    sev = {"complaint": 0, "critical_risk": 0, "wrong_answer": 1, "low_adherence": 2}
    if sort == "recent":
        kept.sort(key=lambda t: t[0].call_started_at or _MIN_DT, reverse=True)
    elif sort == "severity":
        kept.sort(key=lambda t: (min(sev[r] for r in t[2]), t[1] is None, t[1] or 0.0))
    else:  # score — lowest first surfaces the worst calls
        kept.sort(key=lambda t: (t[1] is None, t[1] if t[1] is not None else 0.0))

    total = len(kept)
    page_rows = kept[(page - 1) * page_size : page * page_size]
    items = [
        ReviewQueueItem(
            recording_id=rec.id,
            original_filename=rec.original_filename,
            broker_ext=rec.broker_ext,
            direction=rec.direction,
            call_started_at=rec.call_started_at,
            duration_seconds=float(rec.duration_seconds) if rec.duration_seconds is not None else None,
            status=rec.status,
            overall_score=score,
            reasons=reasons,
        )
        for rec, score, reasons in page_rows
    ]
    return ReviewQueueOut(
        items=items, total=total, page=page, page_size=page_size, counts=counts
    )
