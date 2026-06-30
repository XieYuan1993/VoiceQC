"""Azure AD / Microsoft Entra ID SSO configuration (admin only).

GET/PUT the singleton sso_config row; the client secret is encrypted at rest
and never returned. `test` performs an OIDC discovery fetch against the
tenant's issuer to validate the tenant id and connectivity before enabling.

apps/web's lazy NextAuth init reads this row directly from the DB and builds
the Entra provider; the public /api/auth/sso-status endpoint (in auth.py)
reads the `enabled` flag for the login page button.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.crypto import encrypt_str
from voiceqa_shared.db_models import SsoConfig, User

from app.db import get_session
from app.deps import ClientMeta, client_meta
from app.permissions import SSO_MANAGE, require
from app.schemas import SsoConfigIn, SsoConfigOut, SsoTestOut

router = APIRouter(prefix="/api/admin/sso", tags=["admin-sso"])

DISCOVERY_TEMPLATE = "https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"


async def _get_or_create(session: AsyncSession) -> SsoConfig:
    config = await session.get(SsoConfig, 1)
    if config is None:
        config = SsoConfig(id=1)
        session.add(config)
        await session.flush()
    return config


def _out(c: SsoConfig) -> SsoConfigOut:
    return SsoConfigOut(
        enabled=c.enabled,
        tenant_id=c.tenant_id,
        client_id=c.client_id,
        has_secret=c.client_secret_enc is not None,
        allowed_email_domains=list(c.allowed_email_domains or []),
        group_role_mappings=list(c.group_role_mappings or []),
        auto_provision=c.auto_provision,
        default_role=c.default_role,
        updated_at=c.updated_at,
    )


@router.get("", response_model=SsoConfigOut)
async def get_sso(
    user: User = Depends(require(SSO_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> SsoConfigOut:
    return _out(await _get_or_create(session))


@router.put("", response_model=SsoConfigOut)
async def put_sso(
    payload: SsoConfigIn,
    user: User = Depends(require(SSO_MANAGE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> SsoConfigOut:
    config = await _get_or_create(session)
    # Guard: can't enable without the essentials.
    if payload.enabled and not (payload.tenant_id and payload.client_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "tenant_id and client_id are required to enable SSO"
        )
    has_secret = config.client_secret_enc is not None or bool(payload.client_secret)
    if payload.enabled and not has_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "a client secret is required to enable SSO")

    config.enabled = payload.enabled
    config.tenant_id = payload.tenant_id
    config.client_id = payload.client_id
    config.allowed_email_domains = payload.allowed_email_domains
    config.group_role_mappings = [m.model_dump() for m in payload.group_role_mappings]
    config.auto_provision = payload.auto_provision
    config.default_role = payload.default_role
    if payload.client_secret:  # blank/None keeps the stored secret
        config.client_secret_enc = encrypt_str(payload.client_secret)
    config.updated_by = user.id
    log_audit(
        session, action="sso_config.update", user_id=user.id, actor_email=user.email,
        object_type="sso_config", object_id="1",
        details={"enabled": payload.enabled, "tenant_id": payload.tenant_id},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    await session.refresh(config)
    return _out(config)


@router.post("/test", response_model=SsoTestOut)
async def test_sso(
    user: User = Depends(require(SSO_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> SsoTestOut:
    """Validate the configured tenant via its OIDC discovery document."""
    config = await _get_or_create(session)
    if not config.tenant_id:
        return SsoTestOut(ok=False, detail="no tenant_id configured")
    url = DISCOVERY_TEMPLATE.format(tenant=config.tenant_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return SsoTestOut(ok=False, detail=f"discovery returned HTTP {resp.status_code}")
        doc = resp.json()
        issuer = doc.get("issuer")
        if not doc.get("authorization_endpoint"):
            return SsoTestOut(ok=False, detail="discovery doc missing authorization_endpoint")
        return SsoTestOut(ok=True, detail="tenant discovery succeeded", issuer=issuer)
    except Exception as e:
        return SsoTestOut(ok=False, detail=f"discovery fetch failed: {str(e)[:200]}")
