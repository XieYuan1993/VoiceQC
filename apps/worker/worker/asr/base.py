"""Pluggable batch-ASR adapter contract (requirement: "Google ASR first").

The start/poll split exists so Celery can resume: `start_batch` returns a
provider operation name that is persisted on the recording row; a redelivered
task re-attaches via `fetch_result` instead of paying for a second
transcription.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ChannelFile:
    """One mono audio object to transcribe, tagged with who is speaking."""

    uri: str  # gs://...
    channel_role: str  # broker | customer | mixed


@dataclass
class AdaptationPhrase:
    value: str
    boost: float = 10.0


@dataclass
class SegmentResult:
    start_ms: int
    end_ms: int
    text: str
    language: str | None = None
    confidence: float | None = None
    # Optional word timings [(begin_ms, word_text), …]. When present, the merge
    # step can split this segment where the OTHER channel interjects, so turns
    # interleave in true conversational order instead of one block per channel.
    words: list[tuple[int, str]] | None = None


@dataclass
class FileResult:
    uri: str  # input uri, matches a ChannelFile.uri
    segments: list[SegmentResult] = field(default_factory=list)
    language_detected: str | None = None
    billed_seconds: float = 0.0
    error: str | None = None


class BatchASRAdapter(Protocol):
    provider: str

    def start_batch(
        self,
        files: list[ChannelFile],
        *,
        language_mode: str,
        adaptation_phrases: list[AdaptationPhrase],
        model: str,
        output_prefix_uri: str | None = None,
    ) -> str:
        """Kick off batch recognition; returns the provider operation name.

        output_prefix_uri=None -> results returned inline in the operation
        response (no bucket write; right for call-sized audio). Set a gs://
        prefix only for very long files where inline results could exceed
        operation size limits.
        """
        ...

    def fetch_result(self, operation_name: str) -> list[FileResult] | None:
        """None while still running; FileResults when done.

        Raises on terminal operation failure.
        """
        ...
