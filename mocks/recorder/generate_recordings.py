# /// script
# requires-python = ">=3.11"
# ///
"""Generate synthetic stereo call recordings from the golden-day fixture.

Stands in for Quam's telephony recorder output until real samples arrive:
  - one WAV per call, 16 kHz 16-bit stereo, LEFT = broker, RIGHT = customer
  - filenames follow the assumed recorder convention
    {extension}_{YYYYMMDD}_{HHMMSS}_{direction}_{caller}.wav
  - manifest.json carries per-file ground truth (client, expected trade
    instructions, expected recon bucket) for golden-fixture tests

Speech is synthesized locally with macOS `say` (Cantonese: Sinji, Mandarin:
Tingting) and assembled with ffmpeg. Suitable for exercising the pipeline
mechanics end-to-end; NOT a substitute for real recordings when judging ASR
accuracy.

Usage:
  uv run mocks/recorder/generate_recordings.py                 # fixture date
  uv run mocks/recorder/generate_recordings.py --date 2026-06-12 --zip
  uv run mocks/recorder/generate_recordings.py --only R1,R7    # quick subset
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import wave
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / "data" / "golden_day.json"

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # 16-bit PCM
LEAD_IN_S = 0.6
TURN_GAP_S = 0.5
RATE_BROKER = 185
RATE_CUSTOMER = 168

# Preference order per language; falls back down the list if not installed.
VOICE_PREFS = {
    "yue": ["Sinji", "Tingting", "Meijia", "Samantha"],
    "cmn": ["Tingting", "Meijia", "Sinji", "Samantha"],
}


def pick_voices() -> dict[str, str]:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout
    installed = {line.split()[0] for line in out.splitlines() if line.strip()}
    voices = {}
    for lang, prefs in VOICE_PREFS.items():
        chosen = next((v for v in prefs if v in installed), None)
        if chosen is None:
            sys.exit(f"no usable voice for {lang}; install a Chinese voice in System Settings > Spoken Content")
        if chosen != prefs[0]:
            print(f"warning: preferred voice {prefs[0]!r} for {lang} not installed, using {chosen!r}")
        voices[lang] = chosen
    return voices


def synth_turn(text: str, voice: str, rate: int, tmp: Path, idx: int) -> bytes:
    """Synthesize one utterance, return raw 16 kHz mono s16le PCM frames."""
    aiff = tmp / f"turn_{idx}.aiff"
    wav = tmp / f"turn_{idx}.wav"
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
         "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
        check=True,
    )
    with wave.open(str(wav), "rb") as w:
        return w.readframes(w.getnframes())


def write_mono(path: Path, frames: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames)


def build_recording(rec: dict, voices: dict[str, str], out_path: Path) -> float:
    """Render one call to a stereo WAV (L=broker, R=customer). Returns duration in seconds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Lay turns on a shared timeline, each on its speaker's channel.
        clips = []  # (channel, start_frame, pcm)
        cursor = int(LEAD_IN_S * SAMPLE_RATE)
        for i, turn in enumerate(rec["turns"]):
            is_broker = turn["speaker"] == "broker"
            pcm = synth_turn(
                turn["text"], voices[turn["voice"]],
                RATE_BROKER if is_broker else RATE_CUSTOMER, tmp, i,
            )
            clips.append(("L" if is_broker else "R", cursor, pcm))
            cursor += len(pcm) // SAMPLE_WIDTH + int(TURN_GAP_S * SAMPLE_RATE)

        total_frames = cursor
        channels = {"L": bytearray(total_frames * SAMPLE_WIDTH), "R": bytearray(total_frames * SAMPLE_WIDTH)}
        for channel, start, pcm in clips:
            offset = start * SAMPLE_WIDTH
            channels[channel][offset : offset + len(pcm)] = pcm

        left, right = tmp / "L.wav", tmp / "R.wav"
        write_mono(left, bytes(channels["L"]))
        write_mono(right, bytes(channels["R"]))
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(left), "-i", str(right),
             "-filter_complex", "[0:a][1:a]join=inputs=2:channel_layout=stereo[a]",
             "-map", "[a]", "-c:a", "pcm_s16le", str(out_path)],
            check=True,
        )
        return total_frames / SAMPLE_RATE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="Restamp recordings to this date (YYYY-MM-DD)")
    parser.add_argument("--out", type=Path, default=None, help="Output dir (default recorder/recordings/<date>)")
    parser.add_argument("--only", default=None, help="Comma-separated recording ids, e.g. R1,R7")
    parser.add_argument("--zip", action="store_true", help="Also produce recordings_<date>.zip for batch-upload testing")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    date = args.date or fixture["trade_date"]
    out_dir = args.out or HERE / "recordings" / date
    out_dir.mkdir(parents=True, exist_ok=True)

    voices = pick_voices()
    clients = {c["id"]: c for c in fixture["clients"]}
    ae_by_ext = {b["extension"]: b["ae_code"] for b in fixture["brokers"]}
    wanted = set(args.only.split(",")) if args.only else None

    manifest_recs = []
    for rec in fixture["recordings"]:
        if wanted and rec["id"] not in wanted:
            continue
        hhmmss = rec["start_time"].replace(":", "")
        filename = f"{rec['extension']}_{date.replace('-', '')}_{hhmmss}_{rec['direction']}_{rec['caller']}.wav"
        duration = build_recording(rec, voices, out_dir / filename)
        client = clients.get(rec["client"]) if rec["client"] else None
        manifest_recs.append({
            "recording_id": rec["id"],
            "filename": filename,
            "broker_ext": rec["extension"],
            "ae_code": ae_by_ext[rec["extension"]],
            "direction": rec["direction"],
            "caller": rec["caller"],
            "started_at": f"{date}T{rec['start_time']}+08:00",
            "duration_seconds": round(duration, 2),
            "client": {"name_en": client["name_en"], "name_zh": client["name_zh"], "account": client["account"]} if client else None,
            "expected": rec["expected"],
        })
        print(f"{rec['id']}: {filename} ({duration:.1f}s, {len(rec['turns'])} turns)")

    manifest = {
        "trade_date": date,
        "recorder": fixture["recorder"],
        "voices": voices,
        "recordings": manifest_recs,
        "expected_recon_summary": fixture["expected_recon_summary"],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {manifest_path}")

    if args.zip:
        zip_path = out_dir.parent / f"recordings_{date}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(out_dir.glob("*.wav")):
                zf.write(f, f.name)
        print(f"wrote {zip_path}")


if __name__ == "__main__":
    main()
