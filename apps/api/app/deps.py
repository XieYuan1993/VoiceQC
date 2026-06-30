"""FastAPI dependencies: current_user + request metadata for auditing.

Ported from Voicebot-Platform's deps.py, minus the org/membership layer
(single-tenant app — role lives on the user row).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.db_models import Project, User

from app.auth import AuthJSDecryptError, decode_session_from_cookies
from app.db import get_session
from app.settings import settings


async def current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    cookies = dict(request.cookies)
    try:
        decoded = decode_session_from_cookies(cookies, settings.NEXTAUTH_SECRET.get_secret_value())
    except AuthJSDecryptError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid session: {e}") from e

    if decoded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no session cookie")

    sub = decoded.claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session has no subject")

    try:
        user_id = UUID(sub)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session subject is not a UUID") from e

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")

    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account disabled")

    # Instant revocation: deactivation / role change / password reset bump
    # users.session_version; older JWTs then fail here.
    claim_version = decoded.claims.get("session_version", 0)
    if user.session_version != claim_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session revoked")

    return user


@dataclass
class ClientMeta:
    ip: str | None
    user_agent: str | None


def client_meta(request: Request) -> ClientMeta:
    """Request metadata for audit rows."""
    return ClientMeta(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def default_project_id(session: AsyncSession) -> UUID:
    """The default project's id (falls back to the oldest project)."""
    pid = (
        await session.execute(select(Project.id).where(Project.is_default.is_(True)).limit(1))
    ).scalar_one_or_none()
    if pid is None:
        pid = (
            await session.execute(select(Project.id).order_by(Project.created_at).limit(1))
        ).scalar_one_or_none()
    if pid is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no project configured")
    return pid


async def resolve_project_id(
    project_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> UUID:
    """Active project for a request: explicit ?project_id=… or the default.

    The default fallback keeps pre-redesign clients (which don't yet pass a
    project) working against the default project.
    """
    if project_id is not None:
        if await session.get(Project, project_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
        return project_id
    return await default_project_id(session)


def require_project_module(module: str):
    """Dependency factory: 403 unless the resolved project enables `module`.

    Used to gate optional features (e.g. trade reconciliation) so projects
    that don't turn the module on can't reach its endpoints at all.
    """

    async def dep(
        project_id: UUID = Depends(resolve_project_id),
        session: AsyncSession = Depends(get_session),
    ) -> UUID:
        project = await session.get(Project, project_id)
        if project is None or not (project.modules or {}).get(module):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"the '{module}' module is not enabled for this project",
            )
        return project_id

    return dep
