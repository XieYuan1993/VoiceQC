"""Stage 3: evaluate — one Gemini structured call per recording.

Admin config (eval_criteria + extraction_fields) drives BOTH the prompt and
the response schema, so config changes alter the contract, not just prose.
Every evaluation snapshots the config it ran under; re-runs get a new
run_seq and past evaluations stay untouched (DESIGN.md §5).

Budget guard: when today's llm_usage total exceeds budget.llm_daily_tokens
the recording fails soft with failed_stage='budget' — retryable tomorrow.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from loguru import logger
from sqlalchemy import func, select, text
from voiceqa_shared.db_models import (
    ChecklistItem,
    EvalCriterion,
    Evaluation,
    EvaluationResult,
    ExtractionField,
    IndustryTerm,
    KbChunk,
    Project,
    Recording,
    TradeInstruction,
    Transaction,
    Transcript,
)
from voiceqa_shared.llm_usage import llm_tokens_today_sync, record_llm_usage_sync

from worker.celery_app import app
from worker.db import SessionLocal, engine, get_setting
from worker.kb import cosine
from worker.llm import factory
from worker.llm.embeddings import Embedder
from worker.settings import settings
from worker.tasks.pipeline import _fail
from worker.trade_normalization import (
    MAX_SECURITY_CANDIDATES,
    normalize_stock_code,
    normalize_trade_item,
)

SIDES = {"buy", "sell", "amend", "cancel", "unknown"}
PRICE_TYPES = {"market", "limit", "unknown"}
TRADE_INTERACTION_TYPES = {"order_instruction", "notification", "inquiry"}
SEVERITIES = {"info", "warning", "critical"}
CHANNELS = {"broker", "customer", "mixed"}
SENTIMENTS = {"positive", "neutral", "negative", "frustrated", "mixed"}
VERDICTS = {"correct", "incorrect", "unsupported"}
KB_TOP_K = 6  # KB chunks retrieved per call for answer-correctness
KB_QUERY_CHARS = 2000  # transcript prefix used as the retrieval query (embed token cap)
TRADE_CHUNK_CHARS = 6_000
TRADE_CHUNK_OVERLAP_LINES = 2
TRADE_CANDIDATES_MAX = MAX_SECURITY_CANDIDATES
TRADE_CONTEXT_WINDOW_MINUTES = 60
TRADE_CONTEXT_MAX_CALLS = 3
TRADE_CONTEXT_CHARS = 4_000

_ACCOUNT_MARKERS = re.compile(
    r"(?:account|acct|a/c|戶口|户口|賬戶|账户|客戶號|客户号)",
    re.IGNORECASE,
)
_SIX_DIGIT_ACCOUNT = re.compile(r"(?<!\d)(\d(?:[\s-]?\d){5})(?![\s-]?\d)")
_ACCOUNT_LABEL_MARKERS = re.compile(
    r"(?:account|acct|a/c|\u6236\u53e3|\u6237\u53e3|\u6236\u865f|\u6237\u53f7|"
    r"\u8cec\u6236|\u8d26\u6237|\u5ba2\u6236\u865f|\u5ba2\u6237\u53f7)",
    re.IGNORECASE,
)
_IDENTITY_MARKERS = re.compile(
    r"(?:identity|id\s*(?:no|number)?|\u8eab\u4efd\u8b49|\u8eab\u4efd\u8bc1|"
    r"\u8eab\u5206\u8b49|\u8eab\u5206\u8bc1)",
    re.IGNORECASE,
)
_LABELLED_ACCOUNT = re.compile(r"(?<!\d)(\d(?:[\s-]?\d){4,5})(?![\s-]?\d)")
_LABELLED_ACCOUNT_PREFIX = re.compile(r"(?<!\d)(\d{6})(?=\d{4,})")
_ACCOUNT_WITH_888_SUFFIX = re.compile(
    r"(?<!\d)(\d(?:[\s-]?\d){5})(?:[\s-]*(?:hyphen|\u9ed1|i)?[\s-]*888)(?!\d)",
    re.IGNORECASE,
)
_SEVEN_DIGIT_ACCOUNT_WITH_REPEAT = re.compile(r"(?<!\d)(\d{7})(?!\d)")
_TIMESTAMP = re.compile(r"\[(\d{2}):(\d{2})\]")


@lru_cache(maxsize=1)
def _adapter():
    if settings.LLM_FALLBACK_PROVIDER:
        return factory.create_with_fallback(
            settings.LLM_PROVIDER,
            settings.LLM_FALLBACK_PROVIDER,
            fallback_model=settings.DASHSCOPE_LLM_MODEL,
        )
    return factory.create(settings.LLM_PROVIDER)


# ---------------------------------------------------------------------------
# Prompt + schema builders.
# ---------------------------------------------------------------------------


def _glossary_block(terms: list[IndustryTerm]) -> str:
    if not terms:
        return "(no glossary defined)"
    lines = []
    for t in terms:
        aliases = ", ".join(t.aliases or [])
        code = f" (stock code {t.stock_code})" if t.stock_code else ""
        lines.append(f"- {t.canonical}{code}" + (f" — aliases: {aliases}" if aliases else ""))
    return "\n".join(lines)


def _criteria_block(criteria: list[EvalCriterion]) -> str:
    if not criteria:
        return "(no criteria configured — skip scoring, still extract trades and summarise)"
    lines = []
    for c in criteria:
        scoring = "pass/fail" if c.score_type == "pass_fail" else "score 1-5"
        lines.append(f"- key={c.key} | {c.name} | {scoring}\n  Rubric: {c.description}")
    return "\n".join(lines)


def _call_fields_block(fields: list[ExtractionField]) -> str:
    if not fields:
        return "(none)"
    lines = []
    for f in fields:
        type_desc = f.field_type
        if f.field_type == "enum" and f.enum_options:
            type_desc = "one of: " + ", ".join(f.enum_options)
        lines.append(f"- {f.key} ({type_desc}): {f.description or f.label}")
    return "\n".join(lines)


def _checklist_block(items: list[ChecklistItem]) -> str:
    lines = []
    for it in items:
        req = "required" if it.required else "optional"
        desc = f" — {it.description}" if it.description else ""
        lines.append(f"- key={it.key} | {it.label} ({req}){desc}")
    return "\n".join(lines)


def _retrieve_kb_context(transcript_text: str, chunks: list[KbChunk]) -> str | None:
    """Embed the call as a query and return the top-K most similar KB chunks,
    formatted for the prompt. None when there is nothing relevant."""
    if not chunks or not transcript_text.strip():
        return None
    q_emb = Embedder().embed_query(transcript_text[:KB_QUERY_CHARS])
    ranked = sorted(
        ((cosine(q_emb, c.embedding), c) for c in chunks),
        key=lambda t: t[0],
        reverse=True,
    )
    top = [c for score, c in ranked[:KB_TOP_K] if score > 0]
    if not top:
        return None
    return "\n\n".join(f"[KB {i + 1}] {c.content}" for i, c in enumerate(top))


def build_prompt(
    rec: Recording,
    transcript_text: str,
    criteria: list[EvalCriterion],
    call_fields: list[ExtractionField],
    terms: list[IndustryTerm],
    checklist: list[ChecklistItem],
    *,
    context: str | None,
    trade_module: bool,
    kb_context: str | None = None,
) -> str:
    channel_note = (
        "Speakers are channel-separated and labelled by role."
        if rec.gcs_uri_broker
        else "Speaker labels are unavailable (single channel) — attribute roles from content."
    )
    started = rec.call_started_at.isoformat() if rec.call_started_at else "unknown"
    domain_line = f"\n{context.strip()}" if context and context.strip() else ""

    # Trade-instruction + caller extraction are part of the optional
    # trade-reconciliation module — only requested when the project enables it.
    trade_block = ""
    if trade_module:
        trade_block = (
            "\n- Extract EVERY trade instruction the client gives — a call may contain several; "
            "amendments and cancellations count. Resolve stocks to their numeric code via the "
            "glossary where possible (e.g. 騰訊 -> 700). Numbers as digits. The transcript may "
            "garble names and digits — give the most plausible reading and reflect uncertainty in "
            '"confidence" (0-1). If the call contains no trade instruction, "trade_instructions" is [].'
            "\n- caller: the CLIENT's own name and account number as stated anywhere in the call "
            '(the client identifying themselves, e.g. "我係陳大文 戶口…"). This is the client, NOT '
            "the agent. Use null for either field if it is not stated."
        )

    checklist_section = (
        f"\n\n## Checklist — required items the agent must cover\n{_checklist_block(checklist)}"
        if checklist
        else ""
    )
    checklist_instruction = (
        '\n- checklist: for EACH checklist item above, by its key, set "covered" true if the agent '
        "addressed or asked it anywhere in the call (semantic match — exact wording is NOT required) "
        "and false otherwise; when covered, give a short evidence_quote and approx_ms."
        if checklist
        else ""
    )

    kb_section = (
        f"\n\n## Knowledge base — authoritative policy/product references\n{kb_context}"
        if kb_context
        else ""
    )
    correctness_instruction = (
        "\n- correctness: check the agent's factual claims AGAINST the knowledge base above and "
        "list EACH one — INCLUDE claims the agent got right (verdict correct), not only mistakes; "
        "confirming accuracy matters as much as catching errors. A claim is any specific checkable "
        "assertion the agent makes that the KB covers — especially a security's stock code or name, "
        "an order type, trading hours, settlement, fees, notifications or platform features (e.g. "
        "the agent naming a stock together with its code, even if recognition is imperfect). For "
        "each: claim (what the agent asserted, in English); verdict correct|incorrect|unsupported — "
        "mark correct ONLY when a KB line directly confirms the specific claim, incorrect when a KB "
        "line contradicts it, and unsupported when the agent asserts something the KB does not "
        "actually state; kb_quote: copy the supporting or contradicting line VERBATIM from the "
        "Knowledge base section above (never from the glossary or transcript), or null when "
        "unsupported; evidence_quote: the agent's verbatim words, with approx_ms; confidence 0-1. "
        "Judge ONLY against the KB above. If the agent made no checkable claim, return []."
        if kb_context
        else ""
    )

    return f"""You are a meticulous call-quality and compliance evaluator.{domain_line}
