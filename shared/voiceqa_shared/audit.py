"""Audit-log helper. The caller owns the transaction (commit)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceqa_shared.db_models import AuditLog


def log_audit(
    session: AsyncSession,
    *,
    action: str,
    user_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Stage an audit row on the current session.

    Synchronous add — flushes/commits with the caller's transaction so the
    audit row and the audited change land atomically.
    """
    session.add(
        AuditLog(
            action=action,
            user_id=user_id,
            actor_email=actor_email,
            object_type=object_type,
            object_id=object_id,
            details=details,
            ip=ip,
            user_agent=user_agent,
        )
    )
