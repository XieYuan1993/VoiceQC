"""AES-256-GCM for secrets stored in the DB (txn API credentials now;
SSO client secret in Phase 4).

Format: base64(nonce) + "." + base64(ciphertext||tag). The Node twin
(apps/web/src/lib/crypto.ts, Phase 4) must produce/accept the same format —
keep TEST_VECTOR in sync across both implementations.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from voiceqa_shared.settings import SharedSettings

_settings = SharedSettings()


def _key() -> bytes:
    raw = _settings.APP_ENCRYPTION_KEY.get_secret_value()
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    # Arbitrary string key — derive 32 bytes deterministically.
    return hashlib.sha256(raw.encode()).digest()


def encrypt_str(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce).decode() + "." + base64.b64encode(ct).decode()


def decrypt_str(token: str) -> str:
    nonce_b64, _, ct_b64 = token.partition(".")
    nonce = base64.b64decode(nonce_b64)
    ct = base64.b64decode(ct_b64)
    return AESGCM(_key()).decrypt(nonce, ct, None).decode()
