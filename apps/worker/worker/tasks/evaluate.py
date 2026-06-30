"""Stage 3: evaluate — one Gemini structured call per recording.

Admin config (eval_criteria + extraction_fields) drives BOTH the prompt and
the response schema, so config changes alter the contract, not just prose.
Every evaluation snapshots the config it ran under; re-runs get a new
run_seq and past evaluations stay untouched (DESIGN.md §5).

Budget guard: when today's llm_usage total exceeds budget.llm_daily_tokens
the recording fails soft with failed_stage='budget' — retryable tomorrow.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from loguru import logger
from sqlalchemy import select
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
    Transcript,
)
from voiceqa_shared.llm_usage import llm_tokens_today_sync, record_llm_usage_sync

from worker.celery_app import app
from worker.db import SessionLocal, get_setting
from worker.kb import cosine
from worker.llm import factory
from worker.llm.embeddings import Embedder
from worker.settings import settings
from worker.tasks.pipeline import _fail

SIDES = {"buy", "sell", "amend", "cancel", "unknown"}
PRICE_TYPES = {"market", "limit", "unknown"}
SEVERITIES = {"info", "warning", "critical"}
CHANNELS = {"broker", "customer", "mixed"}
SENTIMENTS = {"positive", "neutral", "negative", "frustrated", "mixed"}
VERDICTS = {"correct", "incorrect", "unsupported"}
KB_TOP_K = 6  # KB chunks retrieved per call for answer-correctness
KB_QUERY_CHARS = 2000  # transcript prefix used as the retrieval query (embed token cap)


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
            'garble names and digits — give the most plausible reading and reflect uncertainty in '
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


def _field_schema(f: ExtractionField) -> dict[str, Any]:
    if f.field_type == "enum" and f.enum_options:
        return {"type": "string", "enum": list(f.enum_options), "nullable": True}
    if f.field_type == "number":
        return {"type": "number", "nullable": True}
    if f.field_type == "boolean":
        return {"type": "boolean", "nullable": True}
    return {"type": "string", "nullable": True}  # string | date


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
            "summary", "criteria", "risk_flags",
            "sentiment", "topics", "complaint", "follow_up_actions",
        ],
    }
    # Trade-reconciliation module: client identity + structured trade orders.
    if trade_module:
        schema["properties"]["caller"] = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "nullable": True},
                "account": {"type": "string", "nullable": True},
            },
        }
        schema["properties"]["trade_instructions"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stock_code": {"type": "string", "nullable": True},
                    "stock_name_raw": {"type": "string", "nullable": True},
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
                "required": ["side", "price_type", "confidence"],
            },
        }
        schema["required"] += ["caller", "trade_instructions"]
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
    if not code:
        return None
    stripped = "".join(ch for ch in code if ch.isdigit()).lstrip("0")
    return stripped or None


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


@app.task(name="voiceqa.pipeline.evaluate", bind=True, max_retries=5)
def evaluate(self, recording_id: str) -> None:
    from worker.tasks.batch import update_progress

    with SessionLocal() as session:
        rec = session.get(Recording, uuid.UUID(recording_id))
        if rec is None or rec.status != "evaluating":
            return
        project_id = rec.project_id
        project = session.get(Project, project_id)
        trade_module = bool((project.modules or {}).get("trade_reconciliation")) if project else False
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
        session.commit()
        evaluation_id = evaluation.id
        batch_id = str(rec.batch_id)

        # Answer-correctness RAG: retrieve the most relevant KB chunks for this
        # call (skipped — and correctness omitted — when the project has no KB).
        kb_chunks = (
            session.execute(select(KbChunk).where(KbChunk.project_id == project_id))
            .scalars()
            .all()
        )
        kb_context = _retrieve_kb_context(transcript.full_text, kb_chunks) if kb_chunks else None

        prompt = build_prompt(
            rec, transcript.full_text, criteria, call_fields, terms, checklist,
            context=eval_context, trade_module=trade_module, kb_context=kb_context,
        )
        schema = build_response_schema(
            criteria, call_fields, checklist, trade_module=trade_module,
            has_kb=kb_context is not None,
        )

    try:
        parsed, in_tok, out_tok = _adapter().generate_structured(prompt, schema, model=model)
    except Exception as e:
        transient = any(
            marker in str(e)
            for marker in (
                "429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                "timed out", "TimeoutException", "ReadTimeout", "ConnectTimeout",
            )
        )
        if transient:
            from worker.tasks.pipeline import _touch_updated_at
            _touch_updated_at(recording_id)
            raise self.retry(countdown=60, exc=e) from e
        with SessionLocal() as session:
            ev = session.get(Evaluation, evaluation_id)
            if ev is not None:
                ev.status = "failed"
                ev.error = str(e)[:2000]
                session.commit()
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
        for idx, item in enumerate((parsed.get("trade_instructions") or []) if trade_module else []):
            if not isinstance(item, dict):
                continue
            code = _normalize_stock_code(item.get("stock_code"))
            if code is None and item.get("stock_name_raw"):
                code = aliases.get(str(item["stock_name_raw"]).strip().casefold())
            confidence = _coerce_number(item.get("confidence"))
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
                    client_name_raw=(item.get("client_name_raw") or None),
                    client_account_raw=(item.get("client_account_raw") or None),
                    time_in_call_ms=int(item["time_in_call_ms"])
                    if isinstance(item.get("time_in_call_ms"), int | float)
                    else None,
                    confidence=min(1.0, max(0.0, confidence)) if confidence is not None else None,
                    evidence_quote=(str(item.get("evidence_quote") or "")[:500] or None),
                )
            )
            trade_count += 1

        known_call_keys = {f.key for f in call_fields}
        raw_fields = parsed.get("call_fields") or {}
        evaluation.extracted_call_fields = {
            k: v for k, v in raw_fields.items() if k in known_call_keys
        } if isinstance(raw_fields, dict) else {}

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
            session, callsite="evaluation", model=model, input_tokens=in_tok, output_tokens=out_tok
        )

        # Client identity as heard in the call -> recording (for display/search).
        # Only set when found, so a re-run that misses it doesn't wipe a prior hit.
        caller = parsed.get("caller") if trade_module else None
        if isinstance(caller, dict):
            name = str(caller.get("name") or "").strip()
            account = str(caller.get("account") or "").strip()
            if name:
                rec.client_name = name[:200]
            if account:
                rec.client_account = account[:100]

        rec.status = "completed"
        rec.failed_stage = None
        session.commit()

    logger.info(
        "evaluated {} run={}: score={} trades={} tokens={}/{}",
        recording_id, run_seq, evaluation.overall_score, trade_count, in_tok, out_tok,
    )
    update_progress.delay(batch_id)
