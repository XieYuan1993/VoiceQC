"""Phase-0 admin tables: password reset, brokers, settings, audit log.

- password_reset_tokens: single-use expiring tokens (sha256 stored, not raw)
- brokers / user_broker_codes: AE code <-> phone extension mapping; scopes
  the `broker` role to its own recordings
- app_settings: admin-edited key/value JSONB config
- audit_log: append-only trail (mutations AND sensitive reads)
"""
from __future__ import annotations

from alembic import op

revision = "0002_admin_tables"
down_revision = "0001_authjs_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE password_reset_tokens (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at    TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_password_reset_tokens_user_id ON password_reset_tokens (user_id);
        """
    )

    op.execute(
        """
        CREATE TABLE brokers (
            code             TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            phone_extensions TEXT[] NOT NULL DEFAULT '{}',
            active           BOOLEAN NOT NULL DEFAULT true,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE user_broker_codes (
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            broker_code TEXT NOT NULL REFERENCES brokers(code) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, broker_code)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE app_settings (
            key        TEXT PRIMARY KEY,
            value      JSONB NOT NULL,
            updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE audit_log (
            id          BIGSERIAL PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
            actor_email TEXT,
            action      TEXT NOT NULL,
            object_type TEXT,
            object_id   TEXT,
            details     JSONB,
            ip          INET,
            user_agent  TEXT
        );
        CREATE INDEX ix_audit_log_occurred_at ON audit_log (occurred_at);
        CREATE INDEX ix_audit_log_user_id_occurred_at ON audit_log (user_id, occurred_at);
        CREATE INDEX ix_audit_log_object_type_object_id ON audit_log (object_type, object_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log;")
    op.execute("DROP TABLE IF EXISTS app_settings;")
    op.execute("DROP TABLE IF EXISTS user_broker_codes;")
    op.execute("DROP TABLE IF EXISTS brokers;")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens;")