Evaluate the recorded call below.

## Call metadata
- started: {started} | agent: {rec.broker_ext or "unknown"} | direction: {rec.direction}
- duration: {rec.duration_seconds or "unknown"}s
- {channel_note}

## Glossary (use to resolve domain-specific references)
{_glossary_block(terms)}

## Transcript (timestamps [mm:ss]; produced by ASR and may contain recognition errors)
{transcript_text}

## Evaluation criteria
{_criteria_block(criteria)}

## Call-level fields to extract
{_call_fields_block(call_fields)}{checklist_section}{kb_section}

## Instructions
- Score EVERY criterion listed above, by its key. pass_fail criteria: set "passed" \
true/false and leave "score" null. scale_1_5 criteria: set "score" 1-5 and leave "passed" null. \
If the transcript gives no basis to judge a criterion, set both null and say so in the rationale.
- rationale: 1-3 sentences, in English.
- evidence: 1-3 VERBATIM quotes from the transcript (copy the exact characters, including any \
ASR errors), each with its channel and the [mm:ss] timestamp converted to milliseconds.{trade_block}
- summary: 2-4 sentences in English: who called, what they wanted, what happened.
- risk_flags: anything compliance-relevant beyond the criteria (client confusion, disputes, \
pressure, mentions of off-channel dealing), with severity info|warning|critical. Usually [].
- sentiment: the CUSTOMER's overall sentiment — label one of positive|neutral|negative|frustrated|\
mixed, and score from -1.0 (very negative) to 1.0 (very positive). Judge the customer, not the agent.
- intent: the customer's primary reason for the call as a SHORT canonical category of 2-4 words, \
lower-case, WITHOUT specifics like stock, product or person names — so similar calls share one \
label (e.g. "place order", "cancel order", "account enquiry", "price query", "complaint"). null if \
unclear.
- topics: 1-5 SHORT canonical tags (1-2 words, Title Case) for what the call covered — products, \
issues, processes (e.g. "Order Placement", "Account Balance", "IPO"). [] if none stand out.
- complaint: is_complaint true ONLY if the customer expressed dissatisfaction or a grievance about \
the product, service, or staff (not a mere question); category a short label when true (e.g. \
"service delay", "mis-selling", "claim handling"), else null.
- follow_up_actions: 0-5 concrete actions someone must take after the call (e.g. "send policy \
document", "escalate to claims team"). [] if none.{checklist_instruction}{correctness_instruction}
- Judge on the balance of evidence; do not invent content that is not in the transcript."""


def _trade_chunks(text: str, max_chars: int = TRADE_CHUNK_CHARS) -> list[str]:
    """Split long transcripts on timestamped lines with a small overlap."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0
    for line in text.splitlines():
        line_chars = len(line) + 1
        if current and current_chars + line_chars > max_chars:
            chunks.append("\n".join(current))
            current = current[-TRADE_CHUNK_OVERLAP_LINES:]
            current_chars = sum(len(item) + 1 for item in current)
        if line_chars > max_chars:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_chars = 0
            chunks.extend(line[i : i + max_chars] for i in range(0, len(line), max_chars))
            continue
        current.append(line)
        current_chars += line_chars
    if current:
        chunks.append("\n".join(current))
    return [chunk for chunk in chunks if chunk.strip()] or [text]


