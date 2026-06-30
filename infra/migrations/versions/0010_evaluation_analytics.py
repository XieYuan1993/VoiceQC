"""Add conversation-analytics columns to evaluations.

Customer-side sentiment, intent, topics, complaint flag and follow-up actions —
produced by the same Gemini evaluation call, so no schema beyond these columns.
"""
from __future__ import annotations

from alembic import op

revision = "0010_evaluation_analytics"
down_revision = "0009_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE evaluations ADD COLUMN sentiment_label TEXT;")
    op.execute("ALTER TABLE evaluations ADD COLUMN sentiment_score NUMERIC(3, 2);")
    op.execute("ALTER TABLE evaluations ADD COLUMN customer_intent TEXT;")
    op.execute("ALTER TABLE evaluations ADD COLUMN topics JSONB NOT NULL DEFAULT '[]'::jsonb;")
    op.execute("ALTER TABLE evaluations ADD COLUMN is_complaint BOOLEAN;")
    op.execute("ALTER TABLE evaluations ADD COLUMN complaint_category TEXT;")
    op.execute(
        "ALTER TABLE evaluations ADD COLUMN follow_up_actions JSONB NOT NULL DEFAULT '[]'::jsonb;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE evaluations DROP COLUMN follow_up_actions;")
    op.execute("ALTER TABLE evaluations DROP COLUMN complaint_category;")
    op.execute("ALTER TABLE evaluations DROP COLUMN is_complaint;")
    op.execute("ALTER TABLE evaluations DROP COLUMN topics;")
    op.execute("ALTER TABLE evaluations DROP COLUMN customer_intent;")
    op.execute("ALTER TABLE evaluations DROP COLUMN sentiment_score;")
    op.execute("ALTER TABLE evaluations DROP COLUMN sentiment_label;")
