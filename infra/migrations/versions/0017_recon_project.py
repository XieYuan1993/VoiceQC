"""Scope reconciliation runs to a project."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_recon_project"
down_revision = "0016_backfill_evaluator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recon_runs", sa.Column("project_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_recon_runs_project_id_projects",
        "recon_runs",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Historical runs predate project scoping and may contain mixed-project
    # recordings. Keep them under the original/default project; Demo projects
    # should create a fresh, correctly scoped run after deployment.
    op.execute(
        """
        UPDATE recon_runs
        SET project_id = (
            SELECT id
            FROM projects
            ORDER BY is_default DESC, created_at ASC
            LIMIT 1
        )
        WHERE project_id IS NULL
        """
    )
    op.alter_column("recon_runs", "project_id", nullable=False)
    op.create_index(
        "ix_recon_runs_project_id_started_at",
        "recon_runs",
        ["project_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recon_runs_project_id_started_at", table_name="recon_runs")
    op.drop_constraint(
        "fk_recon_runs_project_id_projects", "recon_runs", type_="foreignkey"
    )
    op.drop_column("recon_runs", "project_id")
