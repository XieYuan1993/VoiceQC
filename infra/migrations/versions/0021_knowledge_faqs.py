"""Project-scoped FAQs and FWD demo FAQ seed."""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_knowledge_faqs"
down_revision = "0020_knowledge_cards"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_faqs",
        sa.Column(
            "id", postgresql.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *[
            sa.Column(name, sa.Text(), nullable=False)
            for name in ("code", "category", "question", "answer")
        ],
        *[
            sa.Column(name, sa.Text(), nullable=False, server_default=sa.text("''"))
            for name in ("source", "demo_notice")
        ],
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("project_id", "code", name="uq_knowledge_faqs_project_code"),
    )
    op.create_index("ix_knowledge_faqs_project_id", "knowledge_faqs", ["project_id"])
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "data/0021_fwd_faqs.json").read_text(
            encoding="utf-8"
        )
    )
    columns = ("code", "category", "question", "answer", "source", "demo_notice")
    projects = sa.table(
        "projects", sa.column("id", postgresql.UUID()), sa.column("slug", sa.Text())
    )
    faqs = sa.table(
        "knowledge_faqs",
        sa.column("project_id", postgresql.UUID()),
        *[sa.column(name, sa.Text()) for name in columns],
    )
    items = sa.func.jsonb_array_elements(
        sa.cast(op.inline_literal(json.dumps(payload, ensure_ascii=False)), postgresql.JSONB())
    ).table_valued("value")
    value = sa.cast(items.c.value, postgresql.JSONB())
    query = (
        sa.select(projects.c.id, *[value[name].astext for name in columns])
        .select_from(projects.join(items, sa.true()))
        .where(projects.c.slug == op.inline_literal("fwd-insurance-demo"))
    )
    op.execute(faqs.insert().from_select(["project_id", *columns], query))


def downgrade():
    op.drop_table("knowledge_faqs")
