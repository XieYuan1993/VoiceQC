"""Batch ingest: expand zips, parse filename metadata, dispatch chains."""

from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from celery import chain
from loguru import logger
from sqlalchemy import func, select
from voiceqa_shared import gcs
from voiceqa_shared.db_models import Recording, UploadBatch

from worker.celery_app import app
from worker.db import SessionLocal, get_setting

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}

# Zip-bomb guards.
MAX_ZIP_MEMBERS = 500
MAX_MEMBER_BYTES = 200 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 4 * 1024 * 1024 * 1024

HK = ZoneInfo("Asia/Hong_Kong")

TEXT_EXTS = {".txt", ".text"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "big5hkscs", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _parse_call_export_text(text: str) -> dict[str, str | datetime | None]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().casefold()
        value = value.strip()
        if key:
            fields[key] = value

    started_at = None
    start_raw = fields.get("call start time")
    if start_raw:
        try:
            started_at = datetime.strptime(start_raw, "%d %b %Y %H:%M:%S").replace(tzinfo=HK)
        except ValueError:
            logger.warning("bad Call Start Time in txt metadata: {}", start_raw)

    direction_raw = (fields.get("call direction") or "").casefold()
    if direction_raw.startswith("out"):
        direction = "OUT"
    elif direction_raw.startswith("in"):
        direction = "IN"
    else:
        direction = "unknown"

    return {
        "started_at": started_at,
        "broker_ext": fields.get("extension") or None,
        "caller_number": fields.get("other party")
        or fields.get("called number")
        or fields.get("caller number")
        or None,
        "direction": direction,
    }


def _metadata_key_from_start(meta: dict[str, str | datetime | None]) -> str | None:
    started = meta.get("started_at")
    if isinstance(started, datetime):
        return started.strftime("%Y%m%d_%H%M%S")
    return None


def _load_zip_text_metadata(zf: zipfile.ZipFile) -> dict[str, dict[str, str | datetime | None]]:
    metadata: dict[str, dict[str, str | datetime | None]] = {}
    for member in zf.infolist():
        if member.is_dir() or Path(member.filename).suffix.lower() not in TEXT_EXTS:
            continue
        name = Path(member.filename).name
        try:
            with zf.open(member) as f:
                metadata[name] = _parse_call_export_text(_decode_text(f.read()))
        except Exception as e:
            logger.warning("could not parse txt metadata {}: {}", name, e)
    return metadata


def _match_metadata_for_audio(
    audio_name: str,
    metadata: dict[str, dict[str, str | datetime | None]],
) -> dict[str, str | datetime | None] | None:
    audio_stem = Path(audio_name).stem

    # 1) Exact same stem, or a metadata filename/id contained in the audio name.
    for txt_name, meta in metadata.items():
        txt_stem = Path(txt_name).stem
        if txt_stem == audio_stem or txt_stem in audio_stem or audio_stem in txt_stem:
            return meta

    # 2) Fall back to Call Start Time -> YYYYMMDD_HHMMSS, matching the wav name.
    for meta in metadata.values():
        key = _metadata_key_from_start(meta)
        if key and key in audio_stem:
            return meta
    return None


def _apply_txt_metadata(rec: Recording, meta: dict[str, str | datetime | None] | None) -> None:
    if not meta:
        return
    rec.broker_ext = str(meta["broker_ext"]) if meta.get("broker_ext") else rec.broker_ext
    rec.caller_number = (
        str(meta["caller_number"]) if meta.get("caller_number") else rec.caller_number
    )
    rec.direction = str(meta.get("direction") or rec.direction or "unknown").upper()
    if isinstance(meta.get("started_at"), datetime):
        rec.call_started_at = meta["started_at"]


def _expand_zips(session, batch_id: str, project_id) -> int:
    """Extract audio members of every staged zip into recording rows."""
    created = 0
    filename_pattern = get_setting(session, project_id, "filename.parse_regex")
    try:
        filename_regex = re.compile(filename_pattern) if filename_pattern else None
    except re.error as e:
        logger.error("invalid filename.parse_regex while expanding zip: {}", e)
        filename_regex = None
    zip_keys = gcs.list_keys(f"raw/{batch_id}/_zips/")
    for key in zip_keys:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "batch.zip"
            gcs.download_uri_to_file(gcs.to_uri(key), str(zip_path))
            with zipfile.ZipFile(zip_path) as zf:
                txt_metadata = _load_zip_text_metadata(zf)
                members = [
                    m for m in zf.infolist()
                    if not m.is_dir()
                    and not m.filename.startswith("__MACOSX")
                    and not Path(m.filename).name.startswith(".")
                    and Path(m.filename).suffix.lower() in AUDIO_EXTS
                ]
                if len(members) > MAX_ZIP_MEMBERS:
                    raise RuntimeError(f"zip has {len(members)} members (max {MAX_ZIP_MEMBERS})")
                total = sum(m.file_size for m in members)
                if total > MAX_TOTAL_UNCOMPRESSED:
                    raise RuntimeError(f"zip expands to {total} bytes (max {MAX_TOTAL_UNCOMPRESSED})")

                for member in members:
                    if member.file_size > MAX_MEMBER_BYTES:
                        logger.warning("skipping oversized zip member {}", member.filename)
                        continue
                    name = Path(member.filename).name
                    out = Path(tmpdir) / name
                    with zf.open(member) as src, out.open("wb") as dst:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            dst.write(chunk)
                    sha = _sha256_file(out)
                    dup = session.execute(
                        select(Recording.id).where(
                            Recording.batch_id == uuid.UUID(batch_id),
                            Recording.sha256 == sha,
                        )
                    ).scalar_one_or_none()
                    if dup is not None:
                        logger.warning("duplicate in batch, skipping zip member {}", name)
                        continue
                    rid = uuid.uuid4()
                    raw_uri = gcs.upload_file(f"raw/{batch_id}/{rid}/{name}", str(out))
                    recording = Recording(
                        id=rid,
                        project_id=project_id,
                        batch_id=uuid.UUID(batch_id),
                        original_filename=name,
                        sha256=sha,
                        size_bytes=out.stat().st_size,
                        gcs_uri_raw=raw_uri,
                    )
                    if not (filename_regex and filename_regex.match(name)):
                        _apply_txt_metadata(
                            recording,
                            _match_metadata_for_audio(name, txt_metadata),
                        )
                    session.add(
                        recording
                    )
                    created += 1
        gcs.delete_key(key)
    session.commit()
    return created


def _parse_filenames(session, batch_id: str, project_id) -> None:
    """Fill broker_ext / call_started_at / caller / direction from filenames."""
    pattern = get_setting(session, project_id, "filename.parse_regex")
    if not pattern:
        return
    try:
        regex = re.compile(pattern)
    except re.error as e:
        logger.error("invalid filename.parse_regex: {}", e)
        return

    rows = (
        session.execute(
            select(Recording).where(
                Recording.batch_id == uuid.UUID(batch_id),
                Recording.call_started_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    for rec in rows:
        m = regex.match(rec.original_filename)
        if not m:
            logger.warning("filename does not match recorder pattern: {}", rec.original_filename)
            continue
        groups = m.groupdict()
        rec.broker_ext = groups.get("broker_ext") or rec.broker_ext
        rec.caller_number = groups.get("caller") or rec.caller_number
        rec.direction = (groups.get("direction") or "unknown").upper()
        if groups.get("date") and groups.get("time"):
            try:
                rec.call_started_at = datetime.strptime(
                    groups["date"] + groups["time"], "%Y%m%d%H%M%S"
                ).replace(tzinfo=HK)
            except ValueError:
                logger.warning("bad timestamp in filename: {}", rec.original_filename)
    session.commit()


@app.task(name="voiceqa.ingest.expand_batch", bind=True)
def expand_batch(self, batch_id: str) -> None:
    from worker.tasks.batch import update_progress
    from worker.tasks.pipeline import normalize_audio, transcribe

    with SessionLocal() as session:
        batch = session.get(UploadBatch, uuid.UUID(batch_id))
        if batch is None:
            return
        project_id = batch.project_id

        try:
            created = _expand_zips(session, batch_id, project_id)
            if created:
                logger.info("expanded {} recordings from zips in batch {}", created, batch_id)
        except Exception as e:
            logger.error("zip expansion failed for batch {}: {}", batch_id, e)
            # Individual uploads still proceed; the batch surfaces the error.

        _parse_filenames(session, batch_id, project_id)

        batch.total_files = session.execute(
            select(func.count()).select_from(Recording).where(
                Recording.batch_id == uuid.UUID(batch_id)
            )
        ).scalar_one()
        session.commit()

        pending = (
            session.execute(
                select(Recording.id).where(
                    Recording.batch_id == uuid.UUID(batch_id),
                    Recording.status == "uploaded",
                )
            )
            .scalars()
            .all()
        )

    for rid in pending:
        chain(normalize_audio.si(str(rid)), transcribe.si(str(rid))).apply_async()
    logger.info("batch {} dispatched {} pipeline chains", batch_id, len(pending))
    update_progress.delay(batch_id)
