"""STT configuration spike — compare language modes ± term adaptation.

Settles the open Phase-1 questions on REAL recordings (DESIGN.md §4):
which language mode handles HK code-switching best, and whether adaptation
phrases compose with language-agnostic auto mode in batch.

Usage (repo root):
    uv run python scripts/spike_stt.py path/to/call1.wav path/to/call2.wav
    uv run python scripts/spike_stt.py --configs auto,auto+terms,yue+terms file.wav

Each config runs a real BatchRecognize (costs ~$0.02/min/config). Stereo
files are split into broker/customer channels first, mirroring the pipeline.
Results print side by side for human judgement; nothing is written to the DB.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "worker"))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from voiceqa_shared import gcs  # noqa: E402
from worker import audio  # noqa: E402
from worker.asr.base import AdaptationPhrase, ChannelFile  # noqa: E402
from worker.asr.google_batch import GoogleBatchASR  # noqa: E402

CONFIGS = {
    "auto": {"language_mode": "auto", "adaptation": False},
    "auto+terms": {"language_mode": "auto", "adaptation": True},
    "yue": {"language_mode": "yue-Hant-HK", "adaptation": False},
    "yue+terms": {"language_mode": "yue-Hant-HK", "adaptation": True},
}


def load_phrases() -> list[AdaptationPhrase]:
    """Adaptation phrases from the terms CSV (no DB dependency)."""
    import csv

    path = REPO_ROOT / "mocks" / "data" / "industry_terms.csv"
    phrases: list[AdaptationPhrase] = []
    if not path.exists():
        return phrases
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for value in [row["canonical"], *row["aliases"].split("|")]:
                value = value.strip()
                if value:
                    phrases.append(AdaptationPhrase(value=value))
    return phrases


def prepare_channels(local: Path, spike_id: str) -> list[ChannelFile]:
    info = audio.probe(str(local))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        if info.channels >= 2:
            left, right = tmp / "broker.flac", tmp / "customer.flac"
            audio.split_stereo_to_flac(str(local), str(left), str(right))
            return [
                ChannelFile(
                    uri=gcs.upload_file(f"spike/{spike_id}/{local.stem}/broker.flac", str(left)),
                    channel_role="broker",
                ),
                ChannelFile(
                    uri=gcs.upload_file(f"spike/{spike_id}/{local.stem}/customer.flac", str(right)),
                    channel_role="customer",
                ),
            ]
        mono = tmp / "mono.flac"
        audio.to_mono_flac(str(local), str(mono))
        return [
            ChannelFile(
                uri=gcs.upload_file(f"spike/{spike_id}/{local.stem}/mono.flac", str(mono)),
                channel_role="mixed",
            )
        ]


def run_config(
    asr: GoogleBatchASR,
    name: str,
    cfg: dict,
    channels: list[ChannelFile],
    phrases: list[AdaptationPhrase],
) -> None:
    print(f"\n=== config: {name} (language={cfg['language_mode']}, "
          f"adaptation={'on' if cfg['adaptation'] else 'off'}) ===")
    op = asr.start_batch(
        channels,
        language_mode=cfg["language_mode"],
        adaptation_phrases=phrases if cfg["adaptation"] else [],
        model="chirp_2",
    )
    started = time.monotonic()
    while True:
        results = asr.fetch_result(op)
        if results is not None:
            break
        time.sleep(10)
        print(f"  ... waiting ({time.monotonic() - started:.0f}s)", flush=True)

    role_by_uri = {c.uri: c.channel_role for c in channels}
    for r in results:
        role = role_by_uri.get(r.uri, "?")
        if r.error:
            print(f"  [{role}] ERROR: {r.error}")
            continue
        print(f"  [{role}] language={r.language_detected} billed={r.billed_seconds:.0f}s")
        for seg in r.segments:
            mm, ss = divmod(seg.start_ms // 1000, 60)
            print(f"    {mm:02d}:{ss:02d} {seg.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--configs",
        default="auto,auto+terms,yue+terms",
        help=f"comma list from {sorted(CONFIGS)}",
    )
    args = parser.parse_args()

    selected = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in selected if c not in CONFIGS]
    if unknown:
        raise SystemExit(f"unknown configs {unknown}; choose from {sorted(CONFIGS)}")

    asr = GoogleBatchASR()
    phrases = load_phrases()
    spike_id = uuid.uuid4().hex[:8]
    print(f"spike {spike_id}: {len(phrases)} adaptation phrases loaded")

    for path in args.files:
        if not path.exists():
            raise SystemExit(f"no such file: {path}")
        print(f"\n########## {path.name} ##########")
        channels = prepare_channels(path, spike_id)
        for name in selected:
            run_config(asr, name, CONFIGS[name], channels, phrases)

    print(f"\ndone. GCS artifacts under spike/{spike_id}/ (clean up when finished).")


if __name__ == "__main__":
    main()
