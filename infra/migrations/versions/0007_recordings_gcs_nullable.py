"""Allow recordings.gcs_uri_raw to be NULL so retention can purge audio.

A purged recording has NULL gcs_uri_*; the retention sweep selects on
`gcs_uri_raw IS NOT NULL`, so nulling it is also what makes the sweep
idempotent (a purged row is never re-selected).
"""
from __future__ import annotations

from alembic import op

revision = "0007_recordings_gcs_nullable"
down_revision = "0006_sso_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE recordings ALTER COLUMN gcs_uri_raw DROP NOT NULL;")


def downgrade() -> None:
    op.execute("ALTER TABLE recordings ALTER COLUMN gcs_uri_raw SET NOT NULL;")
