"""Industry terms CRUD + CSV import.

Terms feed three consumers: STT adaptation phrases (Phase 1), the LLM
glossary (Phase 2), and the recon alias resolver (Phase 3). CSV columns
match mocks/data/industry_terms.csv: category,canonical,stock_code,aliases
(pipe-separated),notes.
"""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import IndustryTerm, User

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, TERMS_WRITE, require
from app.schemas import TermImportResult, TermIn, TermOut

router = APIRouter(prefix="/api/terms", tags=["terms"])

MAX_CSV_BYTES = 5 * 1024 * 1024


def _out(term: IndustryTerm) -> TermOut:
    return TermOut(
        id=term.id,
        category=term.category,
        canonical=term.canonical,
        stock_code=term.stock_code,
        aliases=list(term.aliases or []),
        boost=term.boost,
        active=term.active,
        notes=term.notes,
        created_at=term.created_at,
    )


def _normalize_code(code: str | None) -> str | None:
    if not code:
        return None
    stripped = code.strip().lstrip("0")
    return stripped or None


@router.get("", response_model=list[TermOut])
async def list_terms(
    include_inactive: bool = False,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[TermOut]:
    stmt = (
        select(IndustryTerm)
        .where(IndustryTerm.project_id == project_id)
        .order_by(IndustryTerm.category, IndustryTerm.canonical)
    )
    if not include_inactive:
        stmt = stmt.where(IndustryTerm.active.is_(True))
    terms = (await session.execute(stmt)).scalars().all()
    return [_out(t) for t in terms]


@router.post("", response_model=TermOut)
async def create_term(
    payload: TermIn,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(TERMS_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> TermOut:
    existing = (
        await session.execute(
            select(IndustryTerm.id).where(
                IndustryTerm.project_id == project_id,
                IndustryTerm.canonical == payload.canonical,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"term {payload.canonical!r} already exists")
    term = IndustryTerm(
        project_id=project_id,
        category=payload.category,
        canonical=payload.canonical,
        stock_code=_normalize_code(payload.stock_code),
        aliases=payload.aliases,
        boost=payload.boost,
        active=payload.active,
        notes=payload.notes,
    )
    session.add(term)
    await session.flush()
    log_audit(
        session, action="terms.create", user_id=user.id, actor_email=user.email,
        object_type="term", object_id=str(term.id), details={"canonical": term.canonical},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return _out(term)


@router.patch("/{term_id}", response_model=TermOut)
async def update_term(
    term_id: uuid.UUID,
    payload: TermIn,
    user: User = Depends(require(TERMS_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> TermOut:
    term = await session.get(IndustryTerm, term_id)
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "term not found")
    existing = (
        await session.execute(
            select(IndustryTerm.id).where(
                IndustryTerm.project_id == term.project_id,
                IndustryTerm.canonical == payload.canonical,
                IndustryTerm.id != term_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"term {payload.canonical!r} already exists")
    term.category = payload.category
    term.canonical = payload.canonical
    term.stock_code = _normalize_code(payload.stock_code)
    term.aliases = payload.aliases
    term.boost = payload.boost
    term.active = payload.active
    term.notes = payload.notes
    log_audit(
        session, action="terms.update", user_id=user.id, actor_email=user.email,
        object_type="term", object_id=str(term.id), details={"canonical": term.canonical},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return _out(term)


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_term(
    term_id: uuid.UUID,
    user: User = Depends(require(TERMS_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> None:
    term = await session.get(IndustryTerm, term_id)
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "term not found")
    log_audit(
        session, action="terms.delete", user_id=user.id, actor_email=user.email,
        object_type="term", object_id=str(term.id), details={"canonical": term.canonical},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.delete(term)
    await session.commit()


@router.post("/import-csv", response_model=TermImportResult)
async def import_csv(
    file: UploadFile,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(TERMS_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> TermImportResult:
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "csv too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"csv must be UTF-8: {e}") from e

    reader = csv.DictReader(io.StringIO(text))
    required = {"category", "canonical", "stock_code", "aliases", "notes"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"csv needs columns {sorted(required)}, got {reader.fieldnames}",
        )

    existing = {
        t.canonical: t
        for t in (
            await session.execute(
                select(IndustryTerm).where(IndustryTerm.project_id == project_id)
            )
        ).scalars().all()
    }
    created = updated = 0
    for row in reader:
        canonical = row["canonical"].strip()
        if not canonical:
            continue
        fields = {
            "category": row["category"].strip() or "other",
            "stock_code": _normalize_code(row["stock_code"]),
            "aliases": [a.strip() for a in row["aliases"].split("|") if a.strip()],
            "notes": row["notes"].strip() or None,
        }
        if canonical in existing:
            term = existing[canonical]
            for key, value in fields.items():
                setattr(term, key, value)
            updated += 1
        else:
            session.add(IndustryTerm(project_id=project_id, canonical=canonical, **fields))
            created += 1

    log_audit(
        session, action="terms.import_csv", user_id=user.id, actor_email=user.email,
        details={"created": created, "updated": updated, "filename": file.filename},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return TermImportResult(created=created, updated=updated)