def _candidate_securities(session, rec: Recording) -> list[tuple[str, str | None]]:
    """Most frequent booked securities near this call, used only as ASR hints."""
    if rec.call_started_at is None:
        return []
    anchor = func.coalesce(Transaction.ordered_at, Transaction.executed_at)
    rows = session.execute(
        select(Transaction.stock_code, Transaction.stock_name, Transaction.raw).where(
            anchor >= rec.call_started_at - timedelta(minutes=15),
            anchor <= rec.call_started_at + timedelta(hours=6),
        )
    ).all()
    counts: Counter[tuple[str, str | None]] = Counter()
    for stock_code, stock_name, raw in rows:
        raw_code = (raw or {}).get("stock_code") if isinstance(raw, dict) else None
        code = _normalize_stock_code(stock_code or raw_code)
        if code:
            counts[(code, stock_name or None)] += 1
    return [security for security, _count in counts.most_common(TRADE_CANDIDATES_MAX)]


def _six_digit_account(text: str | None) -> str | None:
    """Find a six-digit client account, preferring explicit labels and call openings."""
    if not text:
        return None
    normalized = str(text)
    stripped = normalized.strip()
    if re.fullmatch(r"\d{1,6}", stripped):
        return stripped.zfill(6)

    # Quam commonly states a six-digit main account followed by the 888
    # sub-account suffix. Handle both "214353888" and "214353 hyphen 888"
    # before generic matching sees later identity-card digits.
    suffix_match = _ACCOUNT_WITH_888_SUFFIX.search(normalized)
    if suffix_match:
        return re.sub(r"\D", "", suffix_match.group(1))

    for marker in _ACCOUNT_LABEL_MARKERS.finditer(normalized):
        line_start = normalized.rfind("\n", 0, marker.start()) + 1
        line_end = normalized.find("\n", marker.end())
        if line_end < 0:
            line_end = len(normalized)
        before = normalized[max(line_start, marker.start() - 40) : marker.start()]
        preceding = list(_LABELLED_ACCOUNT.finditer(before))
        if preceding:
            return re.sub(r"\D", "", preceding[-1].group(1)).zfill(6)
        match = _LABELLED_ACCOUNT.search(normalized, marker.end(), min(line_end, marker.end() + 80))
        if match:
            between = normalized[marker.end() : match.start()]
            if _IDENTITY_MARKERS.search(between):
                continue
            return re.sub(r"\D", "", match.group(1)).zfill(6)
        prefix = _LABELLED_ACCOUNT_PREFIX.search(
            normalized,
            marker.end(),
            min(len(normalized), marker.end() + 160),
        )
        if prefix:
            return prefix.group(1)

    # ASR sometimes duplicates one spoken digit (600120 -> 6001220). Only
    # repair an opening seven-digit token when removing either repeated digit
    # produces the same unambiguous six-digit value.
    for match in _SEVEN_DIGIT_ACCOUNT_WITH_REPEAT.finditer(normalized[:600]):
        candidate = match.group(1)
        repairs = {
            candidate[:index] + candidate[index + 1 :]
            for index in range(1, len(candidate))
            if candidate[index] != "0" and candidate[index] == candidate[index - 1]
        }
        if len(repairs) == 1:
            return repairs.pop()

    # Unlabelled accounts are accepted only near the start of the call. Reject
    # common ASR quote concatenations such as 484|485, 116|117 and 102|103.
    for match in _SIX_DIGIT_ACCOUNT.finditer(normalized[:2_000]):
        line_start = normalized.rfind("\n", 0, match.start()) + 1
        line = normalized[line_start : match.start()]
        timestamp = _TIMESTAMP.search(line)
        if timestamp and int(timestamp.group(1)) * 60 + int(timestamp.group(2)) > 12:
            continue
        if _IDENTITY_MARKERS.search(line[-40:]):
            continue
        candidate = re.sub(r"\D", "", match.group(1))
        first, second = int(candidate[:3]), int(candidate[3:])
        if abs(first - second) <= 2 or int(candidate) % 100 == 0:
            continue
        return candidate
    return None


def _context_excerpt(text: str) -> str:
    if len(text) <= TRADE_CONTEXT_CHARS:
        return text
    half = TRADE_CONTEXT_CHARS // 2
    return f"{text[:half]}\n[...context shortened...]\n{text[-half:]}"


