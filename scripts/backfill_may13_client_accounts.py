"""Correct audited client-account extraction errors for 2026-05-13.

Dry-run by default. Each correction is keyed by recording filename and only
applies when the current value is the audited bad value.

Usage from repo root:
  uv run python scripts/backfill_may13_client_accounts.py
  uv run python scripts/backfill_may13_client_accounts.py --apply
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "worker"))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import func, select  # noqa: E402
from voiceqa_shared.db_models import Evaluation, Recording, TradeInstruction  # noqa: E402
from worker.db import SessionLocal  # noqa: E402


@dataclass(frozen=True)
class Correction:
    old: str
    new: str | None


CORRECTIONS = {
    "20260513_091411.wav": Correction("67091", "067091"),
    "20260513_093155.wav": Correction("574574", None),
    "20260513_093958.wav": Correction("193938", "203199"),
    "20260513_094332.wav": Correction("140140", None),
    "20260513_095043.wav": Correction("215914", "039984"),
    "20260513_102634.wav": Correction("91596", None),
    "20260513_102303.wav": Correction("215914", "039984"),
    "20260513_103415.wav": Correction("1219", "001219"),
    "20260513_104054.wav": Correction("67091", "067091"),
    "20260513_104203.wav": Correction("484485", None),
    "20260513_104508.wav": Correction("344345", None),
    "20260513_104916.wav": Correction("1219", "001219"),
    "20260513_111832.wav": Correction("616017", "214353"),
    "20260513_112954.wav": Correction("102103", "600120"),
    "20260513_114826.wav": Correction("616017", "214353"),
    "20260513_131648.wav": Correction("116117", "039984"),
    "20260513_132433.wav": Correction("132528", None),
    "20260513_132633.wav": Correction("616017", "214353"),
    "20260513_134521.wav": Correction("1219", "001219"),
    "20260513_134422.wav": Correction("616017", "214353"),
    "20260513_135310.wav": Correction("514515", None),
    "20260513_143611.wav": Correction("776775", None),
    "20260513_143636.wav": Correction("616017", "214353"),
    "20260513_150521.wav": Correction("616017", "214353"),
    "20260513_152604.wav": Correction("2026002", "202677"),
    "20260513_155024.wav": Correction("20261002", "202611"),
    "20260513_155938.wav": Correction("3703", "003703"),
    "20260513_113939.wav": Correction("twenty six forty eight", "002648"),
}


def _canonical(value: str | None) -> str | None:
    text = (value or "").strip()
    digits = "".join(char for char in text if char.isdigit())
    return digits or text.casefold() or None


def main(apply: bool) -> int:
    with SessionLocal() as session:
        recordings = session.execute(
            select(Recording).where(Recording.original_filename.in_(CORRECTIONS))
        ).scalars().all()
        if not recordings:
            print("No audited recordings found.")
            return 0

        latest_runs = (
            select(Evaluation.recording_id, func.max(Evaluation.run_seq).label("run_seq"))
            .where(
                Evaluation.recording_id.in_([recording.id for recording in recordings]),
                Evaluation.status == "completed",
            )
            .group_by(Evaluation.recording_id)
            .subquery()
        )
        latest_ids = session.execute(
            select(Evaluation.id).join(
                latest_runs,
                (Evaluation.recording_id == latest_runs.c.recording_id)
                & (Evaluation.run_seq == latest_runs.c.run_seq),
            )
        ).scalars().all()
        instructions = session.execute(
            select(TradeInstruction).where(TradeInstruction.evaluation_id.in_(latest_ids))
        ).scalars().all()
        instructions_by_recording: dict[object, list[TradeInstruction]] = {}
        for instruction in instructions:
            instructions_by_recording.setdefault(instruction.recording_id, []).append(instruction)

        recording_updates = 0
        instruction_updates = 0
        skipped_changed = 0
        for recording in sorted(recordings, key=lambda item: (item.original_filename, str(item.id))):
            correction = CORRECTIONS[recording.original_filename]
            current_values = {
                _canonical(recording.client_account),
                *(
                    _canonical(instruction.client_account_raw)
                    for instruction in instructions_by_recording.get(recording.id, [])
                ),
            }
            current_values.discard(None)
            already_correct = (
                not current_values if correction.new is None else current_values == {correction.new}
            )
            if already_correct:
                print(
                    f"OK {recording.id} {recording.original_filename}: "
                    f"already {correction.new!r}"
                )
                continue
            if current_values and current_values != {correction.old}:
                skipped_changed += 1
                print(
                    f"SKIP {recording.id} {recording.original_filename}: "
                    f"expected {correction.old}, found {sorted(current_values)}"
                )
                continue

            old_display = sorted(current_values) or [None]
            print(
                f"UPDATE {recording.id} {recording.original_filename}: "
                f"{old_display} -> {correction.new!r}"
            )
            if _canonical(recording.client_account) != correction.new:
                recording.client_account = correction.new
                recording_updates += 1
            for instruction in instructions_by_recording.get(recording.id, []):
                if _canonical(instruction.client_account_raw) == correction.old:
                    instruction.client_account_raw = correction.new
                    instruction_updates += 1

        print(
            f"recordings_found={len(recordings)} recording_updates={recording_updates} "
            f"instruction_updates={instruction_updates} skipped_changed={skipped_changed}"
        )
        if apply:
            session.commit()
            print("Applied updates.")
        else:
            session.rollback()
            print("Dry run only; rerun with --apply to write changes.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    raise SystemExit(main(parser.parse_args().apply))
