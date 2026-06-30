"""Extraction fields CRUD. System trade-scope fields are locked —
reconciliation depends on their shape."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import ExtractionField, User

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.schemas import FieldIn, FieldOut

router = APIRouter(prefix="/api/extraction-fields", tags=["extraction-fields"])


def _out(f: ExtractionField) -> FieldOut:
    return FieldOut(
        id=f.id,
        key=f.key,
        label=f.label,
        description=f.description,
        field_type=f.field_type,
        enum_options=f.enum_options,
        scope=f.scope,
        is_system=f.is_system,
        active=f.active,
        sort_order=f.sort_order,
        created_at=f.created_at,
    )


def _validate(payload: FieldIn) -> None:
    if payload.field_type == "enum" and not payload.enum_options:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "enum fields need enum_options")


@router.get("", response_model=list[FieldOut])
async def list_fields(
    include_inactive: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[FieldOut]:
    stmt = (
        select(ExtractionField)
        .where(ExtractionField.project_id == project_id)
        .order_by(ExtractionField.sort_order, ExtractionField.key)
    )
    if not include_inactive:
        stmt = stmt.where(ExtractionField.active.is_(True))
    return [_out(f) for f in (await session.execute(stmt)).scalars().all()]


@router.post("", response_model=FieldOut)
async def create_field(
    payload: FieldIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> FieldOut:
    _validate(payload)
    if payload.scope == "trade":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "trade-scope fields are system-defined; add call-scope fields instead",
        )
    dup = (
        await session.execute(
            select(ExtractionField.id).where(
                ExtractionField.project_id == project_id, ExtractionField.key == payload.key
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"field {payload.key!r} already exists")
    field = ExtractionField(project_id=project_id, **payload.model_dump())
    session.add(field)
    await session.flush()
    log_audit(
        session, action="fields.create", user_id=user.id, actor_email=user.email,
        object_type="extraction_field", object_id=str(field.id), details={"key": field.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return _out(field)


@router.patch("/{field_id}", response_model=FieldOut)
async def update_field(
    field_id: uuid.UUID,
    payload: FieldIn,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> FieldOut:
    field = await session.get(ExtractionField, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "field not found")
    if field.is_system:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "system field is locked")
    _validate(payload)
    dup = (
        await session.execute(
            select(ExtractionField.id).where(
                ExtractionField.project_id == field.project_id,
                ExtractionField.key == payload.key,
                ExtractionField.id != field_id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"field {payload.key!r} already exists")
    for key, value in payload.model_dump().items():
        setattr(field, key, value)
    log_audit(
        session, action="fields.update", user_id=user.id, actor_email=user.email,
        object_type="extraction_field", object_id=str(field.id), details={"key": field.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return _out(field)


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    field_id: uuid.UUID,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> None:
    field = await session.get(ExtractionField, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "field not found")
    if field.is_system:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "system field is locked")
    log_audit(
        session, action="fields.delete", user_id=user.id, actor_email=user.email,
        object_type="extraction_field", object_id=str(field.id), details={"key": field.key},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.delete(field)
    await session.commit()
