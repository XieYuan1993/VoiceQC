"""Evaluation results: list per recording, re-run, review, per-criterion override."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import (
    Evaluation,
    EvaluationResult,
    TradeInstruction,
    Transcript,
    UploadBatch,
    User,
)

from app import queue
from app.db import get_session
from app.deps import ClientMeta, client_meta
from app.permissions import EVALS_REVIEW, TRANSCRIPTS_READ, require
from app.routers.recordings import _get_scoped
from app.schemas import (
    EvalRerunOut,
    EvaluationOut,
    EvidenceOut,
    ResultOut,
    ResultOverrideIn,
    ReviewIn,
    TradeOut,
)

router = APIRouter(prefix="/api", tags=["evaluations"])


def _result_out(r: EvaluationResult) -> ResultOut:
    return ResultOut(
        criterion_key=r.criterion_key,
        criterion_name=r.criterion_name,
        score=float(r.score) if r.score is not None else None,
        passed=r.passed,
        rationale=r.rationale,
        evidence=[EvidenceOut(**e) for e in (r.evidence or []) if isinstance(e, dict)],
        severity=r.severity,
        override_score=float(r.override_score) if r.override_score is not None else None,
        override_passed=r.override_passed,
        override_note=r.override_note,
        overridden_at=r.overridden_at,
    )


def _trade_out(t: TradeInstruction) -> TradeOut:
    extra_fields = t.extra_fields if isinstance(t.extra_fields, dict) else {}
    return TradeOut(
        id=t.id,
        seq=t.seq,
        stock_code=t.stock_code,
        stock_name_raw=t.stock_name_raw,
        interaction_type=str(extra_fields.get("interaction_type") or "order_instruction"),
        side=t.side,
        quantity=float(t.quantity) if t.quantity is not None else None,
        price=float(t.price) if t.price is not None else None,
        price_type=t.price_type,
        client_name_raw=t.client_name_raw,
        client_account_raw=t.client_account_raw,
        time_in_call_ms=t.time_in_call_ms,
        confidence=t.confidence,
        evidence_quote=t.evidence_quote,
    )


async def _evaluation_out(session: AsyncSession, ev: Evaluation) -> EvaluationOut:
    results = (
        (
            await session.execute(
                select(EvaluationResult)
                .where(EvaluationResult.evaluation_id == ev.id)
                .order_by(EvaluationResult.criterion_key)
            )
        )
        .scalars()
        .all()
    )
    trades = (
        (
            await session.execute(
                select(TradeInstruction)
                .where(TradeInstruction.evaluation_id == ev.id)
                .order_by(TradeInstruction.seq)
            )
        )
        .scalars()
        .all()
    )
    return EvaluationOut(
        id=ev.id,
        recording_id=ev.recording_id,
        run_seq=ev.run_seq,
        status=ev.status,
        llm_model=ev.llm_model,
        summary=ev.summary,
        overall_score=float(ev.overall_score) if ev.overall_score is not None else None,
        risk_flags=list(ev.risk_flags or []),
        extracted_call_fields=dict(ev.extracted_call_fields or {}),
        sentiment_label=ev.sentiment_label,
        sentiment_score=float(ev.sentiment_score) if ev.sentiment_score is not None else None,
        customer_intent=ev.customer_intent,
        topics=list(ev.topics or []),
        is_complaint=ev.is_complaint,
        complaint_category=ev.complaint_category,
        follow_up_actions=list(ev.follow_up_actions or []),
        criteria_snapshot=list(ev.criteria_snapshot or []),
        fields_snapshot=list(ev.fields_snapshot or []),
        checklist_snapshot=list(ev.checklist_snapshot or []),
        checklist_results=list(ev.checklist_results or []),
        checklist_score=float(ev.checklist_score) if ev.checklist_score is not None else None,
        correctness_findings=list(ev.correctness_findings or []),
        correctness_score=float(ev.correctness_score) if ev.correctness_score is not None else None,
        review_status=ev.review_status,
        review_note=ev.review_note,
        reviewed_at=ev.reviewed_at,
        error=ev.error,
        input_tokens=ev.input_tokens,
        output_tokens=ev.output_tokens,
        created_at=ev.created_at,
        completed_at=ev.completed_at,
        results=[_result_out(r) for r in results],
        trades=[_trade_out(t) for t in trades],
    )


@router.get("/recordings/{recording_id}/evaluations", response_model=list[EvaluationOut])
async def list_evaluations(
    recording_id: uuid.UUID,
    user: User = Depends(require(TRANSCRIPTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[EvaluationOut]:
    rec = await _get_scoped(session, user, recording_id)
    evaluations = (
        (
            await session.execute(
                select(Evaluation)
                .where(Evaluation.recording_id == rec.id)
                .order_by(Evaluation.run_seq.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await _evaluation_out(session, ev) for ev in evaluations]


@router.post("/recordings/{recording_id}/evaluations", response_model=EvalRerunOut)
async def rerun_evaluation(
    recording_id: uuid.UUID,
    user: User = Depends(require(EVALS_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> EvalRerunOut:
    """Re-evaluate under the CURRENT criteria/fields config (new run_seq)."""
    rec = await _get_scoped(session, user, recording_id)
    if rec.status in ("uploaded", "converting", "transcribing", "evaluating"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"recording is busy ({rec.status})")
    has_transcript = (
        await session.execute(select(Transcript.id).where(Transcript.recording_id == rec.id))
    ).scalar_one_or_none() is not None
    if not has_transcript:
        raise HTTPException(status.HTTP_409_CONFLICT, "no transcript — reprocess from stt first")

    rec.status = "evaluating"
    rec.failed_stage = None
    rec.error = None
    rec.attempts = 0
    # Reactivate the batch so its rollup status recomputes (else it stays frozen).
    batch = await session.get(UploadBatch, rec.batch_id)
    if batch is not None and batch.status in ("completed", "completed_with_errors", "failed"):
        batch.status = "processing"
    log_audit(
        session, action="evaluation.rerun", user_id=user.id, actor_email=user.email,
        object_type="recording", object_id=str(rec.id), ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send_pipeline_chain(str(rec.id), from_stage="eval")
    return EvalRerunOut(recording_id=rec.id, status="evaluating")


@router.post("/evaluations/{evaluation_id}/review", response_model=EvaluationOut)
async def review_evaluation(
    evaluation_id: uuid.UUID,
    payload: ReviewIn,
    user: User = Depends(require(EVALS_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> EvaluationOut:
    ev = await session.get(Evaluation, evaluation_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evaluation not found")
    if ev.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"evaluation is {ev.status}")
    ev.review_status = "approved" if payload.action == "approve" else "overridden"
    ev.review_note = payload.note
    ev.reviewed_by = user.id
    ev.reviewed_at = datetime.now(UTC)
    log_audit(
        session, action="evaluation.review", user_id=user.id, actor_email=user.email,
        object_type="evaluation", object_id=str(ev.id),
        details={"action": payload.action, "note": payload.note},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return await _evaluation_out(session, ev)


@router.post(
    "/evaluations/{evaluation_id}/results/{criterion_key}/override",
    response_model=EvaluationOut,
)
async def override_result(
    evaluation_id: uuid.UUID,
    criterion_key: str,
    payload: ResultOverrideIn,
    user: User = Depends(require(EVALS_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> EvaluationOut:
    ev = await session.get(Evaluation, evaluation_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evaluation not found")
    result = (
        await session.execute(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_id == evaluation_id,
                EvaluationResult.criterion_key == criterion_key,
            )
        )
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "criterion result not found")
    if payload.passed is None and payload.score is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "provide passed or score")

    result.override_passed = payload.passed
    result.override_score = payload.score
    result.override_note = payload.note
    result.overridden_by = user.id
    result.overridden_at = datetime.now(UTC)
    ev.review_status = "overridden"
    log_audit(
        session, action="evaluation.result_override", user_id=user.id, actor_email=user.email,
        object_type="evaluation", object_id=str(ev.id),
        details={
            "criterion_key": criterion_key,
            "passed": payload.passed,
            "score": payload.score,
            "note": payload.note,
        },
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return await _evaluation_out(session, ev)
