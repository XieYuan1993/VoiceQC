"""Scoped, optimistic transcript amendments and contextual hotword annotations."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import (
    AppSetting,
    IndustryTerm,
    Recording,
    Transcript,
    TranscriptSegment,
    User,
)

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import EVALS_REVIEW, TERMS_WRITE, has_perm, require
from app.routers.recordings import _get_scoped

router = APIRouter(prefix="/api/recordings", tags=["transcript-edits"])


class TranscriptEditIn(BaseModel):
    expected_text: str = Field(max_length=20000)
    text: str = Field(min_length=1, max_length=20000)
    wrong: str = Field(default="", max_length=200)
    correct: str = Field(default="", max_length=200)
    category: Literal["jargon", "person", "other"] = "jargon"
    context: str = Field(default="", max_length=1000)


def validate_edit(payload, original, can_write_terms):
    if payload.expected_text != original:
        raise HTTPException(409, "This transcript changed; refresh before editing")
    if not payload.text.strip():
        raise HTTPException(400, "Transcript text cannot be empty")
    if payload.wrong or payload.correct:
        if not can_write_terms:
            raise HTTPException(403, "Hotword changes require term-write permission")
        if not payload.correct.strip():
            raise HTTPException(400, "A correct hotword is required")
        if payload.wrong.strip() and payload.wrong.strip() not in original:
            raise HTTPException(400, "The annotated word must occur in this transcript sentence")
        if (
            not payload.wrong.strip()
            and payload.correct.strip() not in original
            and payload.correct.strip() not in payload.text
        ):
            raise HTTPException(400, "The hotword must occur in the original or amended sentence")


def format_transcript(segments):
    return "\n".join(
        f"[{segment.start_ms // 60000:02d}:{segment.start_ms // 1000 % 60:02d}] {segment.channel_role}: {segment.text}"
        for segment in segments
    )


@router.patch("/{recording_id}/transcript/segments/{segment_id}")
async def edit_segment(
    recording_id: uuid.UUID,
    segment_id: int,
    payload: TranscriptEditIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(EVALS_REVIEW)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    await _get_scoped(session, user, recording_id, project_id)
    rec = (
        await session.execute(
            select(Recording)
            .where(Recording.id == recording_id, Recording.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if rec.status in ("uploaded", "converting", "transcribing", "evaluating"):
        raise HTTPException(409, "Wait for recording processing to finish before editing")
    transcript = (
        await session.execute(select(Transcript).where(Transcript.recording_id == rec.id))
    ).scalar_one_or_none()
    if transcript is None:
        raise HTTPException(404, "Transcript not found")
    segment = (
        await session.execute(
            select(TranscriptSegment).where(
                TranscriptSegment.id == segment_id, TranscriptSegment.transcript_id == transcript.id
            )
        )
    ).scalar_one_or_none()
    if segment is None:
        raise HTTPException(404, "Transcript sentence not found")
    validate_edit(payload, segment.text, has_perm(user.role, TERMS_WRITE))
    old = segment.text
    changed = old != payload.text.strip()
    if payload.wrong or payload.correct:
        # Serialize edits across recordings in this project, including the case
        # where no settings row exists yet. Wrong spellings are NOT ASR aliases.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"transcript-hotwords:{project_id}"},
        )
        wrong, correct = payload.wrong.strip(), payload.correct.strip()
        rule = {
            "wrong": wrong,
            "correct": correct,
            "context": payload.context.strip() or old[:1000],
        }
        if wrong and wrong != correct:
            setting = await session.get(
                AppSetting, (project_id, "asr.post_correction_replacements")
            )
            rules = list(setting.value or []) if setting else []
            if any(item.get("wrong") == wrong and item.get("correct") != correct for item in rules):
                raise HTTPException(
                    409,
                    "This hotword already has a different correction; review it in the evaluator",
                )
            if not any(
                item.get("wrong") == wrong and item.get("correct") == correct for item in rules
            ):
                rules.append(rule)
            if len(rules) > 500:
                raise HTTPException(400, "This project already has 500 correction annotations")
            if setting:
                setting.value, setting.updated_by = rules, user.id
            else:
                session.add(
                    AppSetting(
                        project_id=project_id,
                        key="asr.post_correction_replacements",
                        value=rules,
                        updated_by=user.id,
                    )
                )
        statement = insert(IndustryTerm).values(
            project_id=project_id,
            canonical=correct,
            category=payload.category,
            aliases=[],
            active=True,
            notes="Transcript hotword annotation",
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_industry_terms_project_id_canonical", set_={"active": True}
            )
        )
        log_audit(
            session,
            action="transcript.hotword",
            user_id=user.id,
            actor_email=user.email,
            object_type="transcript",
            object_id=str(transcript.id),
            details={"segment_id": str(segment.id), **rule},
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
    if changed:
        segment.text = payload.text.strip()
        await session.flush()
        segments = (
            (
                await session.execute(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.transcript_id == transcript.id)
                    .order_by(TranscriptSegment.start_ms, TranscriptSegment.id)
                )
            )
            .scalars()
            .all()
        )
        transcript.full_text = format_transcript(segments)
        log_audit(
            session,
            action="transcript.edit",
            user_id=user.id,
            actor_email=user.email,
            object_type="transcript",
            object_id=str(transcript.id),
            details={"recording_id": str(rec.id), "segment_id": str(segment.id), "start_ms": segment.start_ms,
                     "before": old, "after": segment.text},
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
    await session.commit()
    return {"changed": changed, "hotword_saved": bool(payload.correct)}
