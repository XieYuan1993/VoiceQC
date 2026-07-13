"""Backfill recording broker names from telephony TXT metadata.

This is a metadata-only repair tool. It reads TXT files from local ZIPs, local
TXT directories, or ZIP/TXT objects still present in GCS, matches them to
existing recordings in one batch, and updates recording metadata. It does not
rerun STT or LLM evaluation.

Usage from repo root:
  uv run python scripts/backfill_recording_broker_names.py --batch-id <uuid> --zip calls.zip
  uv run python scripts/backfill_recording_broker_names.py --batch-id <uuid> --from-gcs
  uv run python scripts/backfill_recording_broker_names.py --batch-id <uuid> --zip calls.zip --apply
"""

from __future__ import annotations

import argparse
import sys
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "worker"))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import select  # noqa: E402
from voiceqa_shared import gcs  # noqa: E402
from voiceqa_shared.db_models import Recording  # noqa: E402
from worker.db import SessionLocal  # noqa: E402
from worker.tasks.ingest import (  # noqa: E402
    TEXT_EXTS,
    _apply_txt_metadata,
    _decode_text,
    _load_zip_text_metadata,
    _match_metadata_for_audio,
    _parse_call_export_text,
)

Metadata = dict[str, str | object | None]


@dataclass
class UpdatePreview:
    recording_id: str
    filename: str
    broker_ext: str | None
    broker_name: str | None
    caller_number: str | None
    call_started_at: str | None
    direction: str
    source: str


def _metadata_has_value(meta: Metadata) -> bool:
    return any(meta.get(k) for k in ("broker_name", "broker_ext", "caller_number", "started_at"))


def _merge_metadata(target: dict[str, Metadata], source: str, metadata: dict[str, Metadata]) -> None:
    for name, meta in metadata.items():
        if _metadata_has_value(meta):
            target[f"{source}:{name}"] = meta


def _load_local_zip(path: Path) -> dict[str, Metadata]:
    with zipfile.ZipFile(path) as zf:
        return _load_zip_text_metadata(zf)


def _load_local_txt_dir(path: Path) -> dict[str, Metadata]:
    out: dict[str, Metadata] = {}
    for file in path.rglob("*"):
        if file.is_file() and file.suffix.lower() in TEXT_EXTS:
            out[str(file.relative_to(path))] = _parse_call_export_text(_decode_text(file.read_bytes()))
    return out


def _load_gcs_metadata(batch_id: str, extra_prefixes: Iterable[str]) -> dict[str, Metadata]:
    out: dict[str, Metadata] = {}
    prefixes = [f"raw/{batch_id}/_zips/", *extra_prefixes]
    for prefix in prefixes:
        for key in gcs.list_keys(prefix):
            suffix = Path(key).suffix.lower()
            if suffix == ".zip":
                with zipfile.ZipFile(BytesIO(gcs.read_uri_bytes(gcs.to_uri(key)))) as zf:
                    _merge_metadata(out, key, _load_zip_text_metadata(zf))
            elif suffix in TEXT_EXTS:
                meta = _parse_call_export_text(_decode_text(gcs.read_uri_bytes(gcs.to_uri(key))))
                if _metadata_has_value(meta):
                    out[key] = meta
    return out


def _load_all_metadata(args: argparse.Namespace) -> dict[str, Metadata]:
    metadata: dict[str, Metadata] = {}
    for path_raw in args.zip or []:
        path = Path(path_raw)
        _merge_metadata(metadata, str(path), _load_local_zip(path))
    for path_raw in args.txt_dir or []:
        path = Path(path_raw)
        _merge_metadata(metadata, str(path), _load_local_txt_dir(path))
    if args.from_gcs:
        _merge_metadata(metadata, "gcs", _load_gcs_metadata(args.batch_id, args.gcs_prefix or []))
    return metadata


def _changed_fields(before: dict[str, Any], rec: Recording) -> list[str]:
    after = {
        "broker_ext": rec.broker_ext,
        "broker_name": rec.broker_name,
        "caller_number": rec.caller_number,
        "direction": rec.direction,
        "call_started_at": rec.call_started_at,
    }
    return [key for key, value in after.items() if before[key] != value]


