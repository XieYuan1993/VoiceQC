"""Gemini structured-output adapter (google-genai, Vertex AI).

Upgrades the Voicebot-Platform analysis.py pattern: the response schema is
enforced by constrained decoding (`response_schema`), not just prompt text;
fence-stripping stays as a defensive fallback.

The google-genai SDK is REST-based — no gRPC, so it is safe inside Celery
prefork children (unlike GAPIC gRPC transports; see asr/google_batch.py).

Region note: 3.x Flash models are frequently served from the `global`
endpoint only. We try the configured location first (asia-southeast1 for
residency) and fall back to `global` once, with a warning — the fallback
location sticks for the process lifetime.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from voiceqa_shared.llm_usage import extract_tokens

from worker.settings import settings


def _strip_json_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -len("```")]
    return s.strip()


def _looks_like_unavailable_model(err: Exception) -> bool:
    text = str(err)
    return "NOT_FOUND" in text or "404" in text or "was not found" in text


class GeminiLLM:
    provider = "gemini"

    def __init__(self, *, project: str | None = None, location: str | None = None) -> None:
        self.project = project or settings.GOOGLE_CLOUD_PROJECT
        if not self.project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set")
        self.location = location or settings.VERTEX_LLM_LOCATION
        self._client = self._make_client(self.location)

    def _make_client(self, location: str):
        from google import genai
        from google.genai import types as genai_types

        http_options = genai_types.HttpOptions(timeout=120)
        return genai.Client(vertexai=True, project=self.project, location=location,
                            http_options=http_options)

    def generate_structured(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.2,
    ) -> tuple[dict[str, Any], int, int]:
        from google.genai import types as genai_types

        config = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=temperature,
        )
        try:
            resp = self._client.models.generate_content(
                model=model, contents=prompt, config=config
            )
        except Exception as e:
            if _looks_like_unavailable_model(e) and self.location != "global":
                logger.warning(
                    "model {} not served from {} — falling back to the global endpoint "
                    "(data-residency caveat; pick a regional model for production)",
                    model,
                    self.location,
                )
                self.location = "global"
                self._client = self._make_client("global")
                resp = self._client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
            else:
                raise

        in_tok, out_tok = extract_tokens(resp)
        text = (resp.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        try:
            parsed = json.loads(_strip_json_fences(text))
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Gemini returned invalid JSON despite response_schema: {e}; raw={text[:200]!r}"
            ) from None
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Gemini response is not an object: {str(parsed)[:200]!r}")
        return parsed, in_tok, out_tok
