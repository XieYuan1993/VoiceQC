"""Signed URLs for ASR providers that need to download private audio."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + ("=" * (-len(data) % 4)))


def _sign(payload: str, secret: str) -> str:
    return _b64url(hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest())


def create_token(uri: str, secret: str, *, expires_in_seconds: int) -> str:
    if not secret:
        raise RuntimeError("ASR audio proxy secret is not configured")
    payload = _b64url(
        json.dumps(
            {"uri": uri, "exp": int(time.time()) + expires_in_seconds},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{payload}.{_sign(payload, secret)}"


def parse_token(token: str, secret: str) -> str:
    if not secret:
        raise ValueError("ASR audio proxy secret is not configured")
    try:
        payload, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid token") from exc
    expected = _sign(payload, secret)
    if not hmac.compare_digest(sig, expected):
        raise ValueError("invalid token signature")
    data = json.loads(_unb64url(payload))
    if int(data.get("exp") or 0) < int(time.time()):
        raise ValueError("token expired")
    uri = str(data.get("uri") or "")
    if not uri.startswith("gs://"):
        raise ValueError("invalid audio uri")
    return uri


def create_url(base_url: str, uri: str, secret: str, *, expires_in_seconds: int) -> str:
    base = base_url.rstrip("/")
    token = create_token(uri, secret, expires_in_seconds=expires_in_seconds)
    return f"{base}/api/asr-audio?{urlencode({'token': token})}"
