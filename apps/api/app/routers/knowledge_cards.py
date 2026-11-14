"""Project-scoped knowledge-card listing and workbook import."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import KnowledgeCard, KnowledgeFaq, User
from voiceqa_shared.knowledge_cards import (
    MAX_UPLOAD_BYTES,
    parse_card_workbook,
    parse_faq_workbook,
    related_faq_codes,
)

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.schemas import KnowledgeCardImportOut, KnowledgeCardIn, KnowledgeCardOut

router = APIRouter(prefix="/api/knowledge-cards", tags=["knowledge-cards"])


def card_dict(card: KnowledgeCard) -> dict:
    content = dict(card.content)
    content["related_faq_codes"] = related_faq_codes(content)
    return {
        "id": card.id,
        "code": card.code,
        "title": card.title,
        "trigger_words": card.trigger_words,
        "content": content,
        "active": card.active,
    }


async def cards_with_faqs(session, project_id, cards):
    result = [card_dict(card) for card in cards]
    codes = {code for item in result for code in item["content"]["related_faq_codes"]}
    if not codes:
        return result
    faqs = (
        (
            await session.execute(
                select(KnowledgeFaq).where(
                    KnowledgeFaq.project_id == project_id,
                    KnowledgeFaq.code.in_(codes),
                )
            )
        )
        .scalars()
        .all()
    )
    by_code = {
        faq.code: {"id": faq.id, "code": faq.code, "question": faq.question, "active": faq.active}
        for faq in faqs
    }
    for item in result:
        item["related_faqs"] = [
            by_code[code] for code in item["content"]["related_faq_codes"] if code in by_code
        ]
    return result


@router.get("", response_model=list[KnowledgeCardOut])
async def list_cards(
    include_inactive: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
):
    statement = select(KnowledgeCard).where(KnowledgeCard.project_id == project_id)
    if not include_inactive:
        statement = statement.where(KnowledgeCard.active.is_(True))
    cards = (await session.execute(statement.order_by(KnowledgeCard.code))).scalars().all()
    return await cards_with_faqs(session, project_id, cards)


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
        faqs = await run_in_threadpool(parse_faq_workbook, raw, required=False)
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
    faq_codes = {faq["code"] for faq in faqs}
    existing_faqs = (
        set(
            (
                await session.execute(
                    select(KnowledgeFaq.code).where(
                        KnowledgeFaq.project_id == project_id,
                        KnowledgeFaq.code.in_(faq_codes),
                    )
                )
            )
            .scalars()
            .all()
        )
        if faq_codes
        else set()
    )
    for faq in faqs:
        statement = insert(KnowledgeFaq).values(project_id=project_id, **faq)
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_knowledge_faqs_project_code",
                set_={
                    key: getattr(statement.excluded, key)
                    for key in ("category", "question", "answer", "source", "demo_notice")
                }
                | {"active": True, "updated_at": datetime.now(UTC)},
            )
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
    return KnowledgeCardImportOut(
        created=created,
        updated=len(existing),
        total=len(cards),
        faqs_created=len(faq_codes - existing_faqs),
        faqs_updated=len(existing_faqs),
    )


async def _save_card(payload, card_id, project_id, user, session, meta):
    card = await session.get(KnowledgeCard, card_id) if card_id else None
    if card_id and (card is None or card.project_id != project_id):
        raise HTTPException(404, "Knowledge card not found")
    if card and card.code != payload.code:
        raise HTTPException(400, "Card code cannot be changed")
    words = list(dict.fromkeys(word.strip() for word in payload.trigger_words))
    if not payload.title.strip() or not all(words) or any(len(word) > 200 for word in words):
        raise HTTPException(400, "A title and non-empty trigger words are required")
    codes = payload.content.related_faq_codes
    if codes:
        existing = set(
            (
                await session.execute(
                    select(KnowledgeFaq.code).where(
                        KnowledgeFaq.project_id == project_id, KnowledgeFaq.code.in_(codes)
                    )
                )
            )
            .scalars()
            .all()
        )
        if set(codes) != existing:
            raise HTTPException(400, "Some related FAQs are missing from this project")
    if card is None:
        card = KnowledgeCard(id=uuid.uuid4(), project_id=project_id, code=payload.code)
        session.add(card)
    card.title = payload.title.strip()
    card.trigger_words = words
    card.content = payload.content.model_dump()
    card.active = payload.active
    log_audit(
        session,
        action="knowledge_cards.update" if card_id else "knowledge_cards.create",
        user_id=user.id,
        actor_email=user.email,
        object_type="knowledge_card",
        object_id=str(card.id),
        details={"code": card.code, "active": card.active},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Card code already exists in this project") from exc
    return (await cards_with_faqs(session, project_id, [card]))[0]


@router.post("", response_model=KnowledgeCardOut)
async def create_card(
    payload: KnowledgeCardIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    return await _save_card(payload, None, project_id, user, session, meta)


@router.put("/{card_id}", response_model=KnowledgeCardOut)
async def update_card(
    card_id: uuid.UUID,
    payload: KnowledgeCardIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    return await _save_card(payload, card_id, project_id, user, session, meta)
