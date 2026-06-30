"""LLM-assisted evaluator authoring.

Given a natural-language description of what a team wants to check in their
calls, draft a starter set of evaluation criteria + extraction fields. This
only DRAFTS — the user reviews/edits and saves them through the normal
criteria/extraction-field CRUD. Runs in the worker so it reuses the Gemini
client + budget/usage plumbing; the API enqueues it and waits for the result.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from voiceqa_shared.llm_usage import record_llm_usage_sync

from worker.celery_app import app
from worker.db import SessionLocal, default_project_id, get_setting
from worker.llm import factory
from worker.settings import settings

_KEY_RE = re.compile(r"[^a-z0-9_]+")
CATEGORIES = {"compliance", "quality"}
SCORE_TYPES = {"pass_fail", "scale_1_5"}
SEVERITIES = {"info", "warning", "critical"}
FIELD_TYPES = {"string", "number", "boolean", "date", "enum"}

GEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string", "enum": sorted(CATEGORIES)},
                    "score_type": {"type": "string", "enum": sorted(SCORE_TYPES)},
                    "severity": {"type": "string", "enum": sorted(SEVERITIES)},
                    "weight": {"type": "number"},
                },
                "required": ["key", "name", "description", "category", "score_type", "severity"],
            },
        },
        "extraction_fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "description": {"type": "string", "nullable": True},
                    "field_type": {"type": "string", "enum": sorted(FIELD_TYPES)},
                    "enum_options": {"type": "array", "items": {"type": "string"}, "nullable": True},
                },
                "required": ["key", "label", "field_type"],
            },
        },
    },
    "required": ["criteria", "extraction_fields"],
}


def _slug(value: str | None, fallback: str) -> str:
    s = _KEY_RE.sub("_", (value or "").strip().lower()).strip("_")
    return (s or fallback)[:64]


def _build_prompt(description: str, context: str | None) -> str:
    ctx = (context or "").strip() or "(no additional context given)"
    return f"""You design practical call-QA evaluation rubrics. A team wants to evaluate their \
recorded phone calls and needs a starter rubric.

## Business / use-case context
{ctx}

## What they want to evaluate
{description}

## Produce
- 4 to 8 evaluation CRITERIA. Each has: a snake_case `key` (a-z, 0-9, _); a short `name`; a clear \
1-3 sentence `description` written as an instruction to the evaluator about what passes vs fails; a \
`category` ("compliance" for must-do/regulatory checks, "quality" for soft-skill/service checks); a \
`score_type` ("pass_fail" for objective yes/no checks, "scale_1_5" for qualitative judgement); a \
`severity` (critical|warning|info); and a `weight` from 1 to 3 (higher = more important).
- 2 to 6 EXTRACTION FIELDS capturing structured facts from each call (e.g. call reason, outcome, \
follow-up needed). Each has: a snake_case `key`; a short `label`; a `description`; a `field_type` \
(string|number|boolean|date|enum); and `enum_options` only when field_type is "enum".

Keep keys unique and human-readable. Tailor everything to the described use-case. Do NOT include \
trading/securities items unless the description explicitly mentions them."""


def _sanitize(parsed: dict[str, Any]) -> dict[str, Any]:
    criteria: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, c in enumerate(parsed.get("criteria") or []):
        if not isinstance(c, dict):
            continue
        key = _slug(c.get("key") or c.get("name"), f"criterion_{i + 1}")
        while key in seen:
            key = f"{key}_{i + 1}"[:64]
        seen.add(key)
        try:
            weight = float(c.get("weight") or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        name = str(c.get("name") or key)[:200]
        criteria.append(
            {
                "key": key,
                "name": name,
                "description": (str(c.get("description") or "").strip()[:4000] or name),
                "category": c.get("category") if c.get("category") in CATEGORIES else "quality",
                "score_type": c.get("score_type") if c.get("score_type") in SCORE_TYPES else "pass_fail",
                "severity": c.get("severity") if c.get("severity") in SEVERITIES else "warning",
                "weight": min(10.0, max(0.0, weight)),
            }
        )

    fields: list[dict[str, Any]] = []
    fseen: set[str] = set()
    for i, f in enumerate(parsed.get("extraction_fields") or []):
        if not isinstance(f, dict):
            continue
        key = _slug(f.get("key") or f.get("label"), f"field_{i + 1}")
        while key in fseen:
            key = f"{key}_{i + 1}"[:64]
        fseen.add(key)
        ftype = f.get("field_type") if f.get("field_type") in FIELD_TYPES else "string"
        opts = f.get("enum_options") if isinstance(f.get("enum_options"), list) else None
        opts = [str(o)[:100] for o in opts][:20] if opts else None
        if ftype == "enum" and not opts:
            ftype = "string"
        fields.append(
            {
                "key": key,
                "label": str(f.get("label") or key)[:200],
                "description": (str(f.get("description")).strip()[:1000] if f.get("description") else None),
                "field_type": ftype,
                "enum_options": opts,
            }
        )

    return {"criteria": criteria[:12], "extraction_fields": fields[:10]}


@app.task(name="voiceqa.evaluator.generate_criteria")
def generate_criteria(
    description: str, project_id: str | None = None, context: str | None = None
) -> dict[str, Any]:
    prompt = _build_prompt(description, context)
    with SessionLocal() as session:
        pid = uuid.UUID(project_id) if project_id else default_project_id(session)
        model = get_setting(session, pid, "llm.model", settings.VERTEX_LLM_MODEL)
        parsed, in_tok, out_tok = factory.create("gemini").generate_structured(
            prompt, GEN_SCHEMA, model=model, temperature=0.4
        )
        record_llm_usage_sync(
            session, callsite="evaluator_generate", model=model,
            input_tokens=in_tok, output_tokens=out_tok,
        )
        session.commit()
    return _sanitize(parsed)