def _prior_trade_context(session, rec: Recording, account: str | None) -> str | None:
    """Return earlier calls for the same broker and verified account as read-only context."""
    if not account or rec.call_started_at is None:
        return None
    broker_filter = None
    if rec.broker_ext:
        broker_filter = Recording.broker_ext == rec.broker_ext
    elif rec.broker_name:
        broker_filter = Recording.broker_name == rec.broker_name
    if broker_filter is None:
        return None

    rows = session.execute(
        select(Recording, Transcript)
        .join(Transcript, Transcript.recording_id == Recording.id)
        .where(
            Recording.project_id == rec.project_id,
            Recording.id != rec.id,
            broker_filter,
            Recording.call_started_at < rec.call_started_at,
            Recording.call_started_at
            >= rec.call_started_at - timedelta(minutes=TRADE_CONTEXT_WINDOW_MINUTES),
        )
        .order_by(Recording.call_started_at.desc())
        .limit(12)
    ).all()
    matched = []
    for prior, transcript in rows:
        prior_account = _six_digit_account(prior.client_account) or _six_digit_account(
            transcript.full_text
        )
        if prior_account == account:
            matched.append((prior, transcript))
            if len(matched) >= TRADE_CONTEXT_MAX_CALLS:
                break
    if not matched:
        return None
    blocks = []
    for prior, transcript in reversed(matched):
        blocks.append(
            f"[Prior call started {prior.call_started_at.isoformat()} | account {account}]\n"
            f"{_context_excerpt(transcript.full_text)}"
        )
    return "\n\n".join(blocks)


def build_trade_prompt(
    rec: Recording,
    transcript_text: str,
    terms: list[IndustryTerm],
    candidate_securities: list[tuple[str, str | None]],
    *,
    chunk_index: int,
    chunk_count: int,
    account_hint: str | None = None,
    prior_context: str | None = None,
) -> str:
    candidates = (
        "\n".join(
            f"- {code}" + (f" | {name}" if name else "") for code, name in candidate_securities
        )
        or "(none available)"
    )
    started = rec.call_started_at.isoformat() if rec.call_started_at else "unknown"
    account_note = account_hint or "unknown"
    prior_section = (
        f"""
## Earlier calls for the same broker and verified six-digit account
This is context only. Use it solely to resolve an omitted stock reference in the CURRENT call.
Never extract or repeat an instruction that appears only in an earlier call.
{prior_context}
"""
        if prior_context
        else ""
    )
    return f"""You extract and classify securities trade discussions from Cantonese, Mandarin, and English call transcripts.

## Call metadata
- started: {started} | broker: {rec.broker_name or rec.broker_ext or "unknown"}
- verified client account hint: {account_note}
- transcript chunk: {chunk_index}/{chunk_count}

## Known securities glossary
{_glossary_block(terms)}

## Candidate securities booked near this call
These are hints for repairing ASR errors, not proof that an order was spoken. Never invent an
instruction merely because a candidate appears here. Codes may be Hong Kong numeric codes or US
alphabetic tickers such as NVDA, RKLB, BRK.B, or BF-B.
{candidates}
{prior_section}

## CURRENT call transcript
{transcript_text}

## Extraction rules
- Extract EVERY trade-related event in this chunk, in speaking order, and classify interaction_type:
  - order_instruction: the client gives, authorizes, confirms, amends, or cancels an order in this
    call. A broker proposal counts only when the client clearly authorizes it.
  - notification: either speaker reports or acknowledges an order that was already placed, filled,
    partially filled, rejected, cancelled, expired, or otherwise processed before this discussion.
  - inquiry: the client asks about an existing order, execution, position, price, or status without
    giving a new instruction or authorizing a change.
- Grammatical tense and conversational purpose matter. Mentioning complete trade details is not an
  order_instruction when the speakers are only reporting or asking about an earlier transaction.
- A call may contain several interaction types. Classify each event independently. If an inquiry or
  notification leads to a new authorized order/change, emit the earlier event and the later
  order_instruction separately at their respective timestamps.
- Keep repeated orders as separate instructions when they occur at different timestamps.
- Resolve fast or concatenated speech using the glossary, candidate list, quantity, price, and context.
- Preserve US alphabetic tickers. Normalize Hong Kong numeric codes by removing leading zeros.
- For amend/cancel instructions set side to amend/cancel. Otherwise use buy/sell.
- Extract the instructed quantity, not a later filled quantity. Use null when genuinely unavailable.
- Extract client name/account whenever either speaker states who the instruction belongs to. It does
  not need to be self-identification. Copy the call-level client into each related instruction.
- A client account is exactly six digits. Prefer a six-digit number near account/戶口/賬戶 wording;
  a standalone six-digit number near the start is also likely the account. Use the verified hint above
  when present and copy it into every current-call instruction.
- If the current call omits a stock because the same client continues a discussion from an earlier
  call, inherit the stock only from the same-account context above. Do not inherit side, quantity, or
  price unless the CURRENT call states them.
- time_in_call_ms must point to the instruction's approximate transcript timestamp.
- evidence_quote must be verbatim transcript text. Reflect uncertainty in confidence (0-1).
- If this chunk contains no trade-related event, return an empty trade_instructions array.
"""


def _add_evaluation_summary_hint(prompt: str, summary: str | None) -> str:
    """Add the whole-call summary as a constrained field-recovery hint."""
    if not summary or not summary.strip():
        return prompt
    return f"""{prompt}

## Evaluation summary (secondary, model-generated hint)
{summary.strip()}

Use this summary only to fill a missing field on an instruction that is independently present in
the CURRENT call transcript. Never create an instruction solely from the summary, and never use it
to import an instruction from an earlier call. The CURRENT transcript wins on any conflict.
Evidence must remain a verbatim quote from the CURRENT transcript. If the summary was needed to
recover a field, cap that instruction's confidence at 0.65.
"""


def _merge_trade_outputs(
    outputs: list[dict[str, Any]],
    candidate_securities: list[tuple[str, str | None]] | None = None,
) -> dict[str, Any]:
    caller: dict[str, Any] = {"name": None, "account": None}
    instructions: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for output in outputs:
        raw_caller = output.get("caller")
        if isinstance(raw_caller, dict):
            caller["name"] = caller["name"] or raw_caller.get("name")
            caller["account"] = caller["account"] or raw_caller.get("account")
        for item in output.get("trade_instructions") or []:
            if not isinstance(item, dict):
                continue
            item = normalize_trade_item(item, candidate_securities or [])
            time_ms = item.get("time_in_call_ms")
            time_bucket = round(time_ms / 5000) if isinstance(time_ms, int | float) else None
            key = (
                _normalize_stock_code(item.get("stock_code")),
                str(item.get("stock_name_raw") or "").strip().casefold(),
                item.get("interaction_type"),
                item.get("side"),
                _coerce_number(item.get("quantity")),
                _coerce_number(item.get("price")),
                time_bucket,
            )
            if key in seen:
                continue
            seen.add(key)
            instructions.append(item)
    return {"caller": caller, "trade_instructions": instructions}


