"""Sync SQLAlchemy engine for Celery tasks (psycopg v3)."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from voiceqa_shared.db_models import AppSetting, Project

from worker.settings import settings


def _sync_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + dsn[len("postgresql+asyncpg://") :]
    if dsn.startswith("postgresql://"):
        return "postgresql+psycopg://" + dsn[len("postgresql://") :]
    if dsn.startswith("postgres://"):
        return "postgresql+psycopg://" + dsn[len("postgres://") :]
    return dsn


engine = create_engine(_sync_dsn(settings.DATABASE_URL), pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_setting(session: Session, project_id, key: str, default=None):
    """Read a per-project app setting, keyed by (project_id, key)."""
    row = session.get(AppSetting, (project_id, key))
    return row.value if row is not None else default


def default_project_id(session: Session):
    """The default project's id — used by global/maintenance tasks that are
    not scoped to a single recording."""
    pid = session.execute(
        select(Project.id).where(Project.is_default.is_(True)).limit(1)
    ).scalar_one_or_none()
    if pid is None:
        pid = session.execute(
            select(Project.id).order_by(Project.created_at).limit(1)
        ).scalar_one_or_none()
    return pid
