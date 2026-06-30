"""Checklist / script-adherence: per-project required items + per-call coverage.

A `checklist_items` config table (like extraction_fields) plus snapshot/results/
score columns on evaluations, populated by the same Gemini evaluation call.
"""
from __future__ import annotations

from alembic import op

revision = "0011_checklist"
down_revision = "0010_evaluation_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE checklist_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            label TEXT NOT NULL,
            description TEXT,
            required BOOLEAN NOT NULL DEFAULT true,
            active BOOLEAN NOT NULL DEFAULT true,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_checklist_items_project_id_key UNIQUE (project_id, key)
        );
        """
    )
    op.execute("CREATE INDEX ix_checklist_items_project_id ON checklist_items (project_id);")
    op.execute(
        "ALTER TABLE evaluations ADD COLUMN checklist_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb;"
    )
    op.execute(
        "ALTER TABLE evaluations ADD COLUMN checklist_results JSONB NOT NULL DEFAULT '[]'::jsonb;"
    )
    op.execute("ALTER TABLE evaluations ADD COLUMN checklist_score NUMERIC(5, 2);")


def downgrade() -> None:
    op.execute("ALTER TABLE evaluations DROP COLUMN checklist_score;")
    op.execute("ALTER TABLE evaluations DROP COLUMN checklist_results;")
    op.execute("ALTER TABLE evaluations DROP COLUMN checklist_snapshot;")
    op.execute("DROP TABLE checklist_items;")
