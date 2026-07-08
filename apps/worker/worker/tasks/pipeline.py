"""Per-recording pipeline stages: normalize (ffmpeg) -> transcribe (STT batch).

Every task is idempotent: it re-reads DB state and no-ops if its stage is
already done — safe under acks_late redelivery. Terminal failures mark the
recording `failed` with the stage name and re-raise so the chain stops; the
batch rollup then counts it without blocking sibling recordings.

Phase 2 inserts an `evaluate` stage; until then transcribe completes the
recording.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from voiceqa_shared import gcs
from voiceqa_shared.db_models import (
    IndustryTerm,
    Recording,
    SttUsage,
    Transcript,
    TranscriptSegment,
)

from worker import audio
from worker.asr import factory
from worker.asr.base import AdaptationPhrase, ChannelFile
from worker.celery_app import app
from worker.db import SessionLocal, get_setting
from worker.mono_speaker_repair import repair_mono_transcript
from worker.settings import settings

_STAGE_BY_STATUS = {
    "uploaded": "convert",
    "converting": "convert",
    "transcribing": "stt",
    "evaluating": "eval",
}


def _touch_updated_at(recording_id: str) -> None:
    """Refresh updated_at so sweep_stuck doesn't interfere during Celery retries."""
    with SessionLocal() as session:
        rec = session.get(Recording, uuid.UUID(recording_id))
        if rec:
            rec.updated_at = datetime.now(UTC)
            session.commit()


def _fail(recording_id: str, stage: str, exc: Exception) -> None:
    from worker.tasks.batch import update_progress

    with SessionLocal() as session:
        rec = session.get(Recording, uuid.UUID(recording_id))
        if rec is None:
            return
        rec.status = "failed"
        rec.failed_stage = stage
        rec.error = str(exc)[:2000]
        rec.attempts += 1
        batch_id = str(rec.batch_id)
        session.commit()
    logger.error("recording {} failed at {}: {}", recording_id, stage, exc)
    update_progress.delay(batch_id)


@lru_cache(maxsize=4)
def _adapter(provider: str):
    return factory.create(provider)


# ---------------------------------------------------------------------------
# Stage 1: normalize
# ---------------------------------------------------------------------------


@app.task(name="voiceqa.pipeline.normalize_audio", bind=True)
def normalize_audio(self, recording_id: str) -> None:
    with SessionLocal() as session:
        rec = session.get(Recording, uuid.UUID(recording_id))
        if rec is None or rec.status not in ("uploaded", "converting"):
            return  # already past this stage (redelivery) or gone
        rec.status = "converting"
        session.commit()
        raw_uri = rec.gcs_uri_raw
        broker_channel = get_setting(session, rec.project_id, "audio.broker_channel", "left")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "raw_input"
            gcs.download_uri_to_file(raw_uri, str(raw_path))
            info = audio.probe(str(raw_path))

            uris: dict[str, str | None] = {"broker": None, "customer": None, "mono": None}
            if info.channels >= 2:
                left, right = tmp / "left.flac", tmp / "right.flac"
                audio.split_stereo_to_flac(str(raw_path), str(left), str(right))
                broker_path, customer_path = (
                    (left, right) if broker_channel == "left" else (right, left)
                )
                uris["broker"] = gcs.upload_file(
                    f"normalized/{recording_id}/broker.flac", str(broker_path)
                )
                uris["customer"] = gcs.upload_file(
                    f"normalized/{recording_id}/customer.flac", str(customer_path)
                )
            else:
                mono = tmp / "mono.flac"
                audio.to_mono_flac(str(raw_path), str(mono))
                uris["mono"] = gcs.upload_file(f"normalized/{recording_id}/mono.flac", str(mono))

        with SessionLocal() as session:
            rec = session.get(Recording, uuid.UUID(recording_id))
            rec.gcs_uri_broker = uris["broker"]
            rec.gcs_uri_customer = uris["customer"]
            rec.gcs_uri_mono = uris["mono"]
            rec.duration_seconds = round(info.duration_seconds, 2)
            rec.sample_rate = info.sample_rate
            rec.channels = info.channels
            rec.format = info.format
            rec.status = "transcribing"
            session.commit()
        logger.info(
            "normalized {}: {}ch {}Hz {:.1f}s", recording_id, info.channels,
            info.sample_rate, info.duration_seconds,
        )
    except Exception as e:
        err_str = str(e)
        # GCS / network transients: retry with backoff before permanently failing.
        transient = any(
            m in err_str
            for m in ("timed out", "ReadTimeout", "ConnectTimeout", "TimeoutError",
                      "503", "429", "connection aborted", "Connection reset")
        )
        if transient and self.request.retries < 8:
            _touch_updated_at(recording_id)
            raise self.retry(countdown=30, exc=e) from e
        _fail(recording_id, "convert", e)
        raise


