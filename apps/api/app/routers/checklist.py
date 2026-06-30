"""Checklist / script-adherence items CRUD (per project)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import ChecklistItem, User

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.schemas import ChecklistItemIn, ChecklistItemOut

router = APIRouter(prefix="/api/checklist-items", tags=["checklist"])


def _out(c: ChecklistItem) -> ChecklistItemOut:
    return ChecklistItemOut(
        id=c.id,
        key=c.key,
        label=c.label,
        description=c.description,
        required=c.required,
        active=c.active,
        sort_order=c.sort_order,
        created_at=c.created_at,
    )


@router.get("", response_model=list[ChecklistItemOut])
async def list_items(
    include_inactive: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ChecklistItemOut]:
    stmt = (
        select(ChecklistItem)
        .where(ChecklistItem.project_id == project_id)
        .order_by(ChecklistItem.sort_order, ChecklistItem.key)
    )
    if not include_inactive:
        stmt = stmt.where(ChecklistItem.active.is_(True))
    return [_out(c) for c in (await session.execute(stmt)).scalars().all()]


@router.post("", response_model=ChecklistItemOut)
async def create_item(
    payload: ChecklistItemIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ChecklistItemOut:
    dup = (
        await session.execute(
            select(ChecklistItem.id).where(
                ChecklistItem.project_id == project_id, ChecklistItem.key == payload.key
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"checklist item {payload.key!r} already exists"
        )
    item = ChecklistItem(project_id=project_id, **payload.model_dump())
    session.add(item)
    await session.flush()
    log_audit(
        session, action="checklist.create", user_id=user.id, actor_email=user.email,
        object_type="checklist_item", object_id=str(item.id), details={"key": item.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return _out(item)


@router.patch("/{item_id}", response_model=ChecklistItemOut)
async def update_item(
    item_id: uuid.UUID,
    payload: ChecklistItemIn,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ChecklistItemOut:
    item = await session.get(ChecklistItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "checklist item not found")
    dup = (
        await session.execute(
            select(ChecklistItem.id).where(
                ChecklistItem.project_id == item.project_id,
                ChecklistItem.key == payload.key,
                ChecklistItem.id != item_id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"checklist item {payload.key!r} already exists"
        )
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    log_audit(
        session, action="checklist.update", user_id=user.id, actor_email=user.email,
        object_type="checklist_item", object_id=str(item.id), details={"key": item.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return _out(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> None:
    item = await session.get(ChecklistItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "checklist item not found")
    log_audit(
        session, action="checklist.delete", user_id=user.id, actor_email=user.email,
        object_type="checklist_item", object_id=str(item.id), details={"key": item.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.delete(item)
    await session.commit()
