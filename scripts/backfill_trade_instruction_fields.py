"""Repair canonical trade fields in the latest completed evaluations.

The command is dry-run by default. It only recovers a stock when exactly one
booked security in the call's candidate window is explicitly present in the
instruction evidence.

Usage from repo root:
  uv run python scripts/backfill_trade_instruction_fields.py \
    --date-from 2026-05-11 --date-to 2026-05-15
  uv run python scripts/backfill_trade_instruction_fields.py \
    --date-from 2026-05-11 --date-to 2026-05-15 --apply
"""

from __future__ import annotations

import argparse
import sys
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "worker"))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import func, select  # noqa: E402
from voiceqa_shared.db_models import (  # noqa: E402
    Evaluation,
    Recording,
    TradeInstruction,
    Transaction,
)
from worker.db import SessionLocal  # noqa: E402
from worker.trade_normalization import (  # noqa: E402
    MAX_SECURITY_CANDIDATES,
    infer_price_type,
    recover_stock_code,
)

HK = ZoneInfo("Asia/Hong_Kong")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _args()
    if args.date_to < args.date_from:
        raise SystemExit("--date-to must be on or after --date-from")

    with SessionLocal() as session:
        recordings = session.execute(
            select(Recording).where(Recording.status == "completed")
        ).scalars().all()
        recordings = [
            rec
            for rec in recordings
            if rec.call_started_at is not None
            and args.date_from <= rec.call_started_at.astimezone(HK).date() <= args.date_to
        ]
        if not recordings:
            print("No completed recordings found in the requested date range.")
            return 0

        latest_runs = (
            select(Evaluation.recording_id, func.max(Evaluation.run_seq).label("run_seq"))
            .where(
                Evaluation.recording_id.in_([rec.id for rec in recordings]),
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
        transactions = session.execute(
            select(Transaction).where(
                Transaction.trade_date >= args.date_from,
                Transaction.trade_date <= args.date_to,
            )
        ).scalars().all()

        rec_by_id = {rec.id: rec for rec in recordings}
        candidate_rows = sorted(
            (
                (anchor, txn.stock_code, txn.stock_name)
                for txn in transactions
                if txn.stock_code and (anchor := txn.ordered_at or txn.executed_at) is not None
            ),
            key=lambda row: row[0],
        )
        candidate_times = [row[0] for row in candidate_rows]
        candidates_by_recording: dict[object, list[tuple[str, str | None]]] = {}
        for rec in recordings:
            low = rec.call_started_at - timedelta(minutes=15)
            high = rec.call_started_at + timedelta(hours=6)
            left = bisect_left(candidate_times, low)
            right = bisect_right(candidate_times, high)
            counts = Counter((code, name) for _at, code, name in candidate_rows[left:right])
            candidates_by_recording[rec.id] = [
                security
                for security, _count in counts.most_common(MAX_SECURITY_CANDIDATES)
            ]

        stock_updates = 0
        price_type_updates = 0
        previews: list[str] = []
        for instruction in instructions:
            rec = rec_by_id.get(instruction.recording_id)
            if rec is None:
                continue
            changed: list[str] = []
            if instruction.stock_code is None:
                recovered = recover_stock_code(
                    instruction.evidence_quote,
                    candidates_by_recording[rec.id],
                    quantity=instruction.quantity,
                    price=instruction.price,
                )
                if recovered is not None:
                    instruction.stock_code = recovered
                    stock_updates += 1
                    changed.append(f"stock={recovered}")
            price_type = infer_price_type(instruction.price_type, instruction.evidence_quote)
            if price_type != instruction.price_type:
                instruction.price_type = price_type
                price_type_updates += 1
                changed.append(f"price_type={price_type}")
            if changed and len(previews) < 25:
                previews.append(
                    f"{rec.original_filename} instruction#{instruction.seq}: "
                    + ", ".join(changed)
                    + f" | evidence={instruction.evidence_quote!r}"
                )

        print(f"recordings scanned: {len(recordings)}")
        print(f"instructions scanned: {len(instructions)}")
        print(f"stock codes recoverable: {stock_updates}")
        print(f"price types recoverable: {price_type_updates}")
        for preview in previews:
            print(preview)
        if args.apply:
            session.commit()
            print("Applied updates.")
        else:
            session.rollback()
            print("Dry run only; rerun with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