def _field_schema(f: ExtractionField) -> dict[str, Any]:
    if f.field_type == "enum" and f.enum_options:
        return {"type": "string", "enum": list(f.enum_options), "nullable": True}
    if f.field_type == "number":
        return {"type": "number", "nullable": True}
    if f.field_type == "boolean":
        return {"type": "boolean", "nullable": True}
    return {"type": "string", "nullable": True}  # string | date


def build_trade_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "caller": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "nullable": True},
                    "account": {"type": "string", "nullable": True},
                },
            },
            "trade_instructions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stock_code": {"type": "string", "nullable": True},
                        "stock_name_raw": {"type": "string", "nullable": True},
                        "interaction_type": {
                            "type": "string",
                            "enum": sorted(TRADE_INTERACTION_TYPES),
                        },
                        "side": {"type": "string", "enum": sorted(SIDES)},
                        "quantity": {"type": "number", "nullable": True},
                        "price": {"type": "number", "nullable": True},
                        "price_type": {"type": "string", "enum": sorted(PRICE_TYPES)},
                        "client_name_raw": {"type": "string", "nullable": True},
                        "client_account_raw": {"type": "string", "nullable": True},
                        "time_in_call_ms": {"type": "integer", "nullable": True},
                        "confidence": {"type": "number"},
                        "evidence_quote": {"type": "string", "nullable": True},
                    },
                    "required": ["interaction_type", "side", "price_type", "confidence"],
                },
            },
        },
        "required": ["caller", "trade_instructions"],
    }


def build_response_schema(
    criteria: list[EvalCriterion],
    call_fields: list[ExtractionField],
    checklist: list[ChecklistItem],
    *,
    trade_module: bool,
    has_kb: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": [c.key for c in criteria] or ["none"]},
                        "passed": {"type": "boolean", "nullable": True},
                        "score": {"type": "integer", "nullable": True},
                        "rationale": {"type": "string"},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "quote": {"type": "string"},
                                    "channel": {"type": "string", "enum": sorted(CHANNELS)},
                                    "approx_ms": {"type": "integer", "nullable": True},
                                },
                                "required": ["quote", "channel"],
                            },
                        },
                    },
                    "required": ["key", "rationale", "evidence"],
                },
            },
            "risk_flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "severity": {"type": "string", "enum": sorted(SEVERITIES)},
                        "note": {"type": "string"},
                    },
                    "required": ["key", "severity", "note"],
                },
            },
            "sentiment": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "enum": sorted(SENTIMENTS)},
                    "score": {"type": "number"},
                },
                "required": ["label", "score"],
            },
            "intent": {"type": "string", "nullable": True},
            "topics": {"type": "array", "items": {"type": "string"}},
            "complaint": {
                "type": "object",
                "properties": {
                    "is_complaint": {"type": "boolean"},
                    "category": {"type": "string", "nullable": True},
                },
                "required": ["is_complaint"],
            },
            "follow_up_actions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "summary",
            "criteria",
            "risk_flags",
            "sentiment",
            "topics",
            "complaint",
            "follow_up_actions",
        ],
    }
    # Trade-reconciliation module: client identity + structured trade orders.
    if trade_module:
        trade_schema = build_trade_response_schema()
        schema["properties"].update(trade_schema["properties"])
        schema["required"] += trade_schema["required"]
    if checklist:
        schema["properties"]["checklist"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "enum": [c.key for c in checklist]},
                    "covered": {"type": "boolean"},
                    "evidence_quote": {"type": "string", "nullable": True},
                    "approx_ms": {"type": "integer", "nullable": True},
                },
                "required": ["key", "covered"],
            },
        }
        schema["required"].append("checklist")
    if has_kb:
        schema["properties"]["correctness"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["correct", "incorrect", "unsupported"],
                    },
                    "kb_quote": {"type": "string", "nullable": True},
                    "evidence_quote": {"type": "string", "nullable": True},
                    "approx_ms": {"type": "integer", "nullable": True},
                    "confidence": {"type": "number"},
                },
                "required": ["claim", "verdict"],
            },
        }
        schema["required"].append("correctness")
    if call_fields:
        schema["properties"]["call_fields"] = {
            "type": "object",
            "properties": {f.key: _field_schema(f) for f in call_fields},
            "nullable": True,
        }
    return schema


# ---------------------------------------------------------------------------
# Post-processing.
# ---------------------------------------------------------------------------


def _normalize_stock_code(code: str | None) -> str | None:
    return normalize_stock_code(code)


