"""Build a provisional, role-normalized FWD ASR reference set."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import zipfile
from pathlib import Path

from openpyxl import load_workbook

FORMAL_SCENE_RE = re.compile(r"^(?:S(?:0[1-9]|1[0-7])|B[12])$")
TIMED_TRANSCRIPT_SUFFIX = "2_asr_transcript_with_time_speaker.txt"
SPEAKER_LINE_RE = re.compile(r"^Speaker\s+([12])\|(.*)$")


def _fixed_name(name: str) -> str:
    try:
        return name.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _text(value: object) -> str:
    return str(value or "").strip()


def _scene_rows(workbook_path: Path) -> list[dict[str, str]]:
    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    hotwords = {
        _text(row[1]): _text(row[6])
        for row in workbook["热词修复演示集"].iter_rows(min_row=2, values_only=True)
        if _text(row[1]) and _text(row[6])
    }
    scenes = []
    for row in workbook["场景清单"].iter_rows(min_row=2, values_only=True):
        scene_id = _text(row[0])
        if not FORMAL_SCENE_RE.fullmatch(scene_id):
            continue
        call_id = _text(row[10])[:8]
        speaker_1 = _text(row[9])
        scenes.append(
            {
                "scene_id": scene_id,
                "title": _text(row[1]),
                "language": _text(row[4]),
                "duration": _text(row[5]),
                "call_id": call_id,
                "speaker_1": speaker_1,
                "known_brand_error": hotwords.get(call_id, ""),
            }
        )
    return scenes


def _transcript_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members = {}
    for info in archive.infolist():
        name = _fixed_name(info.filename)
        if not name.endswith(TIMED_TRANSCRIPT_SUFFIX):
            continue
        match = re.search(r"_([0-9a-f]{8})(?:/|\\)", name, re.IGNORECASE)
        if match:
            members[match.group(1).lower()] = info
    return members


def _normalize_roles(text: str, *, speaker_1_is_agent: bool) -> str:
    lines = []
    for raw_line in text.splitlines():
        match = SPEAKER_LINE_RE.match(raw_line.strip())
        if not match:
            if raw_line.strip():
                lines.append(raw_line.strip())
            continue
        speaker = int(match.group(1))
        is_agent = (speaker == 1) == speaker_1_is_agent
        role = "agent" if is_agent else "customer"
        lines.append(f"{role}|{match.group(2)}")
    return "\n".join(lines) + "\n"


def build(source_zip: Path, workbook_path: Path, output_dir: Path) -> Path:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir = output_dir / "transcripts"
    transcripts_dir.mkdir()

    manifest = []
    with zipfile.ZipFile(source_zip) as archive:
        members = _transcript_members(archive)
        for scene in _scene_rows(workbook_path):
            call_id = scene["call_id"].lower()
            info = members.get(call_id)
            if info is None:
                raise ValueError(f"timed transcript not found for {scene['scene_id']} ({call_id})")
            source_text = archive.read(info).decode("utf-8-sig", errors="replace")
            corrected_text = source_text
            corrections = []
            wrong_brand = scene["known_brand_error"]
            if wrong_brand:
                occurrences = corrected_text.count(wrong_brand)
                if occurrences:
                    corrected_text = corrected_text.replace(wrong_brand, "富衛")
                    corrections.append(
                        {
                            "from": wrong_brand,
                            "to": "富衛",
                            "occurrences": occurrences,
                            "basis": "workbook hotword repair list",
                        }
                    )
                else:
                    corrections.append(
                        {
                            "from": wrong_brand,
                            "to": "富衛",
                            "occurrences": 0,
                            "basis": "workbook entry not found verbatim; audio review required",
                        }
                    )

            speaker_1_is_agent = not scene["speaker_1"].startswith("来电者")
            reference_text = _normalize_roles(
                corrected_text,
                speaker_1_is_agent=speaker_1_is_agent,
            )
            filename = f"{scene['scene_id']}_{call_id}_reference.txt"
            (transcripts_dir / filename).write_text(reference_text, encoding="utf-8")
            manifest.append(
                {
                    **scene,
                    "reference_file": f"transcripts/{filename}",
                    "agent_source_speaker": "Speaker 1" if speaker_1_is_agent else "Speaker 2",
                    "corrections": corrections,
                    "status": (
                        "provisional_brand_corrected_needs_audio_review"
                        if corrections
                        else "provisional_from_supplied_timed_script"
                    ),
                }
            )

    manifest.sort(key=lambda item: item["scene_id"])
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "scene_id",
                "call_id",
                "title",
                "language",
                "duration",
                "agent_source_speaker",
                "known_brand_error",
                "status",
                "reference_file",
            ),
        )
        writer.writeheader()
        for item in manifest:
            writer.writerow({key: item[key] for key in writer.fieldnames})

    readme = """# FWD ASR calibration reference v0.1

This set contains the 19 formal demo calls (S01-S17 and B1-B2).

- Speaker labels are normalized to `agent` and `customer` from the workbook's role mapping.
- Known brand-token errors listed in the workbook are normalized to `富衛`.
- The supplied timestamped transcripts are ASR-derived, not independently human-verified.
- Rows marked `needs_audio_review` require listening before this set can be called a gold standard.
- The seven H-series hotword-only calls are intentionally excluded from this formal calibration set.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    zip_path = Path(f"{output_dir}.zip")
    if zip_path.exists():
        raise ValueError(f"output archive already exists: {zip_path}")
    shutil.make_archive(str(output_dir), "zip", root_dir=output_dir)
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    archive = build(args.source_zip, args.workbook, args.output_dir)
    print(f"FWD reference set ready: {archive}")


if __name__ == "__main__":
    main()
