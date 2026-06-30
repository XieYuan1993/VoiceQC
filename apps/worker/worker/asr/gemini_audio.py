"""Gemini multimodal audio transcription — an alternative ASR provider.

On noisy Cantonese telephony Gemini is dramatically better than chirp (it
understands context, so it doesn't fragment or hallucinate digit loops), at
comparable cost. There's no async long-running operation: each channel is
transcribed in one generate_content call, so `start_batch` does the work
synchronously and returns the serialized result as the resume token, and
`fetch_result` just decodes it — reusing the existing transcribe task flow
unchanged.
"""

from __future__ import annotations

import json
import re

from loguru import logger

from worker.asr.base import AdaptationPhrase, ChannelFile, FileResult, SegmentResult
from worker.settings import settings

_MIME = {
    "flac": "audio/flac",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
}

# Structured output: a list of timestamped utterances per channel.
_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_seconds": {"type": "number"},
                    "text": {"type": "string"},
                },
                "required": ["start_seconds", "text"],
            },
        }
    },
    "required": ["segments"],
}

# Resilient extraction: pull each complete {start_seconds, text} pair even if
# the JSON response was truncated mid-array (long calls can hit the token cap).
_SEG_RE = re.compile(r'"start_seconds"\s*:\s*([0-9.]+)\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"')


class GeminiAudioASR:
    provider = "gemini"

    def __init__(self) -> None:
        self.project = settings.GOOGLE_CLOUD_PROJECT
        # Gemini audio runs from the global endpoint (same residency note as the
        # evaluator — surface to the client).
        self.location = "global"

    def _prompt(self, role: str, phrases: list[AdaptationPhrase]) -> str:
        who = {
            "broker": "the broker / account executive",
            "customer": "the client",
            "mixed": "the broker and client",
        }.get(role, "the speakers")
        glossary = ""
        if phrases:
            terms = ", ".join(p.value for p in phrases[:120])
            glossary = (
                "\n\nHong Kong stock names/codes that may be mentioned — use these to "
                f"spell stock references correctly, but do NOT insert them otherwise: {terms}"
            )
        return (
            f"This is one audio channel ({who}) of a recorded Hong Kong stockbroker phone "
            "call in Cantonese (8 kHz telephony). Transcribe what is actually said, VERBATIM, "
            "in Traditional Chinese. Do not translate, summarise, correct, or invent content; "
            "if a stretch is silence or unintelligible, omit it. Write all numbers (prices, "
            "quantities, account numbers, ID numbers) as digits. Return JSON: an array "
            '"segments", each with start_seconds (approximate, a number) and text.' + glossary
        )

    def start_batch(
        self,
        files: list[ChannelFile],
        *,
        language_mode: str,
        adaptation_phrases: list[AdaptationPhrase],
        model: str,
        output_prefix_uri: str | None = None,
    ) -> str:
        from google import genai
        from google.genai import types

        from worker.asr.google_batch import _clean_transcript

        client = genai.Client(vertexai=True, project=self.project, location=self.location)
        out: list[dict] = []
        for f in files:
            ext = f.uri.rsplit(".", 1)[-1].lower()
            audio = types.Part.from_uri(file_uri=f.uri, mime_type=_MIME.get(ext, "audio/flac"))
            resp = client.models.generate_content(
                model=model,
                contents=[self._prompt(f.channel_role, adaptation_phrases), audio],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=_SCHEMA,
                    max_output_tokens=16384,
                ),
            )
            segs: list[dict] = []
            last_ms = 0
            # Regex-extract complete segments — tolerant of a truncated tail.
            for start_s, text_raw in _SEG_RE.findall(resp.text or ""):
                try:
                    start_ms = int(float(start_s) * 1000)
                    text = _clean_transcript(json.loads(f'"{text_raw}"'))
                except (ValueError, json.JSONDecodeError):
                    continue
                if not text:
                    continue
                segs.append({"start_ms": start_ms, "text": text})
                last_ms = max(last_ms, start_ms)
            out.append({"uri": f.uri, "segments": segs, "billed": last_ms / 1000})
        logger.info("Gemini transcribed {} channel(s) via {}", len(files), model)
        return json.dumps(out, ensure_ascii=False)

    def fetch_result(self, operation_name: str) -> list[FileResult]:
        data = json.loads(operation_name)
        results: list[FileResult] = []
        for ch in data:
            segments = [
                SegmentResult(
                    start_ms=s["start_ms"],
                    end_ms=s["start_ms"],
                    text=s["text"],
                    language="yue-Hant-HK",
                    confidence=None,
                )
                for s in ch["segments"]
            ]
            results.append(
                FileResult(
                    uri=ch["uri"],
                    segments=segments,
                    language_detected="yue-Hant-HK",
                    billed_seconds=float(ch.get("billed") or 0),
                )
            )
        return results
