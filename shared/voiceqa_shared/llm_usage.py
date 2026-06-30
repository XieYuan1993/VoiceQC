"""LLM token usage recording + daily budget reads.

Ported from Voicebot-Platform's gemini_usage.py, minus the org dimension
(single-tenant). Celery workers use the sync flavour; FastAPI (usage
dashboards, Phase 4) uses the async one. Upserts via INSERT .. ON CONFLICT.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from voiceqa_shared.db_models import LlmUsage


def extract_tokens(resp: Any) -> tuple[int, int]:
    """(input_tokens, output_tokens) from a google.genai response.

    Defensive — empty / error responses return (0, 0) rather than raising
    so the calling code can still record that a request happened.
    """
    usage = getattr(resp, "usage_metadata", None)
    if usage is None:
        return 0, 0
    in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
    out_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
    return in_tok, out_tok


def _today():
    now = datetime.now(UTC)
    return now.date()


def record_llm_usage_sync(
    session: Session,
    *,
    callsite: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    requests: int = 1,
) -> None:
    stmt = (
        pg_insert(LlmUsage)
        .values(
            day=_today(),
            callsite=callsite,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requests=requests,
        )
        .on_conflict_do_update(
            constraint="uq_llm_usage_day_callsite_model",
            set_={
                "input_tokens": LlmUsage.input_tokens + input_tokens,
                "output_tokens": LlmUsage.output_tokens + output_tokens,
                "requests": LlmUsage.requests + requests,
            },
        )
    )
    session.execute(stmt)
    session.commit()


def llm_tokens_today_sync(session: Session) -> int:
    rows = (
        session.execute(
            select(LlmUsage.input_tokens + LlmUsage.output_tokens).where(
                LlmUsage.day == _today()
            )
        )
        .scalars()
        .all()
    )
    return int(sum(rows))


async def llm_tokens_today_async(session: AsyncSession) -> int:
    rows = (
        (
            await session.execute(
                select(LlmUsage.input_tokens + LlmUsage.output_tokens).where(
                    LlmUsage.day == _today()
                )
            )
        )
        .scalars()
        .all()
    )
    return int(sum(rows))
