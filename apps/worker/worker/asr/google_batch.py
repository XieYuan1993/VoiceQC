"""Google Speech-to-Text v2 BatchRecognize adapter.

Verified constraints (DESIGN.md §1a):
- chirp_2 @ asia-southeast1 (no HK region exists; chirp_3 is US/EU-only)
- batch input must be GCS URIs; max 15 files/request (we send 1-2)
- chirp does NOT support the explicit multi-language list — language_mode
  "auto" maps to language-agnostic transcription (language_codes=["auto"])
- results come back INLINE in the operation response by default — no result
  files in GCS and no Speech-service-agent bucket grant. Inline is a Google
  hard limit of ONE audio file per request, so in inline mode we fire one
  BatchRecognize per channel file and return an opaque JSON token mapping
  uri -> operation name (the caller just persists/passes it back, same as a
  single operation name). Pass output_prefix_uri to switch to GcsOutputConfig
  (single multi-file request) for multi-hour files.
"""

from __future__ import annotations

import json
import re

from google.api_core.client_options import ClientOptions
from google.cloud import speech_v2
from google.longrunning import operations_pb2
from loguru import logger
from voiceqa_shared import gcs

from worker.asr.base import AdaptationPhrase, ChannelFile, FileResult, SegmentResult
from worker.settings import settings

# Google rejects phrase-set boosts above 20; per-request inline phrase cap.
MAX_BOOST = 20.0
MAX_PHRASES = 300


def _duration_to_seconds(value: str | None) -> float:
    """'46.5s' (JSON duration form) -> 46.5"""
    if not value:
        return 0.0
    m = re.match(r"^([\d.]+)s$", value)
    return float(m.group(1)) if m else 0.0


# chirp emits Chinese with a space between every character ("騰 訊"), which
# breaks substring search and reads badly. Collapse whitespace between CJK
# chars / fullwidth punctuation while leaving Latin word spacing intact.
_CJK = r"　-〿㐀-䶿一-鿿＀-￯"
_CJK_SPACE = re.compile(f"(?<=[{_CJK}])\\s+(?=[{_CJK}])")


def _normalize_cjk_spacing(text: str) -> str:
    return _CJK_SPACE.sub("", text)


# chirp hallucinates degenerate repetition on silence / hold / noise — a short
# unit repeated many times ("企權企權企權…", "哦, 哦, 哦…", "拜拜拜拜"). Collapse
# any 1-8 char unit repeated 4+ times in a row (separators between repeats
# allowed) down to two copies. Genuine 2-3x emphasis ("好好", "唔該唔該") is
# below the threshold and preserved. CRITICAL: only collapse units containing
# a Chinese character — repeated DIGITS are real numbers (100000, 20000), never
# hallucination, and must never be touched.
_REPEAT = re.compile(r"([^\s,，、。!?！？]{1,8}?)(?:[\s,，、。]*\1){3,}")
_HAN = re.compile(r"[㐀-鿿]")
# chirp often spells numbers out digit-by-digit ("1 0 0"); join them so a real
# number reads as a number AND so digit-loop hallucinations form a single unit.
_DIGIT_SPACE = re.compile(r"(?<=[0-9])\s+(?=[0-9])")


def _collapse_repeats(text: str) -> str:
    def repl(m: re.Match) -> str:
        unit = m.group(1)
        # Preserve only single-char digit/Latin runs — that's how real numbers
        # look (the zeros in 100000). Collapse everything else repeated 4+ times:
        # CJK loops, and multi-digit loops ("18149"x20 is noise, not a number).
        if len(unit) < 2 and not _HAN.search(unit):
            return m.group(0)
        return unit * 2

    return _REPEAT.sub(repl, text)


def _clean_transcript(text: str) -> str:
    return _collapse_repeats(_DIGIT_SPACE.sub("", _normalize_cjk_spacing(text.strip())))


