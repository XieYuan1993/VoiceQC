"""Backfill starter evaluator config for projects created completely empty."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from voiceqa_shared.project_defaults import DEFAULT_EVAL_CRITERIA, DEFAULT_EXTRACTION_FIELDS

revision = "0016_backfill_evaluator"
down_revision = "0015_bulk_batch_rerun"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    project_ids = list(
        connection.execute(
            sa.text(
                """
                SELECT p.id
                FROM projects p
                WHERE NOT EXISTS (
                    SELECT 1 FROM eval_criteria c WHERE c.project_id = p.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM extraction_fields f WHERE f.project_id = p.id
                )
                """
            )
        ).scalars()
    )

    criteria = sa.table(
        "eval_criteria",
        sa.column("project_id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("category", sa.Text()),
        sa.column("score_type", sa.Text()),
        sa.column("severity", sa.Text()),
        sa.column("weight", sa.Float()),
        sa.column("sort_order", sa.Integer()),
    )
    fields = sa.table(
        "extraction_fields",
        sa.column("project_id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.Text()),
        sa.column("label", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("field_type", sa.Text()),
        sa.column("enum_options", postgresql.JSONB()),
        sa.column("scope", sa.Text()),
        sa.column("is_system", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )

    for project_id in project_ids:
        connection.execute(
            criteria.insert(),
            [{"project_id": project_id, **row} for row in DEFAULT_EVAL_CRITERIA],
        )
        connection.execute(
            fields.insert(),
            [
                {
                    "project_id": project_id,
                    "description": None,
                    "enum_options": None,
                    **row,
                }
                for row in DEFAULT_EXTRACTION_FIELDS
            ],
        )


def downgrade() -> None:
    # Data may have been edited or used after upgrade; do not delete it.
    pass
