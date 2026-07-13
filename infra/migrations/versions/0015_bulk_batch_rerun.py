"""Persist bulk rerun provider and automatic retry state."""

from __future__ import annotations

from alembic import op

revision = "0015_bulk_batch_rerun"
down_revision = "0014_quam_recon_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE recordings
            ADD COLUMN auto_retry_remaining INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN rerun_asr_provider TEXT,
            ADD COLUMN rerun_asr_model TEXT,
            ADD COLUMN stt_started_at TIMESTAMPTZ;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE recordings
            DROP COLUMN stt_started_at,
            DROP COLUMN rerun_asr_model,
            DROP COLUMN rerun_asr_provider,
            DROP COLUMN auto_retry_remaining;
        """
    )
