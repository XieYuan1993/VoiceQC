"""Knowledge base + answer-correctness (RAG).

Per-project kb_documents + kb_chunks (chunk embeddings stored as JSONB float
arrays — this Postgres has no pgvector, so similarity is computed in Python),
plus correctness columns on evaluations populated by the same Gemini call using
retrieved KB context.
"""
from __future__ import annotations

from alembic import op

revision = "0012_kb_correctness"
down_revision = "0011_checklist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kb_documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            source TEXT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'processing',
            chunk_count INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_kb_documents_project_id ON kb_documents (project_id);")
    op.execute(
        """
        CREATE TABLE kb_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_kb_chunks_project_id ON kb_chunks (project_id);")
    op.execute("CREATE INDEX ix_kb_chunks_document_id ON kb_chunks (document_id);")
    op.execute(
        "ALTER TABLE evaluations ADD COLUMN correctness_findings JSONB NOT NULL "
        "DEFAULT '[]'::jsonb;"
    )
    op.execute("ALTER TABLE evaluations ADD COLUMN correctness_score NUMERIC(5, 2);")


def downgrade() -> None:
    op.execute("ALTER TABLE evaluations DROP COLUMN correctness_score;")
    op.execute("ALTER TABLE evaluations DROP COLUMN correctness_findings;")
    op.execute("DROP TABLE kb_chunks;")
    op.execute("DROP TABLE kb_documents;")