def _preview(rec: Recording, source: str) -> UpdatePreview:
    return UpdatePreview(
        recording_id=str(rec.id),
        filename=rec.original_filename,
        broker_ext=rec.broker_ext,
        broker_name=rec.broker_name,
        caller_number=rec.caller_number,
        call_started_at=rec.call_started_at.isoformat() if rec.call_started_at else None,
        direction=rec.direction,
        source=source,
    )


def run(args: argparse.Namespace) -> int:
    metadata = _load_all_metadata(args)
    if not metadata:
        print("No TXT metadata found.")
        return 2

    matched = 0
    changed = 0
    unchanged = 0
    missing = 0
    previews: list[tuple[UpdatePreview, list[str]]] = []

    with SessionLocal() as session:
        recordings = (
            session.execute(
                select(Recording)
                .where(Recording.batch_id == uuid.UUID(args.batch_id))
                .order_by(Recording.original_filename)
            )
            .scalars()
            .all()
        )
        if not recordings:
            print(f"No recordings found for batch {args.batch_id}.")
            return 2

        for rec in recordings:
            match_key = None
            meta = _match_metadata_for_audio(rec.original_filename, metadata)
            if meta is None:
                missing += 1
                continue
            for key, candidate in metadata.items():
                if candidate is meta:
                    match_key = key
                    break
            matched += 1
            if args.only_missing_broker_name and rec.broker_name:
                unchanged += 1
                continue
            before = {
                "broker_ext": rec.broker_ext,
                "broker_name": rec.broker_name,
                "caller_number": rec.caller_number,
                "direction": rec.direction,
                "call_started_at": rec.call_started_at,
            }
            _apply_txt_metadata(rec, meta)
            fields = _changed_fields(before, rec)
            if fields:
                changed += 1
                previews.append((_preview(rec, match_key or "metadata"), fields))
            else:
                unchanged += 1

        print(
            f"metadata={len(metadata)} recordings={len(recordings)} matched={matched} "
            f"changed={changed} unchanged={unchanged} missing={missing}"
        )
        for preview, fields in previews[: args.limit]:
            print(
                f"- {preview.filename} ({preview.recording_id}) fields={','.join(fields)} "
                f"broker_name={preview.broker_name!r} broker_ext={preview.broker_ext!r} "
                f"caller={preview.caller_number!r} start={preview.call_started_at} "
                f"source={preview.source}"
            )
        if len(previews) > args.limit:
            print(f"... {len(previews) - args.limit} more changed recordings not shown")

        if args.apply:
            session.commit()
            print("Applied changes.")
        else:
            session.rollback()
            print("Dry run only. Re-run with --apply to write changes.")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True, help="Upload batch UUID to update.")
    parser.add_argument(
        "--zip",
        action="append",
        help="Local ZIP file containing audio and TXT metadata. Can be provided multiple times.",
    )
    parser.add_argument(
        "--txt-dir",
        action="append",
        help="Local directory containing TXT metadata files. Can be provided multiple times.",
    )
    parser.add_argument(
        "--from-gcs",
        action="store_true",
        help="Read ZIP/TXT objects from raw/<batch_id>/_zips/ and optional --gcs-prefix values.",
    )
    parser.add_argument(
        "--gcs-prefix",
        action="append",
        help="Extra GCS object prefix to scan for ZIP/TXT metadata.",
    )
    parser.add_argument(
        "--only-missing-broker-name",
        action="store_true",
        default=True,
        help="Only update recordings whose broker_name is currently empty. Default: true.",
    )
    parser.add_argument(
        "--include-existing-broker-name",
        dest="only_missing_broker_name",
        action="store_false",
        help="Allow overwriting existing broker_name when TXT metadata differs.",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes to the database.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum changed rows to print.")
    args = parser.parse_args()
    if not (args.zip or args.txt_dir or args.from_gcs):
        parser.error("provide at least one of --zip, --txt-dir, or --from-gcs")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
