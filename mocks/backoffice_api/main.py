# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.30"]
# ///
"""Mock Quam back-office REST API.

Stands in for the (not yet shared) customer transaction system so the
REST TransactionSource connector can be built and tested end-to-end.
Serves the golden-day fixture, restamped to any requested trade date.

Run:    uv run mocks/backoffice_api/main.py          # listens on :7880
Try:    curl -H 'X-API-Key: quam-mock-key' \
          'http://localhost:7880/api/v1/trades?trade_date=2026-06-11&page=1&page_size=50'

Env:    MOCK_API_KEY        (default quam-mock-key)
        MOCK_PORT           (default 7880)
        MOCK_SERVE_ANY_DATE (default 1 — restamp fixture rows to any requested
                             date; set 0 to only answer for the fixture date)
"""

from __future__ import annotations

import json
import os
from datetime import date as date_t
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "golden_day.json"
API_KEY = os.environ.get("MOCK_API_KEY", "quam-mock-key")
SERVE_ANY_DATE = os.environ.get("MOCK_SERVE_ANY_DATE", "1") == "1"

app = FastAPI(title="Mock Quam Back-Office", version="0.1.0")


def _load_trades() -> tuple[str, list[dict]]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    clients = {c["id"]: c for c in fixture["clients"]}
    rows = []
    for txn in fixture["transactions"]:
        client = clients[txn["client"]]
        rows.append({
            "trade_ref": txn["trade_ref"],
            "trade_date": fixture["trade_date"],
            "order_time": txn["order_time"],
            "exec_time": txn["exec_time"],
            "account_no": client["account"],
            "client_name": f"{client['name_en']} {client['name_zh']}",
            "ae_code": txn["ae_code"],
            "stock_code": txn["stock_code"],
            "stock_name": txn["stock_name"],
            "side": txn["side"],
            "qty": txn["qty"],
            "price": txn["price"],
            "amount": txn["amount"],
            "order_channel": txn["order_channel"],
            "status": txn["status"],
        })
    rows.sort(key=lambda r: r["order_time"] or "")
    return fixture["trade_date"], rows


FIXTURE_DATE, TRADES = _load_trades()


def _restamp(row: dict, day: str) -> dict:
    out = dict(row)
    out["trade_date"] = day
    out["trade_ref"] = row["trade_ref"].replace(FIXTURE_DATE.replace("-", ""), day.replace("-", ""))
    for key in ("order_time", "exec_time"):
        out[key] = f"{day} {row[key]}" if row[key] else None
    return out


@app.get("/api/v1/healthz")
def healthz() -> dict:
    return {"status": "ok", "fixture_date": FIXTURE_DATE, "trades": len(TRADES)}


@app.get("/api/v1/trades")
def trades(
    trade_date: str = Query(..., description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    ae_code: str | None = None,
    order_channel: str | None = None,
    x_api_key: str | None = Header(default=None),
) -> dict:
    if x_api_key != API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key")
    try:
        date_t.fromisoformat(trade_date)
    except ValueError:
        raise HTTPException(422, "trade_date must be YYYY-MM-DD")

    if trade_date == FIXTURE_DATE or SERVE_ANY_DATE:
        rows = [_restamp(r, trade_date) for r in TRADES]
    else:
        rows = []
    if ae_code is not None:
        rows = [r for r in rows if r["ae_code"] == ae_code]
    if order_channel is not None:
        rows = [r for r in rows if r["order_channel"] == order_channel.upper()]

    start = (page - 1) * page_size
    return {
        "trade_date": trade_date,
        "page": page,
        "page_size": page_size,
        "total": len(rows),
        "trades": rows[start : start + page_size],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MOCK_PORT", "7880")))
