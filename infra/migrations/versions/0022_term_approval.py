"""Require administrator approval for newly submitted terms."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_term_approval"
down_revision = "0021_knowledge_faqs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "industry_terms",
        sa.Column("approval_status", sa.Text(), nullable=False, server_default="approved"),
    )
    for name in ("submitted_by", "reviewed_by"):
        op.add_column("industry_terms", sa.Column(name, sa.Text()))
    for name in ("submitted_at", "reviewed_at"):
        op.add_column("industry_terms", sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column(
        "industry_terms",
        sa.Column(
            "pending_rules",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_term_approval_status",
        "industry_terms",
        "approval_status IN ('pending', 'approved', 'rejected')",
    )
    op.create_check_constraint(
        "ck_term_approved_active", "industry_terms", "NOT active OR approval_status = 'approved'"
    )


def downgrade():
    op.drop_constraint("ck_term_approved_active", "industry_terms", type_="check")
    op.drop_constraint("ck_term_approval_status", "industry_terms", type_="check")
    for name in (
        "pending_rules",
        "reviewed_at",
        "submitted_at",
        "reviewed_by",
        "submitted_by",
        "approval_status",
    ):
        op.drop_column("industry_terms", name)
