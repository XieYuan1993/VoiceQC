"""Alembic env — sync psycopg.

Uses psycopg (v3) for the migration connection because asyncpg rejects
multi-statement SQL in a single prepared statement, which our hand-written
migrations rely on. The runtime app still uses asyncpg via SQLAlchemy.

Reads $DATABASE_URL from env. Accepts either an `asyncpg` or `psycopg` DSN
and rewrites it to psycopg form here.

Use `cd infra/migrations && uv run alembic upgrade head` (or `make migrate`).
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Make `voiceqa_shared` importable when alembic runs from infra/migrations.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from voiceqa_shared.db_models import Base  # noqa: E402

# Load .env from repo root if present (so DATABASE_URL is picked up).
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _to_sync_dsn(dsn: str) -> str:
    """Rewrite postgresql+asyncpg://… or postgresql:// to postgresql+psycopg://…"""
    if dsn.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + dsn[len("postgresql+asyncpg://") :]
    if dsn.startswith("postgresql://"):
        return "postgresql+psycopg://" + dsn[len("postgresql://") :]
    if dsn.startswith("postgres://"):
        return "postgresql+psycopg://" + dsn[len("postgres://") :]
    return dsn


# Override the DSN from env.
db_url = os.environ.get("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", _to_sync_dsn(db_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without connecting — used for `alembic upgrade --sql`."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect via psycopg and run migrations."""
    url = config.get_main_option("sqlalchemy.url")
    # psycopg/libpq hangs connecting to Render's INTERNAL Postgres: the app's
    # asyncpg driver connects in plaintext (no SSL) and works, but libpq defaults
    # to negotiating SSL (sslmode=prefer) and GSS encryption first, and the
    # internal endpoint stalls that handshake — the ~18s silent timeout. Force a
    # plaintext connection to match asyncpg, and cap connect_timeout so any real
    # failure surfaces fast instead of hanging.
    connect_args = (
        {"connect_timeout": 15, "sslmode": "disable", "gssencmode": "disable"}
        if "+psycopg" in url
        else {}
    )
    connectable = create_engine(url, poolclass=pool.NullPool, connect_args=connect_args)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