def _alias_map(terms: list[IndustryTerm]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for t in terms:
        if not t.stock_code:
            continue
        for name in [t.canonical, *(t.aliases or [])]:
            mapping[name.strip().casefold()] = t.stock_code
    return mapping


def _coerce_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sanitize_evidence(raw: Any) -> list[dict[str, Any]]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not item.get("quote"):
            continue
        ms = item.get("approx_ms")
        out.append(
            {
                "quote": str(item["quote"])[:500],
                "channel": item.get("channel") if item.get("channel") in CHANNELS else "mixed",
                "approx_ms": int(ms) if isinstance(ms, int | float) else None,
            }
        )
    return out[:5]


def _overall_score(criteria: list[EvalCriterion], by_key: dict[str, dict]) -> float | None:
    """Weighted 0-100. pass_fail -> 0/1; scale_1_5 -> (score-1)/4.
    Criteria the model could not judge (both null) are excluded."""
    num = den = 0.0
    for c in criteria:
        entry = by_key.get(c.key)
        if entry is None:
            continue
        if c.score_type == "pass_fail" and entry.get("passed") is not None:
            value = 1.0 if entry["passed"] else 0.0
        elif c.score_type == "scale_1_5" and entry.get("score") is not None:
            value = (max(1, min(5, int(entry["score"]))) - 1) / 4
        else:
            continue
        num += c.weight * value
        den += c.weight
    return round(num / den * 100, 2) if den else None


# ---------------------------------------------------------------------------
# The task.
# ---------------------------------------------------------------------------


@contextmanager
def _evaluation_recording_lock(recording_id: str):
    """Hold a crash-safe, cross-worker lock for one recording evaluation."""
    scope = f"voiceqa-evaluation-recording:{recording_id}"
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = bool(
            connection.execute(
                text(
                    "SELECT pg_try_advisory_lock("
                    "hashtextextended(CAST(:scope AS text), 0))"
                ),
                {"scope": scope},
            ).scalar_one()
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text(
                        "SELECT pg_advisory_unlock("
                        "hashtextextended(CAST(:scope AS text), 0))"
                    ),
                    {"scope": scope},
                )


def _mark_evaluation_attempt_failed(evaluation_id: uuid.UUID, error: str) -> None:
    with SessionLocal() as session:
        evaluation = session.get(Evaluation, evaluation_id)
        if evaluation is not None and evaluation.status == "running":
            evaluation.status = "failed"
            evaluation.error = error[:2000]
            evaluation.completed_at = datetime.now(UTC)
            session.commit()


def _generate_structured_stage(
    adapter,
    prompt: str,
    schema: dict[str, Any],
    *,
    model: str,
    stage: str,
    temperature: float | None = None,
):
    kwargs: dict[str, Any] = {"model": model}
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        return adapter.generate_structured(prompt, schema, **kwargs)
    except Exception as exc:
        raise RuntimeError(f"{stage} failed: {exc}") from exc


@app.task(name="voiceqa.pipeline.evaluate", bind=True, max_retries=5)
def evaluate(self, recording_id: str) -> None:
    with _evaluation_recording_lock(recording_id) as acquired:
        if not acquired:
            logger.info("evaluation already active for {}; duplicate task ignored", recording_id)
            return
        _evaluate_locked(self, recording_id)


def _evaluate_locked(self, recording_id: str) -> None:
    from worker.tasks.batch import update_progress

    with SessionLocal() as session:
        rec = session.get(Recording, uuid.UUID(recording_id))
        if rec is None or rec.status != "evaluating":
            return
        project_id = rec.project_id
        project = session.get(Project, project_id)
        trade_module = (
            bool((project.modules or {}).get("trade_reconciliation")) if project else False
        )
        eval_context = project.eval_prompt_context if project else None
        transcript = (
            session.execute(select(Transcript).where(Transcript.recording_id == rec.id))
        ).scalar_one_or_none()
        if transcript is None:
            _fail(recording_id, "eval", RuntimeError("no transcript to evaluate"))
            return

        budget = int(get_setting(session, project_id, "budget.llm_daily_tokens", 10_000_000))
        spent = llm_tokens_today_sync(session)
        if spent >= budget:
            _fail(
                recording_id,
                "budget",
                RuntimeError(f"daily LLM token budget exhausted ({spent}/{budget})"),
            )
            return

        criteria = (
            session.execute(
                select(EvalCriterion)
                .where(
                    EvalCriterion.project_id == project_id,
                    EvalCriterion.active.is_(True),
                )
                .order_by(EvalCriterion.sort_order)
            )
            .scalars()
            .all()
        )
        call_fields = (
            session.execute(
                select(ExtractionField)
                .where(
                    ExtractionField.project_id == project_id,
                    ExtractionField.active.is_(True),
                    ExtractionField.scope == "call",
                )
                .order_by(ExtractionField.sort_order)
            )
            .scalars()
            .all()
        )
        all_fields = (
            session.execute(
                select(ExtractionField)
                .where(
                    ExtractionField.project_id == project_id,
                    ExtractionField.active.is_(True),
                )
                .order_by(ExtractionField.sort_order)
            )
            .scalars()
            .all()
        )
        terms = (
            session.execute(
                select(IndustryTerm).where(
                    IndustryTerm.project_id == project_id,
                    IndustryTerm.active.is_(True),
                )
            )
            .scalars()
            .all()
        )
        checklist = (
            session.execute(
                select(ChecklistItem)
                .where(
                    ChecklistItem.project_id == project_id,
                    ChecklistItem.active.is_(True),
                )
                .order_by(ChecklistItem.sort_order, ChecklistItem.key)
            )
            .scalars()
            .all()
        )

        run_seq = (
            session.execute(
                select(Evaluation.run_seq)
                .where(Evaluation.recording_id == rec.id)
                .order_by(Evaluation.run_seq.desc())
                .limit(1)
            ).scalar_one_or_none()
            or 0
        ) + 1

        if settings.LLM_PROVIDER == "dashscope" and not settings.LLM_FALLBACK_PROVIDER:
            # Pure DashScope mode: project DB stores a Gemini model name, skip it.
            model = settings.DASHSCOPE_LLM_MODEL
        else:
            model = get_setting(session, project_id, "llm.model", settings.VERTEX_LLM_MODEL)
        evaluation = Evaluation(
            recording_id=rec.id,
            run_seq=run_seq,
            status="running",
            llm_model=model,
            criteria_snapshot=[
                {
                    "key": c.key,
                    "name": c.name,
                    "description": c.description,
                    "category": c.category,
                    "score_type": c.score_type,
                    "severity": c.severity,
                    "weight": c.weight,
                }
                for c in criteria
            ],
            fields_snapshot=[
                {
                    "key": f.key,
                    "label": f.label,
                    "field_type": f.field_type,
                    "enum_options": f.enum_options,
                    "scope": f.scope,
                }
                for f in all_fields
            ],
            checklist_snapshot=[
                {
                    "key": c.key,
                    "label": c.label,
                    "description": c.description,
                    "required": c.required,
                }
                for c in checklist
            ],
        )
        session.add(evaluation)
        rec.updated_at = datetime.now(UTC)
        session.commit()
        evaluation_id = evaluation.id
        batch_id = str(rec.batch_id)

        # Answer-correctness RAG: retrieve the most relevant KB chunks for this
        # call (skipped — and correctness omitted — when the project has no KB).
        kb_chunks = (
            session.execute(select(KbChunk).where(KbChunk.project_id == project_id)).scalars().all()
        )
        kb_context = _retrieve_kb_context(transcript.full_text, kb_chunks) if kb_chunks else None

        prompt = build_prompt(
            rec,
            transcript.full_text,
            criteria,
            call_fields,
            terms,
            checklist,
            context=eval_context,
            trade_module=False,
            kb_context=kb_context,
        )
        schema = build_response_schema(
            criteria,
            call_fields,
            checklist,
            trade_module=False,
            has_kb=kb_context is not None,
        )
        trade_prompts: list[str] = []
        trade_schema = build_trade_response_schema()
        # Preserve an audited/backfilled recording account across re-evaluation;
        # use transcript inference for newly uploaded recordings without one.
        account_hint = _six_digit_account(rec.client_account) or _six_digit_account(
            transcript.full_text
        )
        if trade_module:
            chunks = _trade_chunks(transcript.full_text)
            candidates = _candidate_securities(session, rec)
            prior_context = _prior_trade_context(session, rec, account_hint)
            trade_prompts = [
                build_trade_prompt(
                    rec,
                    chunk,
                    terms,
                    candidates,
                    chunk_index=index,
                    chunk_count=len(chunks),
                    account_hint=account_hint,
                    prior_context=prior_context,
                )
                for index, chunk in enumerate(chunks, 1)
            ]

    try:
        adapter = _adapter()
        parsed, in_tok, out_tok = _generate_structured_stage(
            adapter,
            prompt,
            schema,
            model=model,
            stage="overall evaluation",
        )
        evaluation_summary = str(parsed.get("summary") or "").strip()
        trade_outputs = []
        for index, trade_prompt in enumerate(trade_prompts, 1):
            trade_prompt = _add_evaluation_summary_hint(trade_prompt, evaluation_summary)
            trade_output, trade_in_tok, trade_out_tok = _generate_structured_stage(
                adapter,
                trade_prompt,
                trade_schema,
                model=model,
                stage=f"trade extraction chunk {index}/{len(trade_prompts)}",
                temperature=0.1,
            )
            trade_outputs.append(trade_output)
            in_tok += trade_in_tok
            out_tok += trade_out_tok
        trade_parsed = _merge_trade_outputs(trade_outputs, candidates if trade_module else [])
    except Exception as e:
        transient = any(
            marker in str(e)
            for marker in (
                "429",
                "RESOURCE_EXHAUSTED",
                "503",
                "UNAVAILABLE",
                "timed out",
                "TimeoutException",
                "ReadTimeout",
                "ConnectTimeout",
            )
        )
        if transient:
            if self.request.retries >= self.max_retries:
                _mark_evaluation_attempt_failed(
                    evaluation_id,
                    "evaluation retry limit exceeded",
                )
                _fail(recording_id, "eval", RuntimeError("evaluation retry limit exceeded"))
                raise
            _mark_evaluation_attempt_failed(
                evaluation_id,
                f"transient LLM failure; retry scheduled: {e}",
            )
            raise self.retry(countdown=60, exc=e) from e
        _mark_evaluation_attempt_failed(evaluation_id, str(e))
        _fail(recording_id, "eval", e)
        raise

    with SessionLocal() as session:
        rec = session.get(Recording, uuid.UUID(recording_id))
        evaluation = session.get(Evaluation, evaluation_id)
        criteria = [c for c in criteria]  # snapshot list reused below

        by_key: dict[str, dict] = {}
        for entry in parsed.get("criteria") or []:
            if isinstance(entry, dict) and entry.get("key"):
                by_key[entry["key"]] = entry

        for c in criteria:
            entry = by_key.get(c.key, {})
            passed = entry.get("passed") if isinstance(entry.get("passed"), bool) else None
            score_raw = entry.get("score")
            score = (
                float(max(1, min(5, int(score_raw))))
                if isinstance(score_raw, int | float) and c.score_type == "scale_1_5"
                else None
            )
            session.add(
                EvaluationResult(
                    evaluation_id=evaluation.id,
                    criterion_key=c.key,
                    criterion_name=c.name,
                    passed=passed if c.score_type == "pass_fail" else None,
                    score=score,
                    rationale=str(entry.get("rationale") or "")[:2000] or None,
                    evidence=_sanitize_evidence(entry.get("evidence")),
                    severity=c.severity,
                )
            )

        aliases = _alias_map(terms)
        trade_count = 0
        trade_caller = trade_parsed.get("caller") if trade_module else None
        caller_name = (
            str(trade_caller.get("name") or "").strip() if isinstance(trade_caller, dict) else ""
        )
        raw_caller_account = (
            str(trade_caller.get("account") or "").strip() if isinstance(trade_caller, dict) else ""
        )
        caller_account = _six_digit_account(raw_caller_account) or account_hint or ""
        for idx, item in enumerate(
            (trade_parsed.get("trade_instructions") or []) if trade_module else []
        ):
            if not isinstance(item, dict):
                continue
            code = _normalize_stock_code(item.get("stock_code"))
            if code is None and item.get("stock_name_raw"):
                code = aliases.get(str(item["stock_name_raw"]).strip().casefold())
            confidence = _coerce_number(item.get("confidence"))
            interaction_type = item.get("interaction_type")
            if interaction_type not in TRADE_INTERACTION_TYPES:
                interaction_type = "order_instruction"
            instruction_account = (
                _six_digit_account(str(item.get("client_account_raw") or "")) or caller_account
            )
            session.add(
                TradeInstruction(
                    evaluation_id=evaluation.id,
                    recording_id=rec.id,
                    seq=idx + 1,
                    stock_code=code,
                    stock_name_raw=(item.get("stock_name_raw") or None),
                    side=item.get("side") if item.get("side") in SIDES else "unknown",
                    quantity=_coerce_number(item.get("quantity")),
                    price=_coerce_number(item.get("price")),
                    price_type=item.get("price_type")
                    if item.get("price_type") in PRICE_TYPES
                    else "unknown",
                    client_name_raw=(item.get("client_name_raw") or caller_name or None),
                    client_account_raw=instruction_account or None,
                    time_in_call_ms=int(item["time_in_call_ms"])
                    if isinstance(item.get("time_in_call_ms"), int | float)
                    else None,
                    confidence=min(1.0, max(0.0, confidence)) if confidence is not None else None,
                    extra_fields={"interaction_type": interaction_type},
                    evidence_quote=(str(item.get("evidence_quote") or "")[:500] or None),
                )
            )
            trade_count += 1

        known_call_keys = {f.key for f in call_fields}
        raw_fields = parsed.get("call_fields") or {}
        evaluation.extracted_call_fields = (
            {k: v for k, v in raw_fields.items() if k in known_call_keys}
            if isinstance(raw_fields, dict)
            else {}
        )

        flags = []
        for flag in parsed.get("risk_flags") or []:
            if isinstance(flag, dict) and flag.get("key"):
                flags.append(
                    {
                        "key": str(flag["key"])[:100],
                        "severity": flag.get("severity")
                        if flag.get("severity") in SEVERITIES
                        else "info",
                        "note": str(flag.get("note") or "")[:500],
                    }
                )
        evaluation.risk_flags = flags

        evaluation.summary = str(parsed.get("summary") or "").strip()[:2000] or None

        # Conversation analytics (sentiment / intent / topics / complaint / follow-ups).
        sent = parsed.get("sentiment")
        if isinstance(sent, dict):
            label = sent.get("label")
            evaluation.sentiment_label = label if label in SENTIMENTS else None
            sscore = _coerce_number(sent.get("score"))
            evaluation.sentiment_score = (
                round(max(-1.0, min(1.0, sscore)), 2) if sscore is not None else None
            )
        intent = parsed.get("intent")
        evaluation.customer_intent = (str(intent).strip()[:300] or None) if intent else None
        raw_topics = parsed.get("topics")
        evaluation.topics = (
            [str(t).strip()[:60] for t in raw_topics if isinstance(t, str) and t.strip()][:8]
            if isinstance(raw_topics, list)
            else []
        )
        comp = parsed.get("complaint")
        if isinstance(comp, dict):
            is_c = comp.get("is_complaint")
            evaluation.is_complaint = is_c if isinstance(is_c, bool) else None
            cat = comp.get("category")
            evaluation.complaint_category = (str(cat).strip()[:100] or None) if cat else None
        raw_fua = parsed.get("follow_up_actions")
        evaluation.follow_up_actions = (
            [str(a).strip()[:300] for a in raw_fua if isinstance(a, str) and a.strip()][:8]
            if isinstance(raw_fua, list)
            else []
        )

        # Checklist / script-adherence coverage.
        by_ck = {
            e["key"]: e
            for e in (parsed.get("checklist") or [])
            if isinstance(e, dict) and e.get("key")
        }
        ck_results = []
        covered_req = total_req = 0
        for c in checklist:
            entry = by_ck.get(c.key, {})
            covered = entry.get("covered") is True
            ev_q = entry.get("evidence_quote")
            ms = entry.get("approx_ms")
            ck_results.append(
                {
                    "key": c.key,
                    "label": c.label,
                    "required": c.required,
                    "covered": covered,
                    "evidence_quote": (str(ev_q)[:500] or None) if ev_q else None,
                    "approx_ms": int(ms) if isinstance(ms, int | float) else None,
                }
            )
            if c.required:
                total_req += 1
                covered_req += int(covered)
        evaluation.checklist_results = ck_results
        evaluation.checklist_score = round(covered_req / total_req * 100, 2) if total_req else None

        # Answer correctness against the knowledge base (RAG).
        corr_findings = []
        correct_n = checkable_n = 0
        for item in parsed.get("correctness") or []:
            if not isinstance(item, dict) or item.get("verdict") not in VERDICTS:
                continue
            claim = str(item.get("claim") or "").strip()
            if not claim:
                continue
            verdict = item["verdict"]
            conf = _coerce_number(item.get("confidence"))
            ms = item.get("approx_ms")
            kb_q = item.get("kb_quote")
            ev_q = item.get("evidence_quote")
            corr_findings.append(
                {
                    "claim": claim[:500],
                    "verdict": verdict,
                    "kb_quote": (str(kb_q)[:500] or None) if kb_q else None,
                    "evidence_quote": (str(ev_q)[:500] or None) if ev_q else None,
                    "approx_ms": int(ms) if isinstance(ms, int | float) else None,
                    "confidence": min(1.0, max(0.0, conf)) if conf is not None else None,
                }
            )
            if verdict in ("correct", "incorrect"):
                checkable_n += 1
                correct_n += int(verdict == "correct")
        evaluation.correctness_findings = corr_findings
        evaluation.correctness_score = (
            round(correct_n / checkable_n * 100, 2) if checkable_n else None
        )

        evaluation.overall_score = _overall_score(criteria, by_key)
        evaluation.status = "completed"
        evaluation.input_tokens = in_tok
        evaluation.output_tokens = out_tok
        evaluation.completed_at = datetime.now(UTC)

        record_llm_usage_sync(
            session,
            callsite="evaluation",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            requests=1 + len(trade_prompts),
        )

        # Client identity as heard in the call -> recording (for display/search).
        # Only set when found, so a re-run that misses it doesn't wipe a prior hit.
        caller = trade_parsed.get("caller") if trade_module else None
        if isinstance(caller, dict):
            name = str(caller.get("name") or "").strip()
            account = caller_account
            if name:
                rec.client_name = name[:200]
            if account:
                rec.client_account = account[:100]

        rec.status = "completed"
        rec.failed_stage = None
        rec.stt_started_at = None
        rec.auto_retry_remaining = 0
        rec.rerun_asr_provider = None
        rec.rerun_asr_model = None
        session.commit()

    logger.info(
        "evaluated {} run={}: score={} trades={} tokens={}/{}",
        recording_id,
        run_seq,
        evaluation.overall_score,
        trade_count,
        in_tok,
        out_tok,
    )
    update_progress.delay(batch_id)