# ---------------------------------------------------------------------------
# Stage 2: transcribe (start LRO once, then poll via task retry)
# ---------------------------------------------------------------------------


def _adaptation_phrases(session, project_id) -> list[AdaptationPhrase]:
    """Build STT speech-adaptation phrases from industry terms.

    Settings-driven because, empirically, aggressive phrase boosting on
    chirp_2 batch causes degenerate output — repetition loops and the boost
    vocabulary getting hallucinated into the transcript (seen on real Quam
    audio). So `asr.adaptation` defaults to "off"; "stock_only" biases just
    stock names/codes (the high-value, low-collision terms) at a modest
    `asr.adaptation_boost`; "all" is the original behaviour.
    """
    mode = get_setting(session, project_id, "asr.adaptation", "off")
    if mode not in ("stock_only", "all"):
        return []
    boost = float(get_setting(session, project_id, "asr.adaptation_boost", 5))
    stmt = select(IndustryTerm).where(
        IndustryTerm.project_id == project_id, IndustryTerm.active.is_(True)
    )
    if mode == "stock_only":
        stmt = stmt.where(IndustryTerm.category == "stock")
    terms = session.execute(stmt).scalars().all()
    terms.sort(key=lambda t: (t.category != "stock", t.canonical))
    phrases: list[AdaptationPhrase] = []
    seen: set[str] = set()
    for term in terms:
        for value in [term.canonical, *term.aliases]:
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                phrases.append(AdaptationPhrase(value=value, boost=term.boost or boost))
    return phrases


def _slice_text_by_words(text: str, words: list, lo: int, hi: int) -> str:
    """Return the slice of ``text`` covering words[lo:hi], punctuation included.

    Word tokens are located in the (cleaned, punctuated) sentence text in order,
    so a split run keeps its commas/periods instead of being rebuilt bare.
    """
    pos = 0
    starts: list[int] = []
    for _b, wt in words:
        idx = text.find(wt, pos)
        if idx < 0:
            idx = pos
        starts.append(idx)
        pos = idx + len(wt)
    a = starts[lo]
    b = starts[hi] if hi < len(words) else len(text)
    return text[a:b].strip(" 　,，.。、")  # noqa: RUF001 (trim CJK + ASCII punctuation)


_CJK_DIGITS = {
    "零": "0", "〇": "0", "一": "1", "二": "2", "三": "3", "四": "4",  # noqa: RUF001
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}
_DIGIT_RUN = re.compile("[" + "".join(_CJK_DIGITS) + "]{3,}")


def _spoken_digits_to_arabic(text: str) -> str:
    """Render runs of 3+ spoken digit characters as Arabic, digit by digit
    (二零三二九八 -> 203298) — stock codes, account and phone numbers. Qwen's ITN
    doesn't fire for Cantonese ("yue"), so this does it deterministically while
    keeping everything else verbatim. The length-3 guard leaves non-numeric 一/二
    (一定, 第二) untouched; positional amounts (三十五, 八千) use 十/百/千, which
    aren't digit characters, so those runs never reach length 3 and stay spoken.
    """
    return _DIGIT_RUN.sub(lambda m: "".join(_CJK_DIGITS[c] for c in m.group()), text)


