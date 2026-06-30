"""Data retention (Phase 4): purge aged audio + transcripts past
retention.days, while keeping the compliance record (evaluations, trade
instructions, reconciliation, audit log).

The biggest PII and storage cost is the raw call audio and the verbatim
transcript; those are deleted once a recording's call date passes the
retention window. The recording row, its evaluations, and extracted trade
instructions are retained — they are the durable compliance artifact and
hold far less raw client speech.

Runs daily via celery beat. Idempotent: only acts on rows that still have
GCS objects to remove.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import delete, select
from voiceqa_shared import gcs
from voiceqa_shared.db_models import Recording, Transcript, TxnImport

from worker.celery_app import app
from worker.db import SessionLocal, default_project_id, get_setting

BATCH = 200


def _retention_cutoff(session) -> datetime:
    # Retention is per-project; the global sweep uses the default project's
    # window (per-project sweeps can be added later).
    days = int(get_setting(session, default_project_id(session), "retention.days", 365))
    return datetime.now(UTC) - timedelta(days=days)


def retention_preview(session) -> dict:
    cutoff = _retention_cutoff(session)
    recs = session.execute(
        select(Recording.id).where(
            Recording.call_started_at < cutoff,
            Recording.gcs_uri_raw.is_not(None),
        )
    ).all()
    imports = session.execute(
        select(TxnImport.id).where(
            TxnImport.trade_date < cutoff.date(),
            TxnImport.gcs_uri.is_not(None),
        )
    ).all()
    return {
        "cutoff": cutoff.date().isoformat(),
        "recordings_to_purge": len(recs),
        "txn_files_to_purge": len(imports),
    }


@app.task(name="voiceqa.maintenance.apply_retention")
def apply_retention() -> dict:
    purged_recordings = purged_objects = purged_txn_files = 0
    with SessionLocal() as session:
        cutoff = _retention_cutoff(session)

        recordings = (
            session.execute(
                select(Recording)
                .where(
                    Recording.call_started_at < cutoff,
                    Recording.gcs_uri_raw.is_not(None),
                )
                .limit(BATCH)
            )
            .scalars()
            .all()
        )
        for rec in recordings:
            for uri in (
                rec.gcs_uri_raw,
                rec.gcs_uri_broker,
                rec.gcs_uri_customer,
                rec.gcs_uri_mono,
            ):
                if uri and gcs.delete_uri(uri):
                    purged_objects += 1
            rec.gcs_uri_raw = None
            rec.gcs_uri_broker = None
            rec.gcs_uri_customer = None
            rec.gcs_uri_mono = None
            # Drop verbatim transcript + segments (segments cascade).
            session.execute(delete(Transcript).where(Transcript.recording_id == rec.id))
            purged_recordings += 1

        imports = (
            session.execute(
                select(TxnImport)
                .where(
                    TxnImport.trade_date < cutoff.date(),
                    TxnImport.gcs_uri.is_not(None),
                )
                .limit(BATCH)
            )
            .scalars()
            .all()
        )
        for imp in imports:
            if gcs.delete_uri(imp.gcs_uri):
                purged_txn_files += 1
            imp.gcs_uri = None

        session.commit()

    result = {
        "purged_recordings": purged_recordings,
        "purged_objects": purged_objects,
        "purged_txn_files": purged_txn_files,
    }
    if purged_recordings or purged_txn_files:
        logger.info("retention applied: {}", result)
    return result
