"""Evaluation criteria CRUD. Edits affect FUTURE evaluations only —
past runs carry their own criteria snapshot."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import EvalCriterion, User

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.schemas import CriterionIn, CriterionOut

router = APIRouter(prefix="/api/criteria", tags=["criteria"])


def _out(c: EvalCriterion) -> CriterionOut:
    return CriterionOut(
        id=c.id,
        key=c.key,
        name=c.name,
        description=c.description,
        category=c.category,
        score_type=c.score_type,
        severity=c.severity,
        weight=c.weight,
        active=c.active,
        sort_order=c.sort_order,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("", response_model=list[CriterionOut])
async def list_criteria(
    include_inactive: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[CriterionOut]:
    stmt = (
        select(EvalCriterion)
        .where(EvalCriterion.project_id == project_id)
        .order_by(EvalCriterion.sort_order, EvalCriterion.key)
    )
    if not include_inactive:
        stmt = stmt.where(EvalCriterion.active.is_(True))
    return [_out(c) for c in (await session.execute(stmt)).scalars().all()]


@router.post("", response_model=CriterionOut)
async def create_criterion(
    payload: CriterionIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> CriterionOut:
    dup = (
        await session.execute(
            select(EvalCriterion.id).where(
                EvalCriterion.project_id == project_id, EvalCriterion.key == payload.key
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"criterion {payload.key!r} already exists")
    criterion = EvalCriterion(project_id=project_id, **payload.model_dump())
    session.add(criterion)
    await session.flush()
    log_audit(
        session, action="criteria.create", user_id=user.id, actor_email=user.email,
        object_type="criterion", object_id=str(criterion.id), details={"key": criterion.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    await session.refresh(criterion)
    return _out(criterion)


@router.patch("/{criterion_id}", response_model=CriterionOut)
async def update_criterion(
    criterion_id: uuid.UUID,
    payload: CriterionIn,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> CriterionOut:
    criterion = await session.get(EvalCriterion, criterion_id)
    if criterion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "criterion not found")
    dup = (
        await session.execute(
            select(EvalCriterion.id).where(
                EvalCriterion.project_id == criterion.project_id,
                EvalCriterion.key == payload.key,
                EvalCriterion.id != criterion_id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"criterion {payload.key!r} already exists")
    for key, value in payload.model_dump().items():
        setattr(criterion, key, value)
    log_audit(
        session, action="criteria.update", user_id=user.id, actor_email=user.email,
        object_type="criterion", object_id=str(criterion.id), details={"key": criterion.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    await session.refresh(criterion)
    return _out(criterion)


@router.delete("/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_criterion(
    criterion_id: uuid.UUID,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> None:
    criterion = await session.get(EvalCriterion, criterion_id)
    if criterion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "criterion not found")
    log_audit(
        session, action="criteria.delete", user_id=user.id, actor_email=user.email,
        object_type="criterion", object_id=str(criterion.id), details={"key": criterion.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.delete(criterion)
    await session.commit()
