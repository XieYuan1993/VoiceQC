"""Smoke: the app boots and /api/healthz answers without a database."""

from __future__ import annotations

import httpx
import pytest
from app.main import app


@pytest.mark.anyio
async def test_healthz() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.anyio
async def test_me_requires_session() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/me")
    assert resp.status_code == 401
