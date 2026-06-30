"""ffmpeg helpers: probe + channel split + FLAC normalize.

FLAC mono at the native sample rate (telephony is usually 8 kHz; never
upsample — STT bills by duration, not bytes, and chirp handles 8k natively).

Probe prefers ffprobe; falls back to parsing `ffmpeg -i` stderr because some
dev machines (this one included) ship ffmpeg without ffprobe.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class AudioInfo:
    channels: int
    sample_rate: int
    duration_seconds: float
    format: str


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path: str) -> AudioInfo:
    if shutil.which("ffprobe"):
        proc = _run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=channels,sample_rate,codec_name:format=duration",
                "-of", "json", path,
            ]
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            stream = data["streams"][0]
            return AudioInfo(
                channels=int(stream["channels"]),
                sample_rate=int(stream["sample_rate"]),
                duration_seconds=float(data["format"]["duration"]),
                format=stream.get("codec_name", "unknown"),
            )

    # Fallback: parse `ffmpeg -i` stderr.
    proc = _run(["ffmpeg", "-hide_banner", "-i", path])
    err = proc.stderr
    audio = re.search(
        r"Audio:\s*([A-Za-z0-9_]+)[^,]*,\s*(\d+)\s*Hz,\s*(stereo|mono|(\d+)(?:\.\d+)?\s*channels)",
        err,
    )
    duration = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    if not audio or not duration:
        raise RuntimeError(f"could not probe audio: {path} ({err[-300:]})")
    layout = audio.group(3)
    channels = 2 if layout == "stereo" else 1 if layout == "mono" else int(audio.group(4))
    h, m, s = duration.groups()
    return AudioInfo(
        channels=channels,
        sample_rate=int(audio.group(2)),
        duration_seconds=int(h) * 3600 + int(m) * 60 + float(s),
        format=audio.group(1),
    )


def _ffmpeg(args: list[str]) -> None:
    proc = _run(["ffmpeg", "-y", "-loglevel", "error", *args])
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")


def split_stereo_to_flac(path: str, left_out: str, right_out: str) -> None:
    # Loudness-normalise each channel independently (EBU R128). Telephony legs
    # often differ by several dB — the quieter side transcribes worse — so this
    # lifts both to a consistent level before ASR. Applied per channel so one
    # speaker's level can't drag the other's.
    _ffmpeg(
        [
            "-i", path,
            "-filter_complex",
            "channelsplit=channel_layout=stereo[l][r];"
            "[l]loudnorm=I=-16:TP=-1.5:LRA=11[L];"
            "[r]loudnorm=I=-16:TP=-1.5:LRA=11[R]",
            "-map", "[L]", "-c:a", "flac", left_out,
            "-map", "[R]", "-c:a", "flac", right_out,
        ]
    )


def to_mono_flac(path: str, out: str) -> None:
    _ffmpeg(["-i", path, "-ac", "1", "-c:a", "flac", out])
