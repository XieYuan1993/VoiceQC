"""Knowledge-base documents CRUD (per project).

Documents are created 'processing' and a worker task chunks + embeds them;
the recording evaluator later retrieves chunks to judge answer correctness.
"""
from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import KbDocument, User

from app import queue
from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.schemas import (
    KbDocumentDetailOut,
    KbDocumentIn,
    KbDocumentOut,
    KbDocumentPatchIn,
    KbRetrievalHit,
    KbRetrieveIn,
    KbRetrieveOut,
)

router = APIRouter(prefix="/api/kb/documents", tags=["kb"])


def _out(d: KbDocument) -> KbDocumentOut:
    return KbDocumentOut(
        id=d.id,
        title=d.title,
        source=d.source,
        status=d.status,
        chunk_count=d.chunk_count,
        error=d.error,
        char_count=len(d.content or ""),
        created_at=d.created_at,
    )


@router.get("", response_model=list[KbDocumentOut])
async def list_documents(
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[KbDocumentOut]:
    stmt = (
        select(KbDocument)
        .where(KbDocument.project_id == project_id)
        .order_by(KbDocument.created_at.desc())
    )
    return [_out(d) for d in (await session.execute(stmt)).scalars().all()]


@router.post("", response_model=KbDocumentOut)
async def create_document(
    payload: KbDocumentIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> KbDocumentOut:
    doc = KbDocument(
        project_id=project_id,
        title=payload.title.strip(),
        source=(payload.source.strip() or None) if payload.source else None,
        content=payload.content,
        status="processing",
    )
    session.add(doc)
    await session.flush()
    log_audit(
        session, action="kb.create", user_id=user.id, actor_email=user.email,
        object_type="kb_document", object_id=str(doc.id), details={"title": doc.title},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send("voiceqa.kb.ingest_document", str(doc.id))
    return _out(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> None:
    doc = await session.get(KbDocument, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    log_audit(
        session, action="kb.delete", user_id=user.id, actor_email=user.email,
        object_type="kb_document", object_id=str(doc.id), details={"title": doc.title},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.delete(doc)  # cascades to kb_chunks
    await session.commit()


def _extract_pdf(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


@router.get("/{document_id}", response_model=KbDocumentDetailOut)
async def get_document(
    document_id: uuid.UUID,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> KbDocumentDetailOut:
    doc = await session.get(KbDocument, document_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return KbDocumentDetailOut(
        id=doc.id, title=doc.title, source=doc.source, status=doc.status,
        chunk_count=doc.chunk_count, error=doc.error, char_count=len(doc.content or ""),
        created_at=doc.created_at, content=doc.content,
    )


@router.patch("/{document_id}", response_model=KbDocumentOut)
async def update_document(
    document_id: uuid.UUID,
    payload: KbDocumentPatchIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> KbDocumentOut:
    doc = await session.get(KbDocument, document_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    reingest = False
    if payload.title is not None:
        doc.title = payload.title.strip()
    if payload.source is not None:
        doc.source = payload.source.strip() or None
    if payload.content is not None and payload.content != doc.content:
        doc.content = payload.content
        doc.status = "processing"
        reingest = True
    log_audit(
        session, action="kb.update", user_id=user.id, actor_email=user.email,
        object_type="kb_document", object_id=str(doc.id), details={"title": doc.title},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    if reingest:
        queue.send("voiceqa.kb.ingest_document", str(doc.id))
    return _out(doc)


@router.post("/retrieve", response_model=KbRetrieveOut)
async def retrieve(
    payload: KbRetrieveIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
) -> KbRetrieveOut:
    """Embed a question and return the KB chunks it would retrieve — a tuning aid."""
    result = queue.celery_client.send_task(
        "voiceqa.kb.test_retrieval", args=[str(project_id), payload.query], queue="llm"
    )
    try:
        hits = await asyncio.to_thread(result.get, timeout=30)
    except Exception as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "retrieval is unavailable — is the worker running?",
        ) from e
    return KbRetrieveOut(hits=[KbRetrievalHit(**h) for h in (hits or [])])


@router.post("/upload", response_model=KbDocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> KbDocumentOut:
    """Create a KB document from an uploaded PDF, TXT or Markdown file."""
    raw = await file.read()
    name = file.filename or "document"
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        try:
            text = _extract_pdf(raw)
        except Exception as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"could not read PDF: {e}") from e
    elif ext in ("", ".txt", ".md", ".markdown", ".text"):
        text = raw.decode("utf-8", errors="replace")
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"unsupported file type {ext!r}; use PDF, TXT or MD"
        )
    text = text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no extractable text in the file")
    doc = KbDocument(
        project_id=project_id,
        title=((title or Path(name).stem).strip()[:300]) or name,
        source=name,
        content=text[:200_000],
        status="processing",
    )
    session.add(doc)
    await session.flush()
    log_audit(
        session, action="kb.create", user_id=user.id, actor_email=user.email,
        object_type="kb_document", object_id=str(doc.id), details={"title": doc.title},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send("voiceqa.kb.ingest_document", str(doc.id))
    return _out(doc)
