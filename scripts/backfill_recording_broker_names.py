"""Backfill recording broker names from telephony TXT metadata.

This is a metadata-only repair tool. It reads TXT files from local ZIPs, local
TXT directories, or ZIP/TXT objects still present in GCS, matches them to
existing recordings in one batch, and updates recording metadata. It does not
rerun STT or LLM evaluation.

Usage from repo root:
  uv run python scripts/backfill_recording_broker_names.py --batch-id <uuid> --zip calls.zip
  uv run python scripts/backfill_recording_broker_names.py --batch-id <uuid> --from-gcs
  uv run python scripts/backfill_recording_broker_names.py --batch-id <uuid> --zip calls.zip --apply
  uv run python scripts/backfill_recording_broker_names.py --bundle-zip AE.zip --only-unmapped-extension
"""

from __future__ import annotations

import argparse
import csv
import re
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

from sqlalchemy import func, select  # noqa: E402
from voiceqa_shared import gcs  # noqa: E402
from voiceqa_shared.db_models import Broker, Recording, UploadBatch  # noqa: E402
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
_TRAILING_BATCH_NUMBER = re.compile(r"[_\-\s]+\d+$")


@dataclass
class BundleZip:
    source: str
    inner_zips: dict[str, bytes]


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


@dataclass
class BatchInput:
    batch_id: str
    zip_paths: list[str]
    txt_dirs: list[str]
    from_gcs: bool
    gcs_prefixes: list[str]
    inline_zips: list[tuple[str, bytes]]


def _metadata_has_value(meta: Metadata) -> bool:
    return any(meta.get(k) for k in ("broker_name", "broker_ext", "caller_number", "started_at"))


def _merge_metadata(
    target: dict[str, Metadata], source: str, metadata: dict[str, Metadata]
) -> None:
    for name, meta in metadata.items():
        if _metadata_has_value(meta):
            target[f"{source}:{name}"] = meta


def _load_local_zip(path: Path) -> dict[str, Metadata]:
    with zipfile.ZipFile(path) as zf:
        return _load_zip_text_metadata(zf)


def _load_zip_bytes(name: str, data: bytes) -> dict[str, Metadata]:
    with zipfile.ZipFile(BytesIO(data)) as zf:
        metadata = _load_zip_text_metadata(zf)
    return {f"{name}:{key}": value for key, value in metadata.items()}


def _load_local_txt_dir(path: Path) -> dict[str, Metadata]:
    out: dict[str, Metadata] = {}
    for file in path.rglob("*"):
        if file.is_file() and file.suffix.lower() in TEXT_EXTS:
            out[str(file.relative_to(path))] = _parse_call_export_text(
                _decode_text(file.read_bytes())
            )
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


def _load_metadata(batch: BatchInput) -> dict[str, Metadata]:
    metadata: dict[str, Metadata] = {}
    for path_raw in batch.zip_paths:
        path = Path(path_raw)
        _merge_metadata(metadata, str(path), _load_local_zip(path))
    for name, data in batch.inline_zips:
        _merge_metadata(metadata, name, _load_zip_bytes(name, data))
    for path_raw in batch.txt_dirs:
        path = Path(path_raw)
        _merge_metadata(metadata, str(path), _load_local_txt_dir(path))
    if batch.from_gcs:
        _merge_metadata(metadata, "gcs", _load_gcs_metadata(batch.batch_id, batch.gcs_prefixes))
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


def list_batches() -> int:
    with SessionLocal() as session:
        rows = session.execute(
            select(
                UploadBatch.id,
                UploadBatch.name,
                UploadBatch.trade_date,
                UploadBatch.status,
                UploadBatch.created_at,
                func.count(Recording.id).label("recordings"),
                func.count(Recording.id)
                .filter(Recording.broker_name.is_(None))
                .label("missing_broker_name"),
            )
            .outerjoin(Recording, Recording.batch_id == UploadBatch.id)
            .group_by(
                UploadBatch.id,
                UploadBatch.name,
                UploadBatch.trade_date,
                UploadBatch.status,
                UploadBatch.created_at,
            )
            .order_by(UploadBatch.created_at.desc())
        ).all()

    print("batch_id,name,trade_date,status,recordings,missing_broker_name,created_at")
    for row in rows:
        print(
            f"{row.id},{row.name or ''},{row.trade_date},{row.status},"
            f"{row.recordings},{row.missing_broker_name},{row.created_at.isoformat()}"
        )
    return 0


