"""Transactions, imports (CSV upload + dry-run preview), and source configs."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared import gcs
from voiceqa_shared.audit import log_audit
from voiceqa_shared.crypto import decrypt_str, encrypt_str
from voiceqa_shared.db_models import (
    ReconItem,
    ReconRun,
    Transaction,
    TxnImport,
    TxnSourceConfig,
    User,
)
from voiceqa_shared.txn_sources import detected_trade_dates, fetch_api, parse_file

from app import queue
from app.db import get_session
from app.deps import ClientMeta, client_meta, require_project_module, resolve_project_id
from app.permissions import TXNS_IMPORT, TXNS_READ, require
from app.schemas import (
    DryRunOut,
    ImportOut,
    SkippedRowOut,
    SourceIn,
    SourceOut,
    SourceTestOut,
    TxnListOut,
    TxnOut,
)

router = APIRouter(
    prefix="/api",
    tags=["transactions"],
    dependencies=[Depends(require_project_module("trade_reconciliation"))],
)

MAX_TXN_FILE_BYTES = 50 * 1024 * 1024


def _txn_out(t: Transaction, recon_status: str | None = None) -> TxnOut:
    return TxnOut(
        id=t.id,
        ext_txn_id=t.ext_txn_id,
        trade_date=t.trade_date,
        ordered_at=t.ordered_at,
        executed_at=t.executed_at,
        broker_code=t.broker_code,
        client_account=t.client_account,
        client_name=t.client_name,
        stock_code=t.stock_code,
        stock_name=t.stock_name,
        side=t.side,
        quantity=float(t.quantity) if t.quantity is not None else None,
        price=float(t.price) if t.price is not None else None,
        amount=float(t.amount) if t.amount is not None else None,
        channel=t.channel,
        recon_status=recon_status,
    )


@router.get("/transactions", response_model=TxnListOut)
async def list_transactions(
    trade_date: date | None = None,
    broker_code: str | None = None,
    stock_code: str | None = None,
    recon_status: str | None = None,  # matched | needs_review | unmapped | not_run
    import_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
) -> TxnListOut:
    page, page_size = max(1, page), min(max(1, page_size), 200)
    # Each trade's reconciliation status = its finding in the LATEST completed run
    # for that trade date. No run / not in the latest run -> "not_run".
    latest_run = (
        select(ReconRun.id.label("run_id"), ReconRun.trade_date.label("td"))
        .distinct(ReconRun.trade_date)
        .where(ReconRun.status == "completed")
        .order_by(ReconRun.trade_date, ReconRun.started_at.desc())
        .subquery()
    )
    status_case = case(
        (ReconItem.id.is_(None), "not_run"),
        (ReconItem.item_type == "txn_no_recording", "unmapped"),
        (ReconItem.match_status == "rejected", "unmapped"),
        (ReconItem.match_status == "needs_review", "needs_review"),
        else_="matched",
    )
    stmt = (
        select(Transaction, status_case.label("recon_status"))
        .select_from(Transaction)
        .outerjoin(latest_run, latest_run.c.td == Transaction.trade_date)
        .outerjoin(
            ReconItem,
            and_(
                ReconItem.run_id == latest_run.c.run_id,
                ReconItem.transaction_id == Transaction.id,
            ),
        )
    )
    if trade_date is not None:
        stmt = stmt.where(Transaction.trade_date == trade_date)
    if broker_code:
        stmt = stmt.where(Transaction.broker_code == broker_code)
    if stock_code:
        stmt = stmt.where(Transaction.stock_code == stock_code.lstrip("0"))
    if recon_status:
        stmt = stmt.where(status_case == recon_status)
    if import_id is not None:
        stmt = stmt.where(Transaction.import_id == import_id)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Transaction.executed_at.asc().nulls_last())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return TxnListOut(
        items=[_txn_out(t, status) for t, status in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- Sources -----------------------------------------------------------------


def _source_out(s: TxnSourceConfig) -> SourceOut:
    return SourceOut(
        id=s.id,
        name=s.name,
        kind=s.kind,
        active=s.active,
        config=dict(s.config or {}),
        has_credential=s.credentials_enc is not None,
        schedule_cron=s.schedule_cron,
        last_pulled_at=s.last_pulled_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _validate_source(payload: SourceIn) -> None:
    cfg = payload.config
    required = (
        ("column_mapping",) if payload.kind == "csv" else ("base_url", "path_template", "field_mapping")
    )
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"config missing keys: {missing}")


@router.get("/txn-sources", response_model=list[SourceOut])
async def list_sources(
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[SourceOut]:
    rows = (await session.execute(select(TxnSourceConfig).order_by(TxnSourceConfig.name))).scalars()
    return [_source_out(s) for s in rows]


@router.post("/txn-sources", response_model=SourceOut)
async def create_source(
    payload: SourceIn,
    user: User = Depends(require(TXNS_IMPORT)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> SourceOut:
    _validate_source(payload)
    dup = (
        await session.execute(select(TxnSourceConfig.id).where(TxnSourceConfig.name == payload.name))
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"source {payload.name!r} already exists")
    source = TxnSourceConfig(
        name=payload.name,
        kind=payload.kind,
        active=payload.active,
        config=payload.config,
        credentials_enc=encrypt_str(payload.credential) if payload.credential else None,
        schedule_cron=payload.schedule_cron,
        created_by=user.id,
    )
    session.add(source)
    await session.flush()
    log_audit(
        session, action="txn_source.create", user_id=user.id, actor_email=user.email,
        object_type="txn_source", object_id=str(source.id), details={"name": source.name},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    await session.refresh(source)
    return _source_out(source)


@router.patch("/txn-sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceIn,
    user: User = Depends(require(TXNS_IMPORT)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> SourceOut:
    source = await session.get(TxnSourceConfig, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    _validate_source(payload)
    source.name = payload.name
    source.kind = payload.kind
    source.active = payload.active
    source.config = payload.config
    source.schedule_cron = payload.schedule_cron
    if payload.credential:  # empty/None keeps the existing secret
        source.credentials_enc = encrypt_str(payload.credential)
    log_audit(
        session, action="txn_source.update", user_id=user.id, actor_email=user.email,
        object_type="txn_source", object_id=str(source.id), details={"name": source.name},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    await session.refresh(source)
    return _source_out(source)


@router.post("/txn-sources/{source_id}/test", response_model=SourceTestOut)
async def test_source(
    source_id: uuid.UUID,
    user: User = Depends(require(TXNS_IMPORT)),
    session: AsyncSession = Depends(get_session),
) -> SourceTestOut:
    source = await session.get(TxnSourceConfig, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    if source.kind == "csv":
        missing = [k for k in ("column_mapping",) if not source.config.get(k)]
        return SourceTestOut(ok=not missing, detail="mapping looks valid" if not missing else f"missing {missing}")
    try:
        credential = decrypt_str(source.credentials_enc) if source.credentials_enc else None
        config = {**source.config, "pagination": {**(source.config.get("pagination") or {}), "page_size": 5}}
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
        rows = await run_in_threadpool(fetch_api, config, credential, today)
        sample = [
            {k: v for k, v in asdict(r).items() if k in ("ext_txn_id", "stock_code", "side", "quantity", "price", "channel") }
            for r in rows[:3]
        ]
        return SourceTestOut(ok=True, detail=f"fetched {len(rows)} row(s)", sample=sample)
    except Exception as e:
        return SourceTestOut(ok=False, detail=str(e)[:300])


@router.post("/txn-sources/{source_id}/pull", response_model=ImportOut)
async def pull_source(
    source_id: uuid.UUID,
    trade_date: date = Query(...),
    user: User = Depends(require(TXNS_IMPORT)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ImportOut:
    source = await session.get(TxnSourceConfig, source_id)
    if source is None or source.kind != "api":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "api source not found")
    imp = TxnImport(
        source_config_id=source.id, kind="api_pull", trade_date=trade_date, created_by=user.id
    )
    session.add(imp)
    await session.flush()
    log_audit(
        session, action="txn_import.pull", user_id=user.id, actor_email=user.email,
        object_type="txn_import", object_id=str(imp.id),
        details={"source": source.name, "trade_date": str(trade_date)},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send("voiceqa.txn.pull_api", str(source.id), trade_date.isoformat(), str(imp.id))
    return _import_out(imp)


# --- Imports ------------------------------------------------------------------


def _import_out(i: TxnImport) -> ImportOut:
    return ImportOut(
        id=i.id,
        source_config_id=i.source_config_id,
        kind=i.kind,
        trade_date=i.trade_date,
        file_name=i.file_name,
        status=i.status,
        row_count=i.row_count,
        imported_count=i.imported_count,
        skipped_count=i.skipped_count,
        errors=list(i.errors or []),
        created_at=i.created_at,
        completed_at=i.completed_at,
    )


@router.get("/txn-imports", response_model=list[ImportOut])
async def list_imports(
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ImportOut]:
    rows = (
        await session.execute(
            select(TxnImport).order_by(TxnImport.created_at.desc()).limit(50)
        )
    ).scalars()
    return [_import_out(i) for i in rows]


@router.get("/txn-imports/{import_id}/skipped", response_model=list[SkippedRowOut])
async def import_skipped_rows(
    import_id: uuid.UUID,
    user: User = Depends(require(TXNS_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[SkippedRowOut]:
    """Re-parse the stored file to explain why each non-imported row was skipped."""
    imp = await session.get(TxnImport, import_id)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import not found")
    if not imp.gcs_uri or imp.source_config_id is None:
        return []
    source = await session.get(TxnSourceConfig, imp.source_config_id)
    if source is None:
        return []
    data = await run_in_threadpool(gcs.read_uri_bytes, imp.gcs_uri)
    txns = await run_in_threadpool(parse_file, imp.file_name or "import.csv", data, source.config)
    return [
        SkippedRowOut(
            reason=t.skip_reason,
            ext_txn_id=t.ext_txn_id,
            stock_code=t.stock_code,
            side=t.side,
            quantity=t.quantity,
            raw={k: ("" if v is None else str(v)) for k, v in (t.raw or {}).items()},
        )
        for t in txns
        if t.skip_reason and t.skip_reason != "blank"
    ]


@router.delete("/txn-imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(
    import_id: uuid.UUID,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(TXNS_IMPORT)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> Response:
    """Delete an import and (by cascade) its transactions, then re-reconcile the
    affected dates so mapping/coverage reflects the removal."""
    from app.routers.recon import build_recon_run

    imp = await session.get(TxnImport, import_id)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import not found")
    dates = (
        (
            await session.execute(
                select(Transaction.trade_date).where(Transaction.import_id == import_id).distinct()
            )
        )
        .scalars()
        .all()
    )
    log_audit(
        session, action="txn_import.delete", user_id=user.id, actor_email=user.email,
        object_type="txn_import", object_id=str(import_id),
        details={"file": imp.file_name, "trade_dates": [str(d) for d in dates]},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.delete(imp)  # cascades to this import's transactions
    runs = [await build_recon_run(session, project_id, d, user.id) for d in dates]
    await session.commit()
    for r in runs:
        queue.send("voiceqa.recon.run", str(r.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_TXN_FILE_BYTES + 1)
    if len(data) > MAX_TXN_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large")
    return data


@router.post("/txn-imports/csv", response_model=ImportOut)
async def import_csv(
    file: UploadFile,
    source_config_id: uuid.UUID = Form(...),
    trade_date: date | None = Form(None),
    user: User = Depends(require(TXNS_IMPORT)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ImportOut:
    source = await session.get(TxnSourceConfig, source_config_id)
    if source is None or source.kind != "csv":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "csv source (mapping template) not found")
    filename = file.filename or "trades.csv"
    data = await _read_upload(file)

    # When the mapping template maps a trade-date column, take the date(s) from the
    # file — no need to ask for what the sheet already states. The manual field is a
    # fallback for files without a date column. (Each row keeps its own date on insert.)
    if trade_date is None:
        try:
            parsed = await run_in_threadpool(parse_file, filename, data, source.config)
        except Exception as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"parse failed: {e}") from e
        dates = detected_trade_dates(parsed)
        if not dates:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "No trade date found in the file — pick a mapping template that maps a "
                "trade-date column, or supply a trade date.",
            )
        trade_date = dates[0]

    imp = TxnImport(
        source_config_id=source.id,
        kind="csv_upload",
        trade_date=trade_date,
        file_name=filename,
        created_by=user.id,
    )
    session.add(imp)
    await session.flush()
    # Raw file retained as evidence.
    key = f"txn-imports/{imp.id}/{filename}"
    import io

    imp.gcs_uri = await run_in_threadpool(gcs.upload_fileobj, key, io.BytesIO(data))
    log_audit(
        session, action="txn_import.upload", user_id=user.id, actor_email=user.email,
        object_type="txn_import", object_id=str(imp.id),
        details={"file": filename, "trade_date": str(trade_date)},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    queue.send("voiceqa.txn.import_csv", str(imp.id))
    return _import_out(imp)


@router.post("/txn-imports/csv/dry-run", response_model=DryRunOut)
async def dry_run_csv(
    file: UploadFile,
    source_config_id: uuid.UUID = Form(...),
    user: User = Depends(require(TXNS_IMPORT)),
    session: AsyncSession = Depends(get_session),
) -> DryRunOut:
    """Parse + validate without importing — powers the wizard preview."""
    source = await session.get(TxnSourceConfig, source_config_id)
    if source is None or source.kind != "csv":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "csv source (mapping template) not found")
    data = await _read_upload(file)
    try:
        txns = await run_in_threadpool(parse_file, file.filename or "trades.csv", data, source.config)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"parse failed: {e}") from e

    txns = [t for t in txns if t.skip_reason != "blank"]  # drop spacer rows from counts
    importable = [t for t in txns if t.skip_reason is None]
    preview = []
    for t in (importable + [t for t in txns if t.skip_reason])[:8]:
        row = asdict(t)
        row.pop("raw", None)
        row["trade_date"] = t.trade_date.isoformat() if t.trade_date else None
        row["ordered_at"] = t.ordered_at.isoformat() if t.ordered_at else None
        row["executed_at"] = t.executed_at.isoformat() if t.executed_at else None
        preview.append(row)
    return DryRunOut(
        rows_total=len(txns),
        importable=len(importable),
        skipped_status=sum(1 for t in txns if t.skip_reason == "status"),
        skipped_side=sum(1 for t in txns if t.skip_reason == "side"),
        skipped_duplicate=sum(1 for t in txns if t.skip_reason == "duplicate"),
        trade_dates=[d.isoformat() for d in detected_trade_dates(txns)],
        preview=preview,
    )
