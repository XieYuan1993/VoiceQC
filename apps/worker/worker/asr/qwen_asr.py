"""Qwen3-ASR (Alibaba Cloud Model Studio / DashScope) — an alternative ASR
provider. Dedicated speech model — faster and cheaper than Gemini multimodal,
comparable Cantonese accuracy.

Uses the ASYNCHRONOUS file-transcription API (qwen3-asr-flash-filetrans), which
returns sentence-level timestamps — so each channel splits into timed segments
(interleaved + click-to-seek in the UI), unlike the fast OpenAI-compatible mode
which returns one untimed block per channel. The API fetches the audio from a
URL, so each channel is converted to 16 kHz mono WAV, uploaded to a temp GCS
object, and exposed via a short-lived signed URL (deleted afterwards).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import uuid

import httpx
from loguru import logger
from voiceqa_shared import gcs

from worker import audio
from worker.asr.base import AdaptationPhrase, ChannelFile, FileResult, SegmentResult
from worker.settings import settings

POLL_INTERVAL_S = 2
MAX_POLLS = 120  # ~4 min ceiling

# VoiceQA language_mode -> Qwen language code. Unmapped (e.g. "auto") omits the
# parameter so Qwen auto-detects — keeps the provider usable beyond Cantonese.
_QWEN_LANG = {"yue-Hant-HK": "yue", "cmn-Hans-CN": "zh", "en-US": "en"}


class QwenASR:
    provider = "qwen"

    def __init__(self) -> None:
        if not settings.DASHSCOPE_BASE_URL or not settings.DASHSCOPE_API_KEY.get_secret_value():
            raise RuntimeError(
                "Qwen ASR selected but DASHSCOPE_BASE_URL / DASHSCOPE_API_KEY are not set"
            )
        self.base = settings.DASHSCOPE_BASE_URL.rstrip("/")
        self.key = settings.DASHSCOPE_API_KEY.get_secret_value()
        self._headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _transcribe_channel(self, uri: str, model: str, language: str | None) -> tuple[list[dict], float]:
        # The async file API needs a single non-"filetrans" model -> -filetrans.
        async_model = model if model.endswith("-filetrans") else f"{model}-filetrans"
        tmp_uri: str | None = None
        try:
            with tempfile.TemporaryDirectory() as d:
                raw, wav = f"{d}/in", f"{d}/out.wav"
                gcs.download_uri_to_file(uri, raw)
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-ar", "16000", "-ac", "1", wav],
                    check=True,
                )
                duration = audio.probe(wav).duration_seconds
                tmp_uri = gcs.upload_file(f"qwen-tmp/{uuid.uuid4().hex}.wav", wav)
            file_url = gcs.signed_url(tmp_uri, minutes=30)
            if not file_url:
                raise RuntimeError("cannot sign temp audio URL for Qwen")

            # enable_itn: inverse text normalization — spoken numbers become
            # digits ("二零三二九八" -> "203298"), which reads better and helps
            # stock-code matching in the correctness check.
            params: dict = {"enable_words": True, "enable_itn": True}
            if language:
                params["language"] = language
            submit = httpx.post(
                f"{self.base}/api/v1/services/audio/asr/transcription",
                headers={**self._headers, "X-DashScope-Async": "enable"},
                json={
                    "model": async_model,
                    "input": {"file_url": file_url},
                    "parameters": params,
                },
                timeout=60,
            )
            submit.raise_for_status()
            task_id = submit.json()["output"]["task_id"]

            transcription_url = None
            for _ in range(MAX_POLLS):
                time.sleep(POLL_INTERVAL_S)
                poll = httpx.get(f"{self.base}/api/v1/tasks/{task_id}", headers=self._headers, timeout=30)
                poll.raise_for_status()
                out = poll.json()["output"]
                state = out.get("task_status")
                if state == "SUCCEEDED":
                    transcription_url = out["result"]["transcription_url"]
                    break
                if state in ("FAILED", "UNKNOWN"):
                    # A channel with only silence/no speech (e.g. a 3s hangup) comes
                    # back FAILED with this code — that's a valid empty channel, not
                    # a pipeline error. Let the other channel carry the transcript.
                    if "NO_VALID_FRAGMENT" in json.dumps(out).upper():
                        logger.info("Qwen: no speech in channel, treating as empty: {}", uri)
                        return [], duration
                    raise RuntimeError(f"Qwen task {state}: {out.get('message') or out}")
            if transcription_url is None:
                raise RuntimeError("Qwen task did not complete in time")

            result = httpx.get(transcription_url, timeout=60).json()
            segs: list[dict] = []
            for tr in result.get("transcripts") or []:
                for sen in tr.get("sentences") or []:
                    text = str(sen.get("text") or "").strip()
                    if not text:
                        continue
                    words = [
                        [int(w.get("begin_time") or 0), wt]
                        for w in (sen.get("words") or [])
                        if (wt := str(w.get("text") or w.get("word") or "").strip())
                    ]
                    segs.append(
                        {
                            "start_ms": int(sen.get("begin_time") or 0),
                            "end_ms": int(sen.get("end_time") or 0),
                            "text": text,
                            "words": words,
                        }
                    )
            return segs, duration
        finally:
            if tmp_uri:
                gcs.delete_uri(tmp_uri)

    def start_batch(
        self,
        files: list[ChannelFile],
        *,
        language_mode: str,
        adaptation_phrases: list[AdaptationPhrase],
        model: str,
        output_prefix_uri: str | None = None,
    ) -> str:
        from worker.asr.google_batch import _clean_transcript

        language = _QWEN_LANG.get(language_mode)
        out: list[dict] = []
        for f in files:
            segs, duration = self._transcribe_channel(f.uri, model, language)
            for s in segs:
                s["text"] = _clean_transcript(s["text"])
            segs = [s for s in segs if s["text"]]
            out.append({"uri": f.uri, "segments": segs, "billed": duration})
        logger.info("Qwen transcribed {} channel(s) via {} (async, timestamped)", len(files), model)
        return json.dumps(out, ensure_ascii=False)

    def fetch_result(self, operation_name: str) -> list[FileResult]:
        data = json.loads(operation_name)
        results: list[FileResult] = []
        for ch in data:
            segments = [
                SegmentResult(
                    start_ms=s["start_ms"],
                    end_ms=s.get("end_ms", s["start_ms"]),
                    text=s["text"],
                    language="yue-Hant-HK",
                    confidence=None,
                    words=[(int(w[0]), str(w[1])) for w in (s.get("words") or [])] or None,
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
