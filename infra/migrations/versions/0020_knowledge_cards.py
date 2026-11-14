"""Project-scoped keyword knowledge cards for transcript assistance."""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_knowledge_cards"
down_revision = "0019_audio_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("trigger_words", postgresql.JSONB(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("project_id", "code", name="uq_knowledge_cards_project_code"),
    )
    op.create_index("ix_knowledge_cards_project_id", "knowledge_cards", ["project_id"])
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "data/0020_fwd_knowledge_cards.json").read_text(
            encoding="utf-8"
        )
    )
    projects = sa.table(
        "projects", sa.column("id", postgresql.UUID()), sa.column("slug", sa.Text())
    )
    cards = sa.table(
        "knowledge_cards",
        sa.column("project_id", postgresql.UUID()),
        sa.column("code", sa.Text()),
        sa.column("title", sa.Text()),
        sa.column("trigger_words", postgresql.JSONB()),
        sa.column("content", postgresql.JSONB()),
    )
    items = sa.func.jsonb_array_elements(
        sa.cast(op.inline_literal(json.dumps(payload, ensure_ascii=False)), postgresql.JSONB())
    ).table_valued("value")
    value = sa.cast(items.c.value, postgresql.JSONB())
    query = (
        sa.select(
            projects.c.id,
            value["code"].astext,
            value["title"].astext,
            value["trigger_words"],
            value["content"],
        )
        .select_from(projects.join(items, sa.true()))
        .where(projects.c.slug == op.inline_literal("fwd-insurance-demo"))
    )
    op.execute(
        cards.insert().from_select(
            ["project_id", "code", "title", "trigger_words", "content"], query
        )
    )


def downgrade():
    op.drop_table("knowledge_cards")
