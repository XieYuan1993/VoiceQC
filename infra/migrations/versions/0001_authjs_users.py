"""Auth.js v5 (@auth/pg-adapter) tables + VoiceQA user columns.

Adapter SQL is hardcoded — the column names are camelCase IN THE DATABASE
(userId, providerAccountId, sessionToken, emailVerified) and the
verification table is singular (`verification_token`). Do not "clean up"
in a later migration.

VoiceQA additions on top of the Auth.js spec:
- users.password_hash (argon2id; NULL = SSO-only account)
- users.role (user_role enum — global RBAC, single-tenant app)
- users.is_active, failed_login_attempts, locked_until (lockout)
- users.session_version (revocation hook for the JWT strategy)
- users.created_at
"""
from __future__ import annotations

from alembic import op

revision = "0001_authjs_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Belt-and-braces; init.sql also creates these.
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm";')

    op.execute(
        """
        CREATE TYPE user_role AS ENUM
            ('admin', 'compliance_manager', 'reviewer', 'broker', 'auditor');
        """
    )

    op.execute(
        """
        CREATE TABLE users (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                  TEXT,
            email                 TEXT UNIQUE,
            "emailVerified"       TIMESTAMPTZ,
            image                 TEXT,
            password_hash         TEXT,
            role                  user_role NOT NULL DEFAULT 'reviewer',
            is_active             BOOLEAN NOT NULL DEFAULT true,
            failed_login_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until          TIMESTAMPTZ,
            session_version       INTEGER NOT NULL DEFAULT 0,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE accounts (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            "userId"             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type                 TEXT NOT NULL,
            provider             TEXT NOT NULL,
            "providerAccountId"  TEXT NOT NULL,
            refresh_token        TEXT,
            access_token         TEXT,
            expires_at           BIGINT,
            id_token             TEXT,
            scope                TEXT,
            session_state        TEXT,
            token_type           TEXT,
            CONSTRAINT "uq_accounts_provider_providerAccountId"
                UNIQUE (provider, "providerAccountId")
        );
        CREATE INDEX ix_accounts_userId ON accounts ("userId");
        """
    )

    op.execute(
        """
        CREATE TABLE sessions (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            "userId"       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires        TIMESTAMPTZ NOT NULL,
            "sessionToken" TEXT NOT NULL UNIQUE
        );
        CREATE INDEX ix_sessions_userId ON sessions ("userId");
        """
    )

    op.execute(
        """
        CREATE TABLE verification_token (
            identifier TEXT NOT NULL,
            expires    TIMESTAMPTZ NOT NULL,
            token      TEXT NOT NULL,
            PRIMARY KEY (identifier, token)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS verification_token;")
    op.execute("DROP TABLE IF EXISTS sessions;")
    op.execute("DROP TABLE IF EXISTS accounts;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("DROP TYPE IF EXISTS user_role;")
