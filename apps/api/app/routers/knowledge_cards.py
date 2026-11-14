"""Project-scoped knowledge-card listing and workbook import."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import KnowledgeCard, User
from voiceqa_shared.knowledge_cards import MAX_UPLOAD_BYTES, parse_card_workbook

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.schemas import KnowledgeCardImportOut, KnowledgeCardOut

router = APIRouter(prefix="/api/knowledge-cards", tags=["knowledge-cards"])


def card_dict(card: KnowledgeCard) -> dict:
    return {
        "id": card.id,
        "code": card.code,
        "title": card.title,
        "trigger_words": card.trigger_words,
        "content": card.content,
    }


@router.get("", response_model=list[KnowledgeCardOut])
async def list_cards(
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
):
    cards = (
        (
            await session.execute(
                select(KnowledgeCard)
                .where(
                    KnowledgeCard.project_id == project_id,
                    KnowledgeCard.active.is_(True),
                )
                .order_by(KnowledgeCard.code)
            )
        )
        .scalars()
        .all()
    )
    return [card_dict(card) for card in cards]


@router.post("/import", response_model=KnowledgeCardImportOut)
async def import_cards(
    file: UploadFile = File(...),
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "An XLSX workbook is required")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Workbook exceeds the 5 MB limit")
    try:
        cards = await run_in_threadpool(parse_card_workbook, raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    codes = {card["code"] for card in cards}
    existing = set(
        (
            await session.execute(
                select(KnowledgeCard.code).where(
                    KnowledgeCard.project_id == project_id,
                    KnowledgeCard.code.in_(codes),
                )
            )
        )
        .scalars()
        .all()
    )
    for card in cards:
        statement = insert(KnowledgeCard).values(project_id=project_id, **card)
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_knowledge_cards_project_code",
                set_={
                    "title": statement.excluded.title,
                    "trigger_words": statement.excluded.trigger_words,
                    "content": statement.excluded.content,
                    "active": True,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
    created = len(codes - existing)
    log_audit(
        session,
        action="knowledge_cards.import",
        user_id=user.id,
        actor_email=user.email,
        object_type="project",
        object_id=str(project_id),
        details={"created": created, "updated": len(existing)},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    await session.commit()
    return KnowledgeCardImportOut(created=created, updated=len(existing), total=len(cards))
