"""KB ingest: chunk a document, embed its chunks (Vertex), store kb_chunks.

Documents are created 'processing' by the API; this task flips them to
'ready' (with chunk_count) or 'failed' (with an error message).
"""
from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import delete, select
from voiceqa_shared.db_models import KbChunk, KbDocument

from worker.celery_app import app
from worker.db import SessionLocal
from worker.kb import chunk_text, cosine
from worker.llm.embeddings import Embedder


@app.task(name="voiceqa.kb.ingest_document")
def ingest_document(document_id: str) -> dict:
    doc_uuid = uuid.UUID(document_id)
    with SessionLocal() as session:
        doc = session.get(KbDocument, doc_uuid)
        if doc is None:
            logger.warning("kb ingest: document {} not found", document_id)
            return {"document_id": document_id, "status": "missing"}
        try:
            # Re-chunk from scratch so re-ingest is idempotent.
            session.execute(delete(KbChunk).where(KbChunk.document_id == doc.id))
            chunks = chunk_text(doc.content)
            embeddings = Embedder().embed_documents(chunks) if chunks else []
            for seq, (content, emb) in enumerate(zip(chunks, embeddings, strict=True)):
                session.add(
                    KbChunk(
                        document_id=doc.id,
                        project_id=doc.project_id,
                        seq=seq,
                        content=content,
                        embedding=emb,
                    )
                )
            doc.chunk_count = len(chunks)
            doc.status = "ready"
            doc.error = None
            session.commit()
            logger.info("kb ingest: {} -> {} chunks", document_id, len(chunks))
            return {"document_id": document_id, "status": "ready", "chunks": len(chunks)}
        except Exception as e:
            session.rollback()
            doc = session.get(KbDocument, doc_uuid)
            if doc is not None:
                doc.status = "failed"
                doc.error = str(e)[:500]
                session.commit()
            logger.exception("kb ingest failed for {}", document_id)
            return {"document_id": document_id, "status": "failed"}


@app.task(name="voiceqa.kb.test_retrieval")
def test_retrieval(project_id: str, query: str, k: int = 6) -> list[dict]:
    """Embed a query and return the top-k most similar KB chunks for the project
    (a tuning aid surfaced in the KB UI)."""
    with SessionLocal() as session:
        chunks = (
            session.execute(select(KbChunk).where(KbChunk.project_id == uuid.UUID(project_id)))
            .scalars()
            .all()
        )
        if not chunks:
            return []
        q_emb = Embedder().embed_query(query)
        ranked = sorted(
            ((cosine(q_emb, c.embedding), c) for c in chunks),
            key=lambda t: t[0],
            reverse=True,
        )
        return [
            {"seq": c.seq, "content": c.content, "score": round(float(score), 4)}
            for score, c in ranked[:k]
        ]
