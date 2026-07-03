"""LLM speaker-role repair for mono recordings.

This is a pragmatic fallback for single-channel calls: ASR can only produce
`mixed` turns, so we ask the LLM to infer broker/customer roles from the
conversation content. These labels are inferred, not acoustically verified.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from loguru import logger
from voiceqa_shared.llm_usage import record_llm_usage_sync

from worker.llm import factory
from worker.settings import settings

_LINE_RE = re.compile(r"^\[(?P<ts>\d{2}:\d{2})\]\s*mixed:\s*(?P<text>.*)$")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string"},
                    "speaker": {"type": "string", "enum": ["broker", "customer", "unknown"]},
                    "text": {"type": "string"},
                },
                "required": ["timestamp", "speaker", "text"],
            },
        }
    },
    "required": ["turns"],
}


@lru_cache(maxsize=1)
def _adapter():
    if settings.LLM_FALLBACK_PROVIDER:
        return factory.create_with_fallback(
            settings.LLM_PROVIDER,
            settings.LLM_FALLBACK_PROVIDER,
            fallback_model=settings.DASHSCOPE_LLM_MODEL,
        )
    return factory.create(settings.LLM_PROVIDER)


def _build_prompt(transcript_text: str) -> str:
    return f"""
You are repairing speaker labels for a single-channel Hong Kong brokerage call.

The ASR transcript below has every turn labelled "mixed" because the recording
has only one audio channel. Infer the most likely role for each turn from the
content and dialogue flow:
- broker: account executive / staff / person accepting, confirming, reading back, or submitting orders
- customer: client / caller / person giving instructions, account details, confirmations, questions
- unknown: only when the role is genuinely unclear

Keep every timestamp unchanged. Preserve the original wording as much as
possible. Do not add, remove, translate, or summarise content. Split a line into
multiple turns only when it clearly contains both speakers in one ASR segment.
Return JSON only.

Transcript:
{transcript_text}
""".strip()


def repair_mono_transcript(
    transcript_text: str,
    *,
    model: str,
    session,
) -> str:
    """Return a broker/customer labelled transcript, or the original on failure."""
    if "mixed:" not in transcript_text:
        return transcript_text
    if len(transcript_text.strip()) < 20:
        return transcript_text

    try:
        parsed, in_tok, out_tok = _adapter().generate_structured(
            _build_prompt(transcript_text),
            _SCHEMA,
            model=model,
            temperature=0.0,
        )
        record_llm_usage_sync(
            session,
            callsite="mono_speaker_repair",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
    except Exception as e:
        logger.warning("mono speaker repair failed; keeping mixed transcript: {}", e)
        return transcript_text

    out: list[str] = []
    for item in parsed.get("turns") or []:
        if not isinstance(item, dict):
            continue
        ts = str(item.get("timestamp") or "").strip()
        speaker = str(item.get("speaker") or "unknown").strip()
        text = str(item.get("text") or "").strip()
        if speaker not in {"broker", "customer", "unknown"} or not text:
            continue
        if not re.fullmatch(r"\d{2}:\d{2}", ts):
            match = _LINE_RE.search(text)
            ts = match.group("ts") if match else "00:00"
        out.append(f"[{ts}] {speaker}: {text}")

    if not out:
        return transcript_text
    return "\n".join(out)