def _batch_match_key(name: str | None) -> str:
    stem = Path(name or "").stem.strip()
    return _TRAILING_BATCH_NUMBER.sub("", stem).casefold()


def _load_bundle_zip(path: Path) -> BundleZip:
    inner_zips: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            if Path(member.filename).suffix.lower() != ".zip":
                continue
            key = _batch_match_key(Path(member.filename).name)
            with zf.open(member) as f:
                inner_zips[key] = f.read()
    return BundleZip(source=str(path), inner_zips=inner_zips)


def _load_bundle_zips(paths: Iterable[str]) -> list[BundleZip]:
    return [_load_bundle_zip(Path(path)) for path in paths]


def _batch_inputs_from_bundle_zips(
    bundles: list[BundleZip],
    *,
    include_existing_names: bool = False,
    aliases: dict[str, str] | None = None,
) -> list[BatchInput]:
    rows: list[BatchInput] = []
    with SessionLocal() as session:
        batches = session.execute(
            select(
                UploadBatch.id,
                UploadBatch.name,
                func.count(Recording.id).label("recordings"),
                func.count(Recording.id)
                .filter(Recording.broker_name.is_(None))
                .label("missing_broker_name"),
            )
            .join(Recording, Recording.batch_id == UploadBatch.id)
            .group_by(UploadBatch.id, UploadBatch.name)
            .order_by(UploadBatch.created_at.desc())
        ).all()

    for batch in batches:
        if not include_existing_names and not batch.missing_broker_name:
            continue
        key = _batch_match_key(batch.name)
        bundle_key = (aliases or {}).get(key, key)
        matches = [
            (bundle.source, bundle.inner_zips[bundle_key])
            for bundle in bundles
            if bundle_key in bundle.inner_zips
        ]
        if not matches:
            print(f"[{batch.id}] no inner zip matched batch name {batch.name!r} (key={key!r})")
            continue
        if bundle_key != key:
            print(f"[{batch.id}] bundle alias {key!r} -> {bundle_key!r}")
        if len(matches) > 1:
            print(f"[{batch.id}] multiple inner zips matched {batch.name!r}; using {matches[0][0]}")
        rows.append(
            BatchInput(
                batch_id=str(batch.id),
                zip_paths=[],
                txt_dirs=[],
                from_gcs=False,
                gcs_prefixes=[],
                inline_zips=[(f"{matches[0][0]}:{bundle_key}.zip", matches[0][1])],
            )
        )
    return rows


def run_batch(args: argparse.Namespace, batch: BatchInput) -> int:
    metadata = _load_metadata(batch)
    if not metadata:
        print(f"[{batch.batch_id}] No TXT metadata found.")
        return 2

    matched = 0
    changed = 0
    unchanged = 0
    missing = 0
    previews: list[tuple[UpdatePreview, list[str]]] = []

    with SessionLocal() as session:
        extensions: dict[str, list[str]] = {}
        for broker in session.execute(select(Broker).where(Broker.active.is_(True))).scalars():
            for extension in broker.phone_extensions or []:
                extensions.setdefault(str(extension).strip(), []).append(broker.code)
        recordings = (
            session.execute(
                select(Recording)
                .where(Recording.batch_id == uuid.UUID(batch.batch_id))
                .order_by(Recording.original_filename)
            )
            .scalars()
            .all()
        )
        if not recordings:
            print(f"[{batch.batch_id}] No recordings found.")
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
            current_extension = str(rec.broker_ext).strip() if rec.broker_ext else ""
            has_unique_extension_mapping = len(extensions.get(current_extension, [])) == 1
            if args.only_unmapped_extension and has_unique_extension_mapping:
                unchanged += 1
                continue
            if (
                not args.only_unmapped_extension
                and args.only_missing_broker_name
                and rec.broker_name
            ):
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
            f"[{batch.batch_id}] metadata={len(metadata)} recordings={len(recordings)} matched={matched} "
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


