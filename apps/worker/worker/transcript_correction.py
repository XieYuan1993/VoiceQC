"""Project-scoped LLM correction for ASR transcripts.

The corrector is intentionally conservative: it may repair terminology and
cross-check repeated identifiers, but it cannot change speaker labels,
timestamps, or unsupported numbers.  Any failed or unsafe chunk falls back to
the original ASR text.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from loguru import logger
from sqlalchemy import select
from voiceqa_shared.db_models import IndustryTerm
from voiceqa_shared.llm_usage import record_llm_usage_sync

from worker.db import get_setting
from worker.llm import factory
from worker.settings import settings

_MAX_CHUNK_CHARS = 3_000
_CONTEXT_TURNS = 3
_MIN_TEXT_SIMILARITY = 0.55
_DIGIT_GROUP_RE = re.compile(r"\d(?:[\d\s-]*\d)?")
_CJK_NUMBER_GROUP_RE = re.compile(r"[零〇一二三四五六七八九兩两幺]{3,}")
_ALNUM_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)
_SERVICE_GREETING = re.compile(r"請問.{0,15}(?:幫到|幫助|幫您|幫你)")
_SELF_INTRODUCTION = re.compile(r"我(?:係|是|叫|姓)")
_GREETING_ARTIFACTS = {"5萬份保險": "富衛保險", "5万份保险": "富衛保險"}
_TRANSIENT_ERROR_MARKERS = (
    "timed out",
    "timeout",
    "connection",
    "10054",
    "10060",
    "429",
    "503",
    "unavailable",
    "reset",
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                    "numeric_evidence_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["id", "text", "numeric_evidence_ids"],
            },
        }
    },
    "required": ["turns"],
}


@dataclass(frozen=True)
class TranscriptTurn:
    role: str
    start_ms: int
    text: str


@lru_cache(maxsize=4)
def _adapter(provider: str):
    if provider == "dashscope":
        return factory.create(provider, enable_thinking=False)
    return factory.create(provider)


def _project_glossary(session, project_id) -> list[dict[str, Any]]:
    terms = (
        session.execute(
            select(IndustryTerm)
            .where(
                IndustryTerm.project_id == project_id,
                IndustryTerm.active.is_(True),
            )
            .order_by(IndustryTerm.category, IndustryTerm.canonical)
        )
        .scalars()
        .all()
    )
    return [
        {
            "term": term.canonical,
            "category": term.category,
            "aliases": [str(alias) for alias in (term.aliases or []) if str(alias).strip()],
        }
        for term in terms[:300]
    ]


def _chunks(turns: list[TranscriptTurn]) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    start = 0
    size = 0
    for index, turn in enumerate(turns):
        turn_size = len(turn.text) + 80
        if index > start and size + turn_size > _MAX_CHUNK_CHARS:
            chunks.append((start, index))
            start = index
            size = 0
        size += turn_size
    if start < len(turns):
        chunks.append((start, len(turns)))
    return chunks


def _digit_groups(text: str) -> list[str]:
    return [re.sub(r"\D", "", match.group()) for match in _DIGIT_GROUP_RE.finditer(text)]


def _cjk_number_groups(text: str) -> list[str]:
    return _CJK_NUMBER_GROUP_RE.findall(text)


def _compact(text: str) -> str:
    return _ALNUM_RE.sub("", text).casefold()


def _numeric_change_is_supported(
    original: str,
    corrected: str,
    evidence_ids: list[int],
    indexed_turns: dict[int, TranscriptTurn],
    *,
    turn_id: int,
    allow_numeric_changes: bool,
) -> bool:
    if _cjk_number_groups(original) != _cjk_number_groups(corrected):
        return False
    before = _digit_groups(original)
    after = _digit_groups(corrected)
    if before == after:
        return True
    if not allow_numeric_changes:
        return False
    # Formatting an identifier into multiple groups is itself unsafe: brackets,
    # spaces, or punctuation can change how an account or policy number is read.
    if "".join(before) == "".join(after):
        return False
    if not before or not after or not evidence_ids:
        return False

    changed_numbers = list((Counter(after) - Counter(before)).elements())
    if not changed_numbers:
        return False

    valid_evidence_ids = {
        evidence_id
        for evidence_id in evidence_ids
        if evidence_id != turn_id and evidence_id in indexed_turns
    }
    if not valid_evidence_ids:
        return False

    def supports(turn: TranscriptTurn, number: str) -> bool:
        for observed in _digit_groups(turn.text):
            if observed == number:
                return True
            if len(number) >= 4 and number in observed:
                return True
        return False

    for number in changed_numbers:
        supporting_ids = {
            candidate_id
            for candidate_id, turn in indexed_turns.items()
            if candidate_id != turn_id and supports(turn, number)
        }
        if len(supporting_ids) < 2:
            return False
        if not supporting_ids.intersection(valid_evidence_ids):
            return False
    return True


def _text_change_is_safe(original: str, corrected: str) -> bool:
    original_compact = _compact(original)
    corrected_compact = _compact(corrected)
    if not corrected_compact:
        return False
    if not original_compact:
        return corrected_compact == original_compact
    length_ratio = len(corrected_compact) / len(original_compact)
    if not 0.55 <= length_ratio <= 1.65:
        return False
    if len(original_compact) >= 20:
        similarity = SequenceMatcher(
            None,
            original_compact,
            corrected_compact,
            autojunk=False,
        ).ratio()
        if similarity < _MIN_TEXT_SIMILARITY:
            return False
    return True


def _repair_greeting_term(
    turn: TranscriptTurn,
    candidate: str,
    glossary: list[dict[str, Any]],
    replacements: list[dict[str, str]],
) -> str:
    if turn.role != "broker" or not _SERVICE_GREETING.search(turn.text):
        return turn.text
    if not _SELF_INTRODUCTION.search(turn.text):
        return turn.text
    approved = {item.get("term") for item in glossary}
    rules = {
        item["wrong"]: item["correct"]
        for item in replacements
        if item.get("wrong") and item.get("correct") in approved
        and "opening greeting" in item.get("context", "").lower()
    }
    if "富衛" in approved and any(value == "富衛" for value in rules.values()):
        rules.update({wrong: correct for wrong, correct in _GREETING_ARTIFACTS.items() if correct in approved})
    for wrong, correct in sorted(rules.items(), key=lambda item: -len(item[0])):
        match = re.match(r"(?:[\s\uff0c,\u3002\uff01!]*(?:喂|餵|嗯|哦|早晨|午安|您好|你好)[\s\uff0c,\u3002\uff01!]*)?" + re.escape(wrong), turn.text)
        if not match or match.end() > 18:
            continue
        if correct not in candidate[:18] or not _SERVICE_GREETING.search(candidate):
            continue
        start = match.end() - len(wrong)
        return turn.text[:start] + correct + turn.text[match.end():]
    return turn.text


def _build_prompt(
    context: list[dict[str, Any]],
    target_ids: list[int],
    glossary: list[dict[str, Any]],
    replacements: list[dict[str, str]],
    *,
    allow_numeric_changes: bool,
) -> str:
    numeric_rule = (
        """A numeric or identifier value may change only when at least TWO other
   supplied turns independently repeat or read back the corrected value
   unambiguously. Put all supporting source turn ids in numeric_evidence_ids.
   Keep identifiers as one contiguous digit string; do not add brackets, spaces,
   or separators. Otherwise preserve the original digits exactly."""
        if allow_numeric_changes
        else """Never alter, add, remove, regroup, or reformat any Arabic digit
   sequence or any spoken Chinese digit sequence. Preserve every original number
   exactly. You may correct surrounding non-numeric words, but
   numeric_evidence_ids must remain empty."""
    )
    return f"""
