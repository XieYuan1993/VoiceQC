"""Repair recording broker names from uniquely configured PBX extensions.

Dry-run by default. This never touches recordings whose extension is missing,
unmapped, or assigned to more than one broker.

Usage:
  uv run python scripts/backfill_broker_names_from_extensions.py
  uv run python scripts/backfill_broker_names_from_extensions.py --apply
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "worker"))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import select  # noqa: E402
from voiceqa_shared.db_models import Broker, Recording  # noqa: E402
from worker.db import SessionLocal  # noqa: E402


def main(apply: bool) -> int:
    with SessionLocal() as session:
        brokers = session.execute(select(Broker).where(Broker.active.is_(True))).scalars().all()
        by_extension: dict[str, list[Broker]] = defaultdict(list)
        for broker in brokers:
            for extension in broker.phone_extensions or []:
                by_extension[str(extension).strip()].append(broker)

        recordings = (
            session.execute(select(Recording).where(Recording.broker_ext.is_not(None)))
            .scalars()
            .all()
        )
        changed: list[tuple[Recording, Broker]] = []
        unmapped = 0
        ambiguous = 0
        already_correct = 0
        for recording in recordings:
            matches = by_extension.get(str(recording.broker_ext).strip(), [])
            if not matches:
                unmapped += 1
                continue
            if len(matches) != 1:
                ambiguous += 1
                continue
            broker = matches[0]
            if recording.broker_name == broker.name:
                already_correct += 1
                continue
            changed.append((recording, broker))

        print(
            f"recordings_with_extension={len(recordings)} "
            f"already_correct={already_correct} changes={len(changed)} "
            f"unmapped={unmapped} ambiguous={ambiguous}"
        )
        for recording, broker in changed[:25]:
            print(
                f"{recording.id} {recording.original_filename}: "
                f"{recording.broker_name!r} -> {broker.name!r} "
                f"(extension {recording.broker_ext})"
            )
        if len(changed) > 25:
            print(f"... and {len(changed) - 25} more")

        if not apply:
            print("dry-run only; pass --apply to commit these changes")
            session.rollback()
            return 0

        for recording, broker in changed:
            recording.broker_name = broker.name
        session.commit()
        print(f"applied={len(changed)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Commit safe extension mappings")
    raise SystemExit(main(parser.parse_args().apply))
