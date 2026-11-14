"""Project-scoped FAQ reading and configuration editing."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import KnowledgeFaq, User

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, TRANSCRIPTS_READ, has_perm, require
from app.schemas import KnowledgeFaqIn, KnowledgeFaqOut

router = APIRouter(prefix="/api/knowledge-faqs", tags=["knowledge-faqs"])


def faq_dict(faq):
    return {
        key: getattr(faq, key)
        for key in (
            "id",
            "code",
            "category",
            "question",
            "answer",
            "source",
            "demo_notice",
            "active",
        )
    }


@router.get("", response_model=list[KnowledgeFaqOut])
async def list_faqs(
    include_inactive: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
):
    statement = select(KnowledgeFaq).where(KnowledgeFaq.project_id == project_id)
    if not include_inactive:
        statement = statement.where(KnowledgeFaq.active.is_(True))
    return [
        faq_dict(faq)
        for faq in (await session.execute(statement.order_by(KnowledgeFaq.code))).scalars().all()
    ]


@router.get("/{faq_id}", response_model=KnowledgeFaqOut)
async def get_faq(
    faq_id: uuid.UUID,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(TRANSCRIPTS_READ)),
    session: AsyncSession = Depends(get_session),
):
    faq = await session.get(KnowledgeFaq, faq_id)
    if (
        faq is None
        or faq.project_id != project_id
        or (not faq.active and not has_perm(user.role, CONFIG_READ))
    ):
        raise HTTPException(404, "FAQ not found")
    return faq_dict(faq)


async def _save_faq(payload, faq_id, project_id, user, session, meta):
    faq = await session.get(KnowledgeFaq, faq_id) if faq_id else None
    if faq_id and (faq is None or faq.project_id != project_id):
        raise HTTPException(404, "FAQ not found")
    if faq and faq.code != payload.code:
        raise HTTPException(400, "FAQ code cannot be changed")
    if not payload.question.strip() or not payload.answer.strip():
        raise HTTPException(400, "Question and answer are required")
    if faq is None:
        faq = KnowledgeFaq(id=uuid.uuid4(), project_id=project_id)
        session.add(faq)
    for key, value in payload.model_dump().items():
        setattr(faq, key, value.strip() if isinstance(value, str) else value)
    log_audit(
        session,
        action="knowledge_faqs.update" if faq_id else "knowledge_faqs.create",
        user_id=user.id,
        actor_email=user.email,
        object_type="knowledge_faq",
        object_id=str(faq.id),
        details={"code": faq.code, "active": faq.active},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "FAQ code already exists in this project") from exc
    return faq_dict(faq)


@router.post("", response_model=KnowledgeFaqOut)
async def create_faq(
    payload: KnowledgeFaqIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    return await _save_faq(payload, None, project_id, user, session, meta)


@router.put("/{faq_id}", response_model=KnowledgeFaqOut)
async def update_faq(
    faq_id: uuid.UUID,
    payload: KnowledgeFaqIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
):
    return await _save_faq(payload, faq_id, project_id, user, session, meta)