def _read_map_file(path: Path) -> list[BatchInput]:
    rows: dict[str, BatchInput] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"batch_id"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("map file needs at least a batch_id column")
        for row in reader:
            batch_id = (row.get("batch_id") or "").strip()
            if not batch_id:
                continue
            batch = rows.setdefault(
                batch_id,
                BatchInput(
                    batch_id=batch_id,
                    zip_paths=[],
                    txt_dirs=[],
                    from_gcs=False,
                    gcs_prefixes=[],
                    inline_zips=[],
                ),
            )
            zip_path = (row.get("zip_path") or row.get("zip") or "").strip()
            txt_dir = (row.get("txt_dir") or "").strip()
            gcs_prefix = (row.get("gcs_prefix") or "").strip()
            from_gcs = (row.get("from_gcs") or "").strip().casefold()
            if zip_path:
                batch.zip_paths.append(zip_path)
            if txt_dir:
                batch.txt_dirs.append(txt_dir)
            if gcs_prefix:
                batch.gcs_prefixes.append(gcs_prefix)
            if from_gcs in {"1", "true", "yes", "y"}:
                batch.from_gcs = True
    return list(rows.values())


def run(args: argparse.Namespace) -> int:
    if args.list_batches:
        return list_batches()

    if args.bundle_zip:
        bundles = _load_bundle_zips(args.bundle_zip)
        aliases = {}
        for raw_alias in args.bundle_alias or []:
            source, separator, target = raw_alias.partition("=")
            if not separator or not source.strip() or not target.strip():
                raise ValueError("--bundle-alias must be BATCH_NAME=INNER_ZIP_NAME")
            aliases[_batch_match_key(source)] = _batch_match_key(target)
        batches = _batch_inputs_from_bundle_zips(
            bundles,
            include_existing_names=args.only_unmapped_extension,
            aliases=aliases,
        )
    elif args.map_file:
        batches = _read_map_file(Path(args.map_file))
    else:
        batches = [
            BatchInput(
                batch_id=args.batch_id,
                zip_paths=args.zip or [],
                txt_dirs=args.txt_dir or [],
                from_gcs=args.from_gcs,
                gcs_prefixes=args.gcs_prefix or [],
                inline_zips=[],
            )
        ]

    worst = 0
    for batch in batches:
        code = run_batch(args, batch)
        worst = max(worst, code)
    return worst


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", help="Upload batch UUID to update.")
    parser.add_argument(
        "--list-batches",
        action="store_true",
        help="List batches and broker_name coverage, then exit.",
    )
    parser.add_argument(
        "--map-file",
        help=(
            "CSV file for multi-batch backfill. Columns: batch_id, zip_path "
            "(or zip), optional txt_dir, from_gcs, gcs_prefix."
        ),
    )
    parser.add_argument(
        "--bundle-zip",
        action="append",
        help=(
            "Local ZIP containing per-batch ZIP files. Inner ZIP names are matched "
            "to batch names after stripping trailing _1/_2 style numbers."
        ),
    )
    parser.add_argument(
        "--bundle-alias",
        action="append",
        help=(
            "Explicit batch-to-inner-ZIP name alias, e.g. "
            "0511_0515_ShunfaiTing=0511_0515_ShufaiTing. Can be repeated."
        ),
    )
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
    parser.add_argument(
        "--only-unmapped-extension",
        action="store_true",
        help=(
            "Only update recordings whose current extension has no unique active Broker mapping. "
            "This safely skips records already repaired from a configured extension and allows "
            "Extension Name from TXT to replace an existing Caller Name."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Write changes to the database.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum changed rows to print.")
    args = parser.parse_args()
    if args.list_batches:
        return args
    if args.bundle_zip:
        return args
    if args.map_file:
        return args
    if not args.batch_id:
        parser.error("--batch-id is required unless using --list-batches or --map-file")
    if not (args.zip or args.txt_dir or args.from_gcs):
        parser.error("provide at least one of --zip, --txt-dir, or --from-gcs")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
