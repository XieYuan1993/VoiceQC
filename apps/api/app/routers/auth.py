"""Credential auth endpoints.

- verify-credentials: internal endpoint called by apps/web's Auth.js
  Credentials authorize(). Password verification, lockout, and audit all
  live here (Python side) so the web app stays a thin shell.
- password-reset request/confirm: emailed single-use tokens.
- sso-status: public flag for the login page's "Sign in with Microsoft"
  button. Phase 4 reads sso_config from the DB; until then always false.

Rate limiting (slowapi, 5/min on auth endpoints) lands in Phase 4.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import PasswordResetToken, SsoConfig, User
from voiceqa_shared.passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password

from app.db import get_session
from app.deps import ClientMeta, client_meta
from app.emails import send_password_reset
from app.ratelimit import limiter
from app.schemas import (
    PasswordResetConfirm,
    PasswordResetRequest,
    SsoStatusResponse,
    VerifyCredentialsRequest,
    VerifyCredentialsResponse,
)
from app.settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=15)
RESET_TOKEN_TTL = timedelta(minutes=30)

# One generic message for every credential failure — no user-enumeration or
# lockout oracle.
_INVALID = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")


def _require_internal_secret(
    x_internal_secret: str | None = Header(default=None),
) -> None:
    expected = settings.INTERNAL_API_SECRET.get_secret_value()
    if not (x_internal_secret and hmac.compare_digest(x_internal_secret, expected)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal secret")


@router.post(
    "/verify-credentials",
    response_model=VerifyCredentialsResponse,
    dependencies=[Depends(_require_internal_secret)],
    include_in_schema=False,  # internal contract with apps/web, not public API
)
async def verify_credentials(
    payload: VerifyCredentialsRequest,
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> VerifyCredentialsResponse:
    email = payload.email.lower()
    user = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()

    async def _fail(reason: str, user_id=None) -> None:
        log_audit(
            session,
            action="auth.login_failed",
            user_id=user_id,
            actor_email=email,
            details={"reason": reason},
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
        await session.commit()

    if user is None or user.password_hash is None:
        await _fail("unknown_user_or_no_password")
        raise _INVALID
    if not user.is_active:
        await _fail("account_disabled", user.id)
        raise _INVALID

    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        await _fail("locked", user.id)
        raise _INVALID

    ok, needs_rehash = verify_password(user.password_hash, payload.password)
    if not ok:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + LOCKOUT
            user.failed_login_attempts = 0
            logger.warning("account locked after repeated failures: {}", email)
        await _fail("bad_password", user.id)
        raise _INVALID

    if needs_rehash:
        user.password_hash = hash_password(payload.password)
    user.failed_login_attempts = 0
    user.locked_until = None
    log_audit(
        session,
        action="auth.login_success",
        user_id=user.id,
        actor_email=user.email,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    await session.commit()

    return VerifyCredentialsResponse(
        id=user.id,
        email=user.email or email,
        name=user.name,
        role=user.role,
        session_version=user.session_version,
    )


@router.post("/password-reset/request", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def password_reset_request(
    request: Request,
    payload: PasswordResetRequest,
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> Response:
    """Always 204 — whether or not the account exists (no enumeration)."""
    email = payload.email.lower()
    user = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()

    if user is not None and user.is_active and user.email:
        token = secrets.token_urlsafe(32)
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + RESET_TOKEN_TTL,
            )
        )
        log_audit(
            session,
            action="auth.password_reset_requested",
            user_id=user.id,
            actor_email=user.email,
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
        await session.commit()

        reset_url = f"{settings.NEXTAUTH_URL}/reset-password/{token}"
        try:
            await run_in_threadpool(send_password_reset, user.email, reset_url)
        except Exception as e:
            logger.error("password reset email failed for {}: {}", email, e)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def password_reset_confirm(
    request: Request,
    payload: PasswordResetConfirm,
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> Response:
    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )

    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    row = (
        await session.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")

    user.password_hash = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    # Revoke all existing sessions.
    user.session_version += 1
    row.used_at = now
    log_audit(
        session,
        action="auth.password_reset_completed",
        user_id=user.id,
        actor_email=user.email,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sso-status", response_model=SsoStatusResponse)
async def sso_status(session: AsyncSession = Depends(get_session)) -> SsoStatusResponse:
    """Public: whether the login page should show "Sign in with Microsoft"."""
    config = await session.get(SsoConfig, 1)
    enabled = bool(config and config.enabled and config.tenant_id and config.client_id)
    return SsoStatusResponse(enabled=enabled)