def _interleave_turns(seg_pairs: list[tuple[str, object]]) -> list[tuple[str, int, str]]:
    """Order per-channel segments into true conversational turns.

    A segment is split where the OTHER channel produces a SUBSTANTIAL utterance
    inside its span (≥ MIN_INTERRUPT_MS) — a real interruption, not a brief
    backchannel or word-level cross-talk. Splitting on every other-channel word
    instead shreds simultaneous speech into single characters. Telling a real
    interruption from a same-speaker pause needs both channels at once, which is
    what dual-channel audio provides. With no word timings (other ASR providers)
    this is just a stable start-time ordering, matching the previous behaviour.
    """
    MIN_INTERRUPT_MS = 600
    cut_sources = [
        (seg.start_ms, role)
        for role, seg in seg_pairs
        if seg.words and (seg.end_ms - seg.start_ms) >= MIN_INTERRUPT_MS
    ]

    out: list[tuple[str, int, str]] = []
    for role, seg in seg_pairs:
        words = seg.words or []
        cuts = sorted({c for c, r in cut_sources if r != role and seg.start_ms < c < seg.end_ms})
        if not words or not cuts:
            out.append((role, seg.start_ms, seg.text))
            continue
        bounds = [0]
        for i in range(1, len(words)):
            if any(words[i - 1][0] < c <= words[i][0] for c in cuts):
                bounds.append(i)
        bounds.append(len(words))
        for k in range(len(bounds) - 1):
            lo, hi = bounds[k], bounds[k + 1]
            txt = _slice_text_by_words(seg.text, words, lo, hi)
            if txt:
                out.append((role, int(words[lo][0]), txt))
    out.sort(key=lambda x: x[1])
    return out


