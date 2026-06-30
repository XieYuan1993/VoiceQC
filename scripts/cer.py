"""Character Error Rate (CER) for the ASR — the standard accuracy metric for
Chinese speech recognition (WER doesn't apply: written Chinese has no spaces,
so there are no "words" to align). CER = (S + D + I) / N over characters.

Provide a human reference transcript and compare against either a transcript
already in the DB (by recording id) or a hypothesis text file.

Usage (repo root):
  # against a stored transcript (segments are concatenated, role/timestamps stripped):
  uv run python scripts/cer.py --ref ref.txt --recording <RECORDING_ID>
  # against a raw hypothesis file:
  uv run python scripts/cer.py --ref ref.txt --hyp asr_out.txt
  # restrict to one channel of the stored transcript:
  uv run python scripts/cer.py --ref ref.txt --recording <ID> --channel broker

Normalization (applied to both sides): NFKC fold, drop all whitespace and
punctuation (ASCII + CJK), lowercase Latin — so scoring reflects spoken
content, not formatting. Reports CER plus the substitution/deletion/insertion
breakdown so you can see whether errors are mishears vs missed/extra speech.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata

REPO = "/Users/yilun/Documents/Call QA"
sys.path.insert(0, f"{REPO}/shared")
sys.path.insert(0, f"{REPO}/apps/worker")


def normalize(text: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFKC", text):
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N"):  # letters + numbers only
            out.append(ch.lower())
    return "".join(out)


def edit_counts(ref: str, hyp: str) -> tuple[int, int, int]:
    """Levenshtein DP with op backtrace -> (subs, dels, ins)."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1])
    # Backtrace
    i, j, s, d, ins = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            s += 1; i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            d += 1; i -= 1
        else:
            ins += 1; j -= 1
    return s, d, ins


def hypothesis_from_db(recording_id: str, channel: str | None) -> str:
    from sqlalchemy import select
    from voiceqa_shared.db_models import Transcript, TranscriptSegment
    from worker.db import SessionLocal

    with SessionLocal() as session:
        import uuid

        t = session.execute(
            select(Transcript).where(Transcript.recording_id == uuid.UUID(recording_id))
        ).scalar_one_or_none()
        if t is None:
            raise SystemExit("no transcript for that recording id")
        stmt = select(TranscriptSegment).where(TranscriptSegment.transcript_id == t.id)
        if channel:
            stmt = stmt.where(TranscriptSegment.channel_role == channel)
        segs = session.execute(stmt.order_by(TranscriptSegment.start_ms)).scalars().all()
        return " ".join(s.text for s in segs)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ref", required=True, help="human reference transcript file")
    p.add_argument("--recording", help="recording id — pull the stored transcript")
    p.add_argument("--hyp", help="hypothesis text file (instead of --recording)")
    p.add_argument("--channel", choices=["broker", "customer", "mixed"], help="restrict DB transcript")
    args = p.parse_args()

    ref_raw = open(args.ref, encoding="utf-8").read()
    if args.recording:
        from dotenv import load_dotenv

        load_dotenv(f"{REPO}/.env")
        hyp_raw = hypothesis_from_db(args.recording, args.channel)
    elif args.hyp:
        hyp_raw = open(args.hyp, encoding="utf-8").read()
    else:
        raise SystemExit("provide --recording or --hyp")

    ref, hyp = normalize(ref_raw), normalize(hyp_raw)
    if not ref:
        raise SystemExit("reference is empty after normalization")
    s, d, i = edit_counts(ref, hyp)
    cer = (s + d + i) / len(ref)
    print(f"reference chars (N): {len(ref)}")
    print(f"hypothesis chars   : {len(hyp)}")
    print(f"substitutions (S)  : {s}")
    print(f"deletions (D)      : {d}  (reference chars the ASR missed)")
    print(f"insertions (I)     : {i}  (chars the ASR added)")
    print(f"\nCER = (S+D+I)/N = ({s}+{d}+{i})/{len(ref)} = {cer:.1%}")
    print(f"character accuracy ≈ {max(0, 1 - cer):.1%}")


if __name__ == "__main__":
    main()
