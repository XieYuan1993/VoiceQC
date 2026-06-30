"""RBAC permission matrix + the `require(perm)` dependency.

Single-tenant: roles live on `users.role` (Postgres enum user_role).
Routes declare the permission they need; roles map to permission sets here.
The `broker` role additionally gets row-level scoping (own extensions only)
at the query layer — `recordings:read_own` signals that to route handlers.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

# Permission verbs. Keep in sync with DESIGN.md §7.
RECORDINGS_READ_ALL = "recordings:read_all"
RECORDINGS_READ_OWN = "recordings:read_own"
BATCHES_MANAGE = "batches:manage"
TRANSCRIPTS_READ = "transcripts:read"
EVALS_REVIEW = "evals:review"
CONFIG_READ = "config:read"
CONFIG_WRITE = "config:write"
TERMS_WRITE = "terms:write"
TXNS_READ = "txns:read"
TXNS_IMPORT = "txns:import"
RECON_RUN = "recon:run"
RECON_REVIEW = "recon:review"
USERS_MANAGE = "users:manage"
SSO_MANAGE = "sso:manage"
AUDIT_READ = "audit:read"
USAGE_READ = "usage:read"

_ALL = frozenset(
    {
        RECORDINGS_READ_ALL,
        RECORDINGS_READ_OWN,
        BATCHES_MANAGE,
        TRANSCRIPTS_READ,
        EVALS_REVIEW,
        CONFIG_READ,
        CONFIG_WRITE,
        TERMS_WRITE,
        TXNS_READ,
        TXNS_IMPORT,
        RECON_RUN,
        RECON_REVIEW,
        USERS_MANAGE,
        SSO_MANAGE,
        AUDIT_READ,
        USAGE_READ,
    }
)

ROLE_PERMS: dict[str, frozenset[str]] = {
    "admin": _ALL,
    "compliance_manager": frozenset(
        {
            RECORDINGS_READ_ALL,
            BATCHES_MANAGE,
            TRANSCRIPTS_READ,
            EVALS_REVIEW,
            CONFIG_READ,
            CONFIG_WRITE,
            TERMS_WRITE,
            TXNS_READ,
            TXNS_IMPORT,
            RECON_RUN,
            RECON_REVIEW,
            USAGE_READ,
        }
    ),
    "reviewer": frozenset(
        {
            RECORDINGS_READ_ALL,
            TRANSCRIPTS_READ,
            EVALS_REVIEW,
            CONFIG_READ,
            TXNS_READ,
        }
    ),
    "broker": frozenset(
        {
            RECORDINGS_READ_OWN,
            TRANSCRIPTS_READ,
        }
    ),
    "auditor": frozenset(
        {
            RECORDINGS_READ_ALL,
            TRANSCRIPTS_READ,
            CONFIG_READ,
            TXNS_READ,
            USAGE_READ,
            AUDIT_READ,
        }
    ),
}


def has_perm(role: str, perm: str) -> bool:
    return perm in ROLE_PERMS.get(role, frozenset())


def require(perm: str) -> Callable:
    """Dependency factory: 403 unless the current user's role grants `perm`.

    Returns the user so handlers can chain it:
        user: User = Depends(require(CONFIG_WRITE))
    """
    from voiceqa_shared.db_models import User

    from app.deps import current_user  # local import to avoid a cycle

    async def _dep(user: User = Depends(current_user)) -> User:
        if not has_perm(user.role, perm):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role {user.role!r} lacks permission {perm!r}",
            )
        return user

    return _dep
