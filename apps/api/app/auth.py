"""Auth.js v5 JWE decryption.

Auth.js v5 (using @auth/core's JWT module) issues a JWE cookie. To decrypt
it from Python we replicate the same key derivation and JWE flow.

References:
- @auth/core source: packages/core/src/jwt.ts (function `getDerivedEncryptionKey`)
- JWE spec: RFC 7516
- A256CBC-HS512 spec: RFC 7518 §5.2.5

Algorithm summary:
1. HKDF-SHA256(secret, salt=b'', info=f'Auth.js Generated Encryption Key ({cookie_name})', length=64)
2. JWE compact format: header.encrypted_key.iv.ciphertext.tag
   With `alg=dir`, `encrypted_key` is empty; the HKDF output IS the CEK.
3. With `enc=A256CBC-HS512`:
     mac_key = derived_key[:32]
     aes_key = derived_key[32:]
   AAD for the MAC is the ASCII-encoded base64url-encoded header (i.e.,
   the bytes BEFORE the first dot in the compact form).
4. AES-256-CBC decrypt(aes_key, iv, ciphertext) -> padded plaintext
5. PKCS7 unpad -> JSON claims

The Phase-0 JWT cookie name (`authjs.session-token` over plain HTTP, or
`__Secure-authjs.session-token` over HTTPS) IS the salt used in step 1.
Pass the right cookie name in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DEFAULT_COOKIE_NAMES = (
    # Auth.js v5 cookie names (insecure first because dev runs on http).
    "authjs.session-token",
    "__Secure-authjs.session-token",
    # NextAuth v4 / Auth.js fallback.
    "next-auth.session-token",
    "__Secure-next-auth.session-token",
)


class AuthJSDecryptError(Exception):
    """Wrapping error for any failure during JWE decryption."""


@dataclass
class DecodedSession:
    claims: dict
    cookie_name: str  # which cookie the token was successfully decrypted with


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _derive_key(secret: bytes, salt_str: str) -> bytes:
    """64-byte derived key.

    Auth.js v5 uses the cookie name in both the HKDF `salt` argument AND
    the `info` argument's template:

        salt = cookieName.encode("utf-8")
        info = f"Auth.js Generated Encryption Key ({cookieName})".encode("utf-8")

    Earlier NextAuth v4 used salt=b"" + info="NextAuth.js Generated Encryption Key" —
    different format, not interoperable.
    """
    salt = salt_str.encode("utf-8")
    info = f"Auth.js Generated Encryption Key ({salt_str})".encode()
    return HKDF(
        algorithm=SHA256(),
        length=64,
        salt=salt,
        info=info,
    ).derive(secret)


def decode_authjs_jwe(token: str, secret: str, cookie_name: str) -> dict:
    """Decrypt a JWE issued by Auth.js v5 with the given cookie name as salt.

    Raises AuthJSDecryptError on any failure (bad token, bad key, bad MAC).
    """
    parts = token.split(".")
    if len(parts) != 5:
        raise AuthJSDecryptError(f"expected 5 JWE compact parts, got {len(parts)}")

    header_b64, encrypted_key_b64, iv_b64, ciphertext_b64, tag_b64 = parts
    try:
        header_bytes = _b64url_decode(header_b64)
        encrypted_key = _b64url_decode(encrypted_key_b64)
        iv = _b64url_decode(iv_b64)
        ciphertext = _b64url_decode(ciphertext_b64)
        tag = _b64url_decode(tag_b64)
    except Exception as e:
        raise AuthJSDecryptError(f"base64url decode failed: {e}") from e

    try:
        header = json.loads(header_bytes)
    except Exception as e:
        raise AuthJSDecryptError(f"header is not valid JSON: {e}") from e

    if header.get("alg") != "dir":
        raise AuthJSDecryptError(f"unsupported alg: {header.get('alg')!r} (need 'dir')")
    if header.get("enc") != "A256CBC-HS512":
        raise AuthJSDecryptError(f"unsupported enc: {header.get('enc')!r} (need 'A256CBC-HS512')")
    if encrypted_key:
        raise AuthJSDecryptError("encrypted_key must be empty for alg=dir")

    derived = _derive_key(secret.encode("utf-8"), cookie_name)
    mac_key = derived[:32]
    aes_key = derived[32:]

    # AAD for A256CBC-HS512 is the ASCII bytes of the base64url-encoded header.
    aad = header_b64.encode("ascii")
    al = struct.pack(">Q", len(aad) * 8)  # 64-bit big-endian bit length of AAD
    mac_input = aad + iv + ciphertext + al
    expected_tag = hmac.new(mac_key, mac_input, hashlib.sha512).digest()[:32]

    if not hmac.compare_digest(expected_tag, tag):
        raise AuthJSDecryptError("MAC verification failed")

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    if not padded:
        raise AuthJSDecryptError("empty plaintext")
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 16 or padded[-pad_len:] != bytes([pad_len]) * pad_len:
        raise AuthJSDecryptError("invalid PKCS7 padding")
    plaintext = padded[:-pad_len]

    try:
        return json.loads(plaintext)
    except Exception as e:
        raise AuthJSDecryptError(f"plaintext is not JSON: {e}") from e


def decode_session_from_cookies(
    cookies: dict[str, str],
    secret: str,
    candidate_names: tuple[str, ...] = DEFAULT_COOKIE_NAMES,
) -> DecodedSession | None:
    """Try each candidate cookie name; return the first successful decoded session.

    Returns None if none of the candidate cookies are present.
    Raises AuthJSDecryptError if a candidate cookie is present but cannot be decrypted.
    """
    last_err: AuthJSDecryptError | None = None
    for name in candidate_names:
        if name not in cookies:
            continue
        try:
            claims = decode_authjs_jwe(cookies[name], secret, name)
            return DecodedSession(claims=claims, cookie_name=name)
        except AuthJSDecryptError as e:
            last_err = e
    if last_err is not None:
        raise last_err
    return None
