"""Add transcription-only processing mode to upload batches."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_batch_mode"
down_revision = "0017_recon_project"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "upload_batches",
        sa.Column(
            "processing_mode",
            sa.Text(),
            nullable=False,
            server_default="full",
        ),
    )
    op.create_check_constraint(
        "ck_upload_batches_processing_mode",
        "upload_batches",
        "processing_mode IN ('full', 'transcription_only')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_upload_batches_processing_mode", "upload_batches", type_="check"
    )
    op.drop_column("upload_batches", "processing_mode")
