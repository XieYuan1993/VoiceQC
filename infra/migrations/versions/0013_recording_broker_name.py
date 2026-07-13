"""Add broker name parsed from telephony exports."""
from __future__ import annotations

from alembic import op

revision = "0013_recording_broker_name"
down_revision = "0012_kb_correctness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE recordings ADD COLUMN broker_name TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP COLUMN broker_name;")
