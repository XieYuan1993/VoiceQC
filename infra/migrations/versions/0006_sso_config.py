"""Phase-4 SSO: the singleton sso_config row.

Admin-edited Azure AD / Entra config, read by apps/web's lazy NextAuth init.
The client secret is AES-256-GCM encrypted at rest. A seed row (id=1,
disabled) is inserted so the web app always has a row to read.
"""
from __future__ import annotations

from alembic import op

revision = "0006_sso_config"
down_revision = "0005_txn_recon_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sso_config (
            id                    SMALLINT PRIMARY KEY DEFAULT 1,
            enabled               BOOLEAN NOT NULL DEFAULT false,
            tenant_id             TEXT,
            client_id             TEXT,
            client_secret_enc     TEXT,
            allowed_email_domains TEXT[] NOT NULL DEFAULT '{}',
            group_role_mappings   JSONB NOT NULL DEFAULT '[]',
            auto_provision        BOOLEAN NOT NULL DEFAULT false,
            default_role          user_role NOT NULL DEFAULT 'reviewer',
            updated_by            UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sso_config_singleton CHECK (id = 1)
        );
        INSERT INTO sso_config (id, enabled) VALUES (1, false);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sso_config;")