class GoogleBatchASR:
    provider = "google"

    def __init__(self, *, project: str | None = None, location: str | None = None) -> None:
        self.project = project or settings.GOOGLE_CLOUD_PROJECT
        self.location = location or settings.GOOGLE_STT_LOCATION
        if not self.project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set")
        # REST, not gRPC: Celery prefork forks workers, and gRPC's c-ares
        # resolver breaks in forked children on macOS ("Could not contact
        # DNS servers"). REST uses plain HTTP and is fork-safe.
        self._client = speech_v2.SpeechClient(
            transport="rest",
            client_options=ClientOptions(api_endpoint=f"{self.location}-speech.googleapis.com"),
        )

    # -- start ---------------------------------------------------------------

    def start_batch(
        self,
        files: list[ChannelFile],
        *,
        language_mode: str,
        adaptation_phrases: list[AdaptationPhrase],
        model: str,
        output_prefix_uri: str | None = None,
    ) -> str:
        language_codes = ["auto"] if language_mode == "auto" else [language_mode]

        config = speech_v2.RecognitionConfig(
            auto_decoding_config=speech_v2.AutoDetectDecodingConfig(),
            model=model,
            language_codes=language_codes,
            features=speech_v2.RecognitionFeatures(
                enable_word_time_offsets=True,
                enable_automatic_punctuation=True,
            ),
        )
        if adaptation_phrases:
            inline = speech_v2.PhraseSet(
                phrases=[
                    speech_v2.PhraseSet.Phrase(
                        value=p.value, boost=min(p.boost, MAX_BOOST)
                    )
                    for p in adaptation_phrases[:MAX_PHRASES]
                ]
            )
            config.adaptation = speech_v2.SpeechAdaptation(
                phrase_sets=[
                    speech_v2.SpeechAdaptation.AdaptationPhraseSet(inline_phrase_set=inline)
                ]
            )

        recognizer = f"projects/{self.project}/locations/{self.location}/recognizers/_"

        if output_prefix_uri:
            # GCS output supports many files in one request.
            request = speech_v2.BatchRecognizeRequest(
                recognizer=recognizer,
                config=config,
                files=[speech_v2.BatchRecognizeFileMetadata(uri=f.uri) for f in files],
                recognition_output_config=speech_v2.RecognitionOutputConfig(
                    gcs_output_config=speech_v2.GcsOutputConfig(uri=output_prefix_uri),
                ),
            )
            operation = self._client.batch_recognize(request=request)
            name = operation.operation.name
            logger.info("BatchRecognize started (gcs output): {} ({} files)", name, len(files))
            return name

        # Inline output: hard limit of one file per request -> one op per file.
        ops: dict[str, str] = {}
        for f in files:
            request = speech_v2.BatchRecognizeRequest(
                recognizer=recognizer,
                config=config,
                files=[speech_v2.BatchRecognizeFileMetadata(uri=f.uri)],
                recognition_output_config=speech_v2.RecognitionOutputConfig(
                    inline_response_config=speech_v2.InlineOutputConfig(),
                ),
            )
            operation = self._client.batch_recognize(request=request)
            ops[f.uri] = operation.operation.name
        logger.info("BatchRecognize started (inline): {} operations", len(ops))
        return json.dumps(ops)

    # -- poll ----------------------------------------------------------------

    def fetch_result(self, operation_name: str) -> list[FileResult] | None:
        # Inline mode stores a JSON token mapping uri -> operation name
        # (one op per file); GCS mode stores a single bare operation name.
        if operation_name.lstrip().startswith("{"):
            ops: dict[str, str] = json.loads(operation_name)
            merged: list[FileResult] = []
            for op_name in ops.values():
                results = self._fetch_single(op_name)
                if results is None:
                    return None  # any op still running -> whole set pending
                merged.extend(results)
            return merged
        return self._fetch_single(operation_name)

    def _fetch_single(self, operation_name: str) -> list[FileResult] | None:
        op = self._client.get_operation(operations_pb2.GetOperationRequest(name=operation_name))
        if not op.done:
            return None
        if op.HasField("error"):
            raise RuntimeError(f"BatchRecognize failed: {op.error.message}")

        response = speech_v2.BatchRecognizeResponse.deserialize(op.response.value)
        results: list[FileResult] = []
        for input_uri, file_result in response.results.items():
            if file_result.error and file_result.error.message:
                results.append(FileResult(uri=input_uri, error=file_result.error.message))
                continue

            inline = getattr(file_result, "inline_result", None)
            if inline is not None and inline.transcript:
                # Same dict shape as the GCS output JSON (camelCase keys,
                # durations as "45.5s" strings) — one parser serves both.
                data = speech_v2.BatchRecognizeResults.to_dict(
                    inline.transcript, preserving_proto_field_name=False
                )
                parsed = self._parse_results_data(input_uri, data)
                if not parsed.billed_seconds:
                    # Inline mode reports billing on the file-result envelope,
                    # not inside the transcript payload.
                    meta = getattr(file_result, "metadata", None)
                    billed = getattr(meta, "total_billed_duration", None)
                    if billed is not None:
                        parsed.billed_seconds = billed.total_seconds()
                results.append(parsed)
                continue

            output_uri = self._output_uri(file_result)
            if not output_uri:
                results.append(FileResult(uri=input_uri, error="no inline or GCS result"))
                continue
            results.append(
                self._parse_results_data(input_uri, json.loads(gcs.read_uri_bytes(output_uri)))
            )
        return results

    @staticmethod
    def _output_uri(file_result) -> str | None:
        cloud = getattr(file_result, "cloud_storage_result", None)
        if cloud is not None and getattr(cloud, "uri", ""):
            return cloud.uri
        # Older library versions expose the output location as a flat field.
        return getattr(file_result, "uri", "") or None

    @staticmethod
    def _parse_results_data(input_uri: str, data: dict) -> FileResult:
        """Parse BatchRecognizeResults (inline proto-as-dict or GCS JSON)."""
        segments: list[SegmentResult] = []
        languages: dict[str, int] = {}
        prev_end_ms = 0
        for result in data.get("results", []):
            alternatives = result.get("alternatives") or []
            if not alternatives or not alternatives[0].get("transcript", "").strip():
                continue
            alt = alternatives[0]
            end_ms = int(_duration_to_seconds(result.get("resultEndOffset")) * 1000)
            words = alt.get("words") or []
            start_ms = (
                int(_duration_to_seconds(words[0].get("startOffset")) * 1000)
                if words
                else prev_end_ms
            )
            language = (result.get("languageCode") or "").lower() or None
            if language:
                languages[language] = languages.get(language, 0) + 1
            segments.append(
                SegmentResult(
                    start_ms=start_ms,
                    end_ms=end_ms or start_ms,
                    text=_clean_transcript(alt["transcript"]),
                    language=language,
                    confidence=alt.get("confidence"),
                )
            )
            prev_end_ms = end_ms
        billed = _duration_to_seconds((data.get("metadata") or {}).get("totalBilledDuration"))
        dominant = max(languages, key=languages.get) if languages else None
        return FileResult(
            uri=input_uri,
            segments=segments,
            language_detected=dominant,
            billed_seconds=billed,
        )
