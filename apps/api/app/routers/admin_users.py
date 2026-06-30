"""User administration (admin only): create, list, update role/active/broker
mapping, set password, trigger reset.

RBAC reads the live `users.role` from the DB on every request (deps.py), so
role changes and deactivations take effect immediately. We still bump
`session_version` on those so the web session's cached role claim refreshes
(forces re-login) — defence in depth.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import Broker, PasswordResetToken, User, UserBrokerCode
from voiceqa_shared.passwords import hash_password

from app.db import get_session
from app.deps import ClientMeta, client_meta
from app.emails import send_password_reset
from app.permissions import USERS_MANAGE, require
from app.schemas import AdminUserCreate, AdminUserOut, AdminUserUpdate
from app.settings import settings

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])

RESET_TOKEN_TTL = timedelta(minutes=30)


async def _broker_codes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.execute(
                select(UserBrokerCode.broker_code).where(UserBrokerCode.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )


async def _sync_broker_codes(
    session: AsyncSession, user_id: uuid.UUID, codes: list[str]
) -> None:
    wanted = {c.strip() for c in codes if c.strip()}
    if wanted:
        known = set(
            (
                await session.execute(select(Broker.code).where(Broker.code.in_(wanted)))
            )
            .scalars()
            .all()
        )
        unknown = wanted - known
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown broker codes: {sorted(unknown)}")
    await session.execute(delete(UserBrokerCode).where(UserBrokerCode.user_id == user_id))
    for code in wanted:
        session.add(UserBrokerCode(user_id=user_id, broker_code=code))


async def _out(session: AsyncSession, u: User) -> AdminUserOut:
    now = datetime.now(UTC)
    return AdminUserOut(
        id=u.id,
        email=u.email,
        name=u.name,
        role=u.role,
        is_active=u.is_active,
        has_password=u.password_hash is not None,
        locked=u.locked_until is not None and u.locked_until > now,
        broker_codes=await _broker_codes(session, u.id),
        created_at=u.created_at,
    )


@router.get("", response_model=list[AdminUserOut])
async def list_users(
    actor: User = Depends(require(USERS_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> list[AdminUserOut]:
    users = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    return [await _out(session, u) for u in users]


@router.post("", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate,
    actor: User = Depends(require(USERS_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> AdminUserOut:
    email = payload.email.lower()
    dup = (
        await session.execute(select(User.id).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a user with this email already exists")
    if payload.role == "broker" and not payload.broker_codes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "broker-role users need at least one broker code"
        )
    user = User(
        email=email,
        name=payload.name,
        role=payload.role,
        is_active=payload.is_active,
        password_hash=hash_password(payload.password) if payload.password else None,
        email_verified=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    await _sync_broker_codes(session, user.id, payload.broker_codes)
    log_audit(
        session, action="user.create", user_id=actor.id, actor_email=actor.email,
        object_type="user", object_id=str(user.id),
        details={"email": email, "role": payload.role, "sso_only": payload.password is None},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return await _out(session, user)


async def _get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user


@router.patch("/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    actor: User = Depends(require(USERS_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> AdminUserOut:
    user = await _get_user(session, user_id)
    revoke = False
    if payload.name is not None:
        user.name = payload.name
    if payload.role is not None and payload.role != user.role:
        user.role = payload.role
        revoke = True
    if payload.is_active is not None and payload.is_active != user.is_active:
        if not payload.is_active and user.id == actor.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot deactivate your own account")
        user.is_active = payload.is_active
        revoke = True
    if payload.broker_codes is not None:
        await _sync_broker_codes(session, user.id, payload.broker_codes)
    effective_role = payload.role or user.role
    if effective_role == "broker":
        codes = await _broker_codes(session, user.id)
        if not codes:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "broker-role users need at least one broker code"
            )
    if revoke:
        user.session_version += 1
    log_audit(
        session, action="user.update", user_id=actor.id, actor_email=actor.email,
        object_type="user", object_id=str(user.id),
        details=payload.model_dump(exclude_none=True), ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return await _out(session, user)


@router.post("/{user_id}/set-password", response_model=AdminUserOut)
async def set_password(
    user_id: uuid.UUID,
    payload: dict,
    actor: User = Depends(require(USERS_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> AdminUserOut:
    new_password = str(payload.get("password") or "")
    if len(new_password) < 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password must be at least 10 characters")
    user = await _get_user(session, user_id)
    user.password_hash = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.session_version += 1  # revoke existing sessions
    log_audit(
        session, action="user.set_password", user_id=actor.id, actor_email=actor.email,
        object_type="user", object_id=str(user.id), ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return await _out(session, user)


@router.post("/{user_id}/send-reset", status_code=status.HTTP_204_NO_CONTENT)
async def send_reset(
    user_id: uuid.UUID,
    actor: User = Depends(require(USERS_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> Response:
    user = await _get_user(session, user_id)
    if not user.email or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user has no email or is inactive")
    import hashlib

    token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + RESET_TOKEN_TTL,
        )
    )
    log_audit(
        session, action="user.send_reset", user_id=actor.id, actor_email=actor.email,
        object_type="user", object_id=str(user.id), ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    reset_url = f"{settings.NEXTAUTH_URL}/reset-password/{token}"
    try:
        await run_in_threadpool(send_password_reset, user.email, reset_url)
    except Exception as e:
        logger.error("admin reset email failed for {}: {}", user.email, e)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
