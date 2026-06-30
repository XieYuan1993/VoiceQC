"""Knowledge-base helpers: text chunking + cosine similarity (no pgvector here,
so retrieval ranks chunk embeddings in Python)."""
from __future__ import annotations

import math
import re

_TARGET = 900  # chars per chunk (roughly a short paragraph block)
_OVERLAP = 150


def _hard_split(s: str, target: int, overlap: int) -> list[str]:
    out: list[str] = []
    i = 0
    step = max(1, target - overlap)
    while i < len(s):
        out.append(s[i : i + target])
        i += step
    return out


def chunk_text(text: str, *, target: int = _TARGET, overlap: int = _OVERLAP) -> list[str]:
    """Split document text into retrieval chunks. Packs paragraphs up to ~target
    chars and hard-splits any single paragraph that is longer."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        pieces = _hard_split(p, target, overlap) if len(p) > target else [p]
        for piece in pieces:
            if not buf:
                buf = piece
            elif len(buf) + 1 + len(piece) <= target:
                buf = f"{buf}\n{piece}"
            else:
                chunks.append(buf)
                buf = piece
    if buf.strip():
        chunks.append(buf)
    if not chunks and text.strip():
        chunks = [text.strip()]
    return chunks


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