You are a conservative transcript proofreader for Hong Kong life-insurance calls.
Correct ASR mistakes using the dialogue context, approved glossary, and known
wrong-to-correct examples. The output must remain a verbatim transcript, not a
summary or translation.

Rules:
1. Return only target turns whose text actually needs correction. Omit unchanged
   target turns. Return no items for context-only ids.
2. Change text only. Never change, infer, or output timestamps or speaker roles.
3. Preserve Cantonese, Mandarin, English, tone, repetitions, and incomplete speech.
4. Prefer approved glossary spellings for brands, products, people, and insurance terms.
5. Known replacement rules are contextual examples, not unconditional string replaces.
   Apply them only when the surrounding sentence clearly refers to that approved term.
6. Check names, policy/account/customer numbers, phone numbers, dates, amounts, and
   percentages carefully. Keep leading zeroes. Do not invent a value.
7. {numeric_rule}
8. For non-numeric corrections, return numeric_evidence_ids as an empty array.
9. If uncertain, keep the ASR wording unchanged.

Target ids:
{json.dumps(target_ids, ensure_ascii=False)}

Approved glossary:
{json.dumps(glossary, ensure_ascii=False)}

Known ASR error examples:
{json.dumps(replacements, ensure_ascii=False)}

Dialogue turns (context_only=true items provide evidence but must not be returned):
{json.dumps(context, ensure_ascii=False)}
""".strip()


def correct_turns_with_llm(
    turns: list[TranscriptTurn],
    *,
    adapter,
    model: str,
    glossary: list[dict[str, Any]],
    replacements: list[dict[str, str]],
    session,
    allow_numeric_changes: bool = False,
    repair_greeting_terms: bool = True,
) -> tuple[list[TranscriptTurn], bool]:
    """Correct turns and return ``(turns, changed)``."""
    if not turns or sum(len(turn.text) for turn in turns) < 20:
        return turns, False

    indexed_turns = {index: turn for index, turn in enumerate(turns)}
    corrected = list(turns)
    successful_chunks = 0
    changed_turns = 0

    for start, end in _chunks(turns):
        context_start = max(0, start - _CONTEXT_TURNS)
        context_end = min(len(turns), end + _CONTEXT_TURNS)
        target_ids = list(range(start, end))
        context = [
            {
                "id": index,
                "timestamp_ms": turn.start_ms,
                "speaker": turn.role,
                "text": turn.text,
                "context_only": not start <= index < end,
            }
            for index, turn in enumerate(
                turns[context_start:context_end],
                start=context_start,
            )
        ]
        parsed: dict[str, Any] | None = None
        for attempt in range(2):
            try:
                parsed, input_tokens, output_tokens = adapter.generate_structured(
                    _build_prompt(
                        context,
                        target_ids,
                        glossary,
                        replacements,
                        allow_numeric_changes=allow_numeric_changes,
                    ),
                    _SCHEMA,
                    model=model,
                    temperature=0.0,
                )
                record_llm_usage_sync(
                    session,
                    callsite="transcript_post_correction",
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                break
            except Exception as exc:
                transient = any(
                    marker in str(exc).casefold() for marker in _TRANSIENT_ERROR_MARKERS
                )
                if attempt == 0 and transient:
                    logger.warning(
                        "transcript post-correction chunk {}:{} transient failure; retrying: {}",
                        start,
                        end,
                        exc,
                    )
                    time.sleep(2)
                    continue
                logger.warning(
                    "transcript post-correction chunk {}:{} failed; keeping ASR text: {}",
                    start,
                    end,
                    exc,
                )
                break
        if parsed is None:
            continue

        items = parsed.get("turns") if isinstance(parsed, dict) else None
        if not isinstance(items, list):
            logger.warning("transcript post-correction returned no turn list")
            continue

        valid_items = [
            item
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        ]
        by_id = {item["id"]: item for item in valid_items}
        if len(by_id) != len(valid_items) or not set(by_id) <= set(target_ids):
            logger.warning(
                "transcript post-correction returned unexpected ids for chunk {}:{}",
                start,
                end,
            )
            continue

        successful_chunks += 1
        for turn_id, item in by_id.items():
            original = turns[turn_id]
            candidate = " ".join(str(item.get("text") or "").splitlines()).strip()
            raw_evidence = item.get("numeric_evidence_ids") or []
            evidence_ids = [value for value in raw_evidence if isinstance(value, int)]
            text_safe = _text_change_is_safe(original.text, candidate)
            numbers_safe = _numeric_change_is_supported(
                original.text,
                candidate,
                evidence_ids,
                indexed_turns,
                turn_id=turn_id,
                allow_numeric_changes=allow_numeric_changes,
            )
            if not text_safe or not numbers_safe:
                brand_text = (
                    _repair_greeting_term(original, candidate, glossary, replacements)
                    if repair_greeting_terms else original.text
                )
                if brand_text == original.text:
                    logger.debug("rejected unsafe transcript rewrite for turn {}", turn_id)
                    continue
                candidate = brand_text
            if candidate != original.text:
                corrected[turn_id] = TranscriptTurn(
                    role=original.role,
                    start_ms=original.start_ms,
                    text=candidate,
                )
                changed_turns += 1

    if successful_chunks:
        logger.info(
            "transcript post-correction completed: {} chunk(s), {} changed turn(s)",
            successful_chunks,
            changed_turns,
        )
    return corrected, changed_turns > 0


def correct_project_transcript(
    turns: list[tuple[str, int, str]],
    *,
    session,
    project_id,
) -> tuple[list[tuple[str, int, str]], bool]:
    """Run project-configured post-correction without making it pipeline-fatal."""
    if not get_setting(session, project_id, "asr.post_correction_enabled", False):
        return turns, False

    provider = get_setting(
        session,
        project_id,
        "asr.post_correction_provider",
        settings.LLM_PROVIDER,
    )
    default_model = (
        settings.DASHSCOPE_LLM_MODEL
        if provider == "dashscope"
        else settings.VERTEX_LLM_MODEL
    )
    model = get_setting(
        session,
        project_id,
        "asr.post_correction_model",
        get_setting(session, project_id, "llm.model", default_model),
    )
    raw_replacements = get_setting(
        session,
        project_id,
        "asr.post_correction_replacements",
        [],
    )
    allow_numeric_changes = get_setting(
        session,
        project_id,
        "asr.post_correction_allow_numeric_changes",
        False,
    )
    replacements = [
        {
            "wrong": str(item.get("wrong") or "").strip(),
            "correct": str(item.get("correct") or "").strip(),
            "context": str(item.get("context") or "").strip(),
        }
        for item in raw_replacements
        if isinstance(item, dict)
        and str(item.get("wrong") or "").strip()
        and str(item.get("correct") or "").strip()
    ]
    typed_turns = [TranscriptTurn(role, start_ms, text) for role, start_ms, text in turns]
    try:
        corrected, changed = correct_turns_with_llm(
            typed_turns,
            adapter=_adapter(str(provider)),
            model=str(model),
            glossary=_project_glossary(session, project_id),
            replacements=replacements,
            session=session,
            allow_numeric_changes=bool(allow_numeric_changes),
        )
    except Exception as exc:
        logger.warning("transcript post-correction failed; keeping ASR text: {}", exc)
        return turns, False
    return [(turn.role, turn.start_ms, turn.text) for turn in corrected], changed
