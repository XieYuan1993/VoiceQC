"""Add client identity (name/account as heard in the call) to recordings.

Populated by the evaluation task from what the client states in the call —
the telephony export frequently has no caller name.
"""
from __future__ import annotations

from alembic import op

revision = "0008_recording_client_identity"
down_revision = "0007_recordings_gcs_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE recordings ADD COLUMN client_name TEXT;")
    op.execute("ALTER TABLE recordings ADD COLUMN client_account TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP COLUMN client_account;")
    op.execute("ALTER TABLE recordings DROP COLUMN client_name;")
