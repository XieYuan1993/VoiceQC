"""Vertex multilingual text-embedding client (google-genai, REST).

Mirrors the GeminiLLM adapter's Vertex client construction. Used to index KB
chunks (RETRIEVAL_DOCUMENT) and to embed call text for retrieval
(RETRIEVAL_QUERY). This Postgres has no pgvector, so callers compute cosine
similarity in Python over a small per-project KB.
"""
from __future__ import annotations

from loguru import logger

from worker.settings import settings

EMBED_MODEL = "text-multilingual-embedding-002"
EMBED_DIM = 768
_BATCH = 50  # instances per embed_content request


def _looks_unavailable(err: Exception) -> bool:
    t = str(err)
    return any(s in t for s in ("NOT_FOUND", "404", "not found", "not supported"))


class Embedder:
    """Batches text into Vertex embeddings. The model is not served from every
    region, so default to us-central1 (verified) and fall back to global once."""

    provider = "vertex-embeddings"
    model = EMBED_MODEL
    dim = EMBED_DIM

    def __init__(self, *, project: str | None = None, location: str = "us-central1") -> None:
        self.project = project or settings.GOOGLE_CLOUD_PROJECT
        if not self.project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set")
        self.location = location
        self._client = self._make_client(self.location)

    def _make_client(self, location: str):
        from google import genai

        return genai.Client(vertexai=True, project=self.project, location=location)

    def _embed_batch(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types as genai_types

        config = genai_types.EmbedContentConfig(task_type=task_type)
        try:
            resp = self._client.models.embed_content(
                model=EMBED_MODEL, contents=texts, config=config
            )
        except Exception as e:
            if _looks_unavailable(e) and self.location != "global":
                logger.warning(
                    "embeddings not served from {} — falling back to the global endpoint",
                    self.location,
                )
                self.location = "global"
                self._client = self._make_client("global")
                resp = self._client.models.embed_content(
                    model=EMBED_MODEL, contents=texts, config=config
                )
            else:
                raise
        return [list(e.values) for e in resp.embeddings]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed KB chunks for indexing."""
        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            out.extend(self._embed_batch(texts[i : i + _BATCH], "RETRIEVAL_DOCUMENT"))
        return out

    def embed_query(self, text: str) -> list[float]:
        """Embed a call's text as a retrieval query."""
        return self._embed_batch([text], "RETRIEVAL_QUERY")[0]
