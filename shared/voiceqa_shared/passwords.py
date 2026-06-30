"""Argon2id password hashing — used by apps/api and the seed script."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Library defaults (argon2id, 64 MiB, t=3, p=4) meet OWASP guidance.
_hasher = PasswordHasher()

# Enforced on set/reset, not on login (existing hashes always verify).
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> tuple[bool, bool]:
    """Returns (ok, needs_rehash). Never raises on bad input."""
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False
    return True, _hasher.check_needs_rehash(password_hash)