@app.task(name="voiceqa.pipeline.transcribe", bind=True, max_retries=120)
def transcribe(
    self,
    recording_id: str,
    asr_provider_override: str | None = None,
    asr_model_override: str | None = None,
) -> None:

    with SessionLocal() as session:
        rec = session.get(Recording, uuid.UUID(recording_id))
        if rec is None or rec.status != "transcribing":
            return
        project_id = rec.project_id

        files: list[ChannelFile] = []
        if rec.gcs_uri_broker and rec.gcs_uri_customer:
            files = [
                ChannelFile(uri=rec.gcs_uri_broker, channel_role="broker"),
                ChannelFile(uri=rec.gcs_uri_customer, channel_role="customer"),
            ]
        elif rec.gcs_uri_mono:
            files = [ChannelFile(uri=rec.gcs_uri_mono, channel_role="mixed")]
        if not files:
            _fail(recording_id, "stt", RuntimeError("no normalized audio uris"))
            return

        provider = asr_provider_override or get_setting(session, project_id, "asr.provider", "google")
        adapter = _adapter(provider)
        try:
            if not rec.stt_operation_name:
                language_mode = rec.language_mode or get_setting(
                    session, project_id, "asr.language_mode", "auto"
                )
                model = (
                    asr_model_override
                    or get_setting(session, project_id, "asr.model", settings.GOOGLE_STT_MODEL)
                )
                # Results come back in the operation response (chirp inline /
                # Gemini synchronous) and are persisted straight to Postgres —
                # nothing is written to the bucket besides the audio itself.
                rec.stt_operation_name = adapter.start_batch(
                    files,
                    language_mode=language_mode,
                    adaptation_phrases=_adaptation_phrases(session, project_id),
                    model=model,
                )
                rec.language_mode = language_mode
                session.commit()

            results = adapter.fetch_result(rec.stt_operation_name)
        except Exception as e:
            transient = type(e).__name__ in (
                "TooManyRequests",
                "ServiceUnavailable",
                "DeadlineExceeded",
                "InternalServerError",
            ) or any(
                marker in str(e)
                for marker in (
                    "429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500",
                    "timed out", "ReadTimeout", "ConnectTimeout", "TimeoutError",
                    "connection aborted", "Connection reset",
                )
            )
            if transient:
                _touch_updated_at(recording_id)
                raise self.retry(countdown=60, exc=e) from e
            _fail(recording_id, "stt", e)
            raise

        if results is None:
            # LRO still running — poll again shortly. acks_late + the stored
            # operation name make this resumable across worker restarts.
            raise self.retry(countdown=20)

        role_by_uri = {f.uri: f.channel_role for f in files}
        errors = [r.error for r in results if r.error]
        segments: list[tuple[str, object]] = []  # (role, SegmentResult)
        languages: dict[str, int] = {}
        billed = 0.0
        model = (
            asr_model_override
            or get_setting(session, project_id, "asr.model", settings.GOOGLE_STT_MODEL)
        )
        for r in results:
            role = role_by_uri.get(r.uri, "mixed")
            billed += r.billed_seconds
            if r.language_detected:
                languages[r.language_detected] = languages.get(r.language_detected, 0) + 1
            for seg in r.segments:
                segments.append((role, seg))

        if not segments and errors:
            _fail(recording_id, "stt", RuntimeError("; ".join(errors)[:1000]))
            return

        lines = []
        for role, start_ms, text in _interleave_turns(segments):
            mm, ss = divmod(start_ms // 1000, 60)
            lines.append(f"[{mm:02d}:{ss:02d}] {role}: {_spoken_digits_to_arabic(text)}")
        full_text = "\n".join(lines)

        is_mono_mixed = bool(rec.gcs_uri_mono and not rec.gcs_uri_broker and not rec.gcs_uri_customer)
        if is_mono_mixed and get_setting(session, project_id, "asr.mono_speaker_repair", True):
            repair_model = get_setting(
                session,
                project_id,
                "asr.mono_speaker_repair_model",
                get_setting(session, project_id, "llm.model", settings.VERTEX_LLM_MODEL),
            )
            full_text = repair_mono_transcript(full_text, model=repair_model, session=session)

        # Replace any prior transcript (reprocess path).
        old = session.execute(
            select(Transcript.id).where(Transcript.recording_id == rec.id)
        ).scalar_one_or_none()
        if old is not None:
            session.execute(delete(Transcript).where(Transcript.id == old))

        transcript = Transcript(
            recording_id=rec.id,
            stt_model=model,
            language_detected=max(languages, key=languages.get) if languages else None,
            full_text=full_text,
            billed_seconds=round(billed, 2),
        )
        session.add(transcript)
        session.flush()
        session.add_all(
            TranscriptSegment(
                transcript_id=transcript.id,
                channel_role=role,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text=seg.text,
                language=seg.language,
                confidence=seg.confidence,
            )
            for role, seg in segments
        )

        stmt = pg_insert(SttUsage).values(
            day=datetime.now(UTC).date(),
            provider=provider,
            model=model,
            audio_seconds=int(billed),
            requests=1,
        )
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_stt_usage_day_provider_model",
                set_={
                    "audio_seconds": SttUsage.audio_seconds + int(billed),
                    "requests": SttUsage.requests + 1,
                },
            )
        )

        rec.status = "evaluating"
        rec.error = None
        rec.failed_stage = None
        if errors:
            rec.error = f"partial: {'; '.join(errors)[:500]}"
        session.commit()

    logger.info("transcribed {}: {} segments, {:.0f}s billed", recording_id, len(segments), billed)
    # Stage 3 (Phase 2): evaluation. Local import — evaluate.py imports
    # _fail from this module.
    from worker.tasks.evaluate import evaluate as evaluate_task

    evaluate_task.delay(recording_id)
