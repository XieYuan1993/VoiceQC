"""Transaction imports: CSV/XLSX files and scheduled/manual API pulls.

Re-import policy (DESIGN.md §6): a new completed import for the same
(source, trade_date) supersedes — the previous import's transactions are
deleted in the same DB transaction that inserts the new rows. Cross-source
duplicates (same ext_txn_id + trade_date from BOTH the CSV file and the API)
are skipped and counted, courtesy of the partial unique index.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from loguru import logger
from sqlalchemy import delete, select
from voiceqa_shared import gcs
from voiceqa_shared.crypto import decrypt_str
from voiceqa_shared.db_models import Transaction, TxnImport, TxnSourceConfig
from voiceqa_shared.txn_sources import CanonicalTxn, fetch_api, parse_file

from worker.celery_app import app
from worker.db import SessionLocal

HK = ZoneInfo("Asia/Hong_Kong")


def _supersede_and_insert(
    session, imp: TxnImport, txns: list[CanonicalTxn]
) -> tuple[int, int]:
    """Delete prior same-source transactions for the covered dates, insert new ones.

    Each row carries its own trade_date when the file provides one (a single EOD
    file can span several dates); rows without one fall back to imp.trade_date.
    Returns (imported, skipped)."""
    importable = [t for t in txns if t.skip_reason is None]
    for t in importable:
        if t.trade_date is None:
            t.trade_date = imp.trade_date
    dates = {t.trade_date for t in importable} or {imp.trade_date}

    # Supersede (DESIGN.md §6): a re-import of the same source/kind replaces prior
    # rows on the dates this file covers — date-aware for multi-date files.
    prior_import_ids = (
        session.execute(
            select(TxnImport.id).where(
                TxnImport.id != imp.id,
                TxnImport.status == "completed",
                TxnImport.source_config_id.is_not_distinct_from(imp.source_config_id),
                TxnImport.kind == imp.kind,
            )
        )
        .scalars()
        .all()
    )
    if prior_import_ids:
        session.execute(
            delete(Transaction).where(
                Transaction.import_id.in_(prior_import_ids),
                Transaction.trade_date.in_(dates),
            )
        )
        logger.info("import {}: superseded prior rows on {}", imp.id, sorted(dates))

    # Cross-source dedupe by (ext_txn_id, trade_date) — matches the partial unique
    # index, and avoids a constraint violation on re-import.
    existing = set(
        session.execute(
            select(Transaction.ext_txn_id, Transaction.trade_date).where(
                Transaction.trade_date.in_(dates),
                Transaction.ext_txn_id.is_not(None),
            )
        ).all()
    )

    imported = 0
    for txn in importable:
        key = (txn.ext_txn_id, txn.trade_date)
        if txn.ext_txn_id and key in existing:
            continue  # already present from another source
        if txn.ext_txn_id:
            existing.add(key)
        session.add(
            Transaction(
                import_id=imp.id,
                ext_txn_id=txn.ext_txn_id,
                trade_date=txn.trade_date,
                ordered_at=txn.ordered_at,
                executed_at=txn.executed_at,
                broker_code=txn.broker_code,
                client_account=txn.client_account,
                client_name=txn.client_name,
                stock_code=txn.stock_code,
                stock_name=txn.stock_name,
                side=txn.side,
                quantity=txn.quantity,
                price=txn.price,
                amount=txn.amount,
                channel=txn.channel,
                raw=txn.raw,
            )
        )
        imported += 1
    return imported, len(txns) - imported


def _finish(session, imp: TxnImport, txns: list[CanonicalTxn]) -> None:
    txns = [t for t in txns if t.skip_reason != "blank"]  # spacer rows aren't data
    imported, skipped = _supersede_and_insert(session, imp, txns)
    imp.row_count = len(txns)
    imp.imported_count = imported
    imp.skipped_count = skipped
    imp.status = "completed"
    imp.completed_at = datetime.now(UTC)
    session.commit()
    logger.info(
        "import {} completed: {} rows, {} imported, {} skipped",
        imp.id, len(txns), imported, skipped,
    )
    # Auto-reconcile every date this import touched, so uploaded trades are checked
    # against calls without a manual run. Never fail the import if recon can't start.
    try:
        from worker.tasks.recon import enqueue_recon_run

        dates = (
            session.execute(
                select(Transaction.trade_date).where(Transaction.import_id == imp.id).distinct()
            )
            .scalars()
            .all()
        )
        for d in dates:
            enqueue_recon_run(session, d)
        if dates:
            logger.info("import {}: auto-reconcile queued for {}", imp.id, sorted(dates))
    except Exception as e:
        logger.warning("import {}: auto-reconcile skipped: {}", imp.id, e)


@app.task(name="voiceqa.txn.import_csv", bind=True, max_retries=2)
def import_csv(self, import_id: str) -> None:
    with SessionLocal() as session:
        imp = session.get(TxnImport, uuid.UUID(import_id))
        if imp is None or imp.status not in ("pending", "processing"):
            return
        imp.status = "processing"
        session.commit()

        source = (
            session.get(TxnSourceConfig, imp.source_config_id)
            if imp.source_config_id
            else None
        )
        if source is None or not imp.gcs_uri:
            imp.status = "failed"
            imp.errors = ["missing source config or uploaded file"]
            session.commit()
            return
        try:
            data = gcs.read_uri_bytes(imp.gcs_uri)
            txns = parse_file(imp.file_name or "upload.csv", data, source.config)
            _finish(session, imp, txns)
        except Exception as e:
            imp.status = "failed"
            imp.errors = [str(e)[:500]]
            session.commit()
            logger.error("import {} failed: {}", import_id, e)
            raise


@app.task(name="voiceqa.txn.pull_api", bind=True, max_retries=2)
def pull_api(self, source_config_id: str, trade_date: str, import_id: str | None = None) -> None:
    day = date.fromisoformat(trade_date)
    with SessionLocal() as session:
        source = session.get(TxnSourceConfig, uuid.UUID(source_config_id))
        if source is None or source.kind != "api":
            return
        if import_id:
            imp = session.get(TxnImport, uuid.UUID(import_id))
            if imp is None:
                return
        else:
            imp = TxnImport(
                source_config_id=source.id,
                kind="api_pull",
                trade_date=day,
            )
            session.add(imp)
            session.flush()
        imp.status = "processing"
        session.commit()

        try:
            credential = decrypt_str(source.credentials_enc) if source.credentials_enc else None
            txns = fetch_api(source.config, credential, day)
            _finish(session, imp, txns)
            source.last_pulled_at = datetime.now(UTC)
            session.commit()
        except Exception as e:
            imp.status = "failed"
            imp.errors = [str(e)[:500]]
            session.commit()
            logger.error("api pull {} failed: {}", source_config_id, e)
            raise


@app.task(name="voiceqa.txn.scheduled_pulls")
def scheduled_pulls() -> None:
    """Beat task: fire API pulls whose cron schedule is due (for today, HK)."""
    now = datetime.now(UTC)
    due: list[str] = []
    with SessionLocal() as session:
        sources = (
            session.execute(
                select(TxnSourceConfig).where(
                    TxnSourceConfig.kind == "api",
                    TxnSourceConfig.active.is_(True),
                    TxnSourceConfig.schedule_cron.is_not(None),
                )
            )
            .scalars()
            .all()
        )
        for source in sources:
            try:
                anchor = source.last_pulled_at or datetime(2020, 1, 1, tzinfo=UTC)
                next_run = croniter(source.schedule_cron, anchor).get_next(datetime)
                if next_run <= now:
                    due.append(str(source.id))
            except Exception as e:
                logger.warning("bad schedule_cron on source {}: {}", source.id, e)
    today_hk = datetime.now(HK).date().isoformat()
    for source_id in due:
        pull_api.delay(source_id, today_hk)
    if due:
        logger.info("scheduled_pulls: dispatched {} pull(s)", len(due))
