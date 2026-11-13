"""Store optional audio-review evidence separately from the transcript."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_audio_review"
down_revision = "0018_batch_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transcripts", sa.Column("audio_reviews", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("transcripts", "audio_reviews")
