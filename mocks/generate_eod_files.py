# /// script
# requires-python = ">=3.11"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Generate mock end-of-day (EOD) trade export files from the golden-day fixture.

Produces the two file shapes Quam's back office is assumed to export:
  - eod_trades_<date>.csv   (default UTF-8; --encoding utf-8-sig / big5 for realism)
  - eod_trades_<date>.xlsx  (sheet EOD_TRADES)

Usage:
  uv run mocks/generate_eod_files.py                       # fixture date (2026-06-11)
  uv run mocks/generate_eod_files.py --date 2026-06-12     # restamp rows to another date
  uv run mocks/generate_eod_files.py --encoding big5
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "data" / "golden_day.json"

COLUMNS = [
    "TRADE_REF", "TRADE_DATE", "ORDER_TIME", "EXEC_TIME", "ACCOUNT_NO",
    "CLIENT_NAME", "AE_CODE", "STOCK_CODE", "STOCK_NAME", "SIDE",
    "QTY", "PRICE", "AMOUNT", "ORDER_CHANNEL", "STATUS",
]

# HK back-office exports are frequently Big5; big5hkscs covers HK-specific chars.
ENCODINGS = {"utf-8": "utf-8", "utf-8-sig": "utf-8-sig", "big5": "big5hkscs"}


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build_rows(fixture: dict, date: str) -> list[dict]:
    clients = {c["id"]: c for c in fixture["clients"]}
    orig_date = fixture["trade_date"]
    rows = []
    for txn in fixture["transactions"]:
        client = clients[txn["client"]]
        trade_ref = txn["trade_ref"].replace(orig_date.replace("-", ""), date.replace("-", ""))
        rows.append({
            "TRADE_REF": trade_ref,
            "TRADE_DATE": date,
            "ORDER_TIME": f"{date} {txn['order_time']}" if txn["order_time"] else "",
            "EXEC_TIME": f"{date} {txn['exec_time']}" if txn["exec_time"] else "",
            "ACCOUNT_NO": client["account"],
            "CLIENT_NAME": f"{client['name_en']} {client['name_zh']}",
            "AE_CODE": txn["ae_code"],
            "STOCK_CODE": txn["stock_code"],
            "STOCK_NAME": txn["stock_name"],
            "SIDE": txn["side"],
            "QTY": txn["qty"],
            "PRICE": f"{txn['price']:.2f}",
            "AMOUNT": f"{txn['amount']:.2f}" if txn["amount"] is not None else "",
            "ORDER_CHANNEL": txn["order_channel"],
            "STATUS": txn["status"],
        })
    rows.sort(key=lambda r: r["ORDER_TIME"])
    return rows


def write_csv(rows: list[dict], path: Path, encoding: str) -> None:
    with path.open("w", newline="", encoding=ENCODINGS[encoding]) as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(rows: list[dict], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "EOD_TRADES"
    ws.append(COLUMNS)
    for r in rows:
        ws.append([
            r["TRADE_REF"], r["TRADE_DATE"], r["ORDER_TIME"], r["EXEC_TIME"],
            r["ACCOUNT_NO"], r["CLIENT_NAME"], r["AE_CODE"], r["STOCK_CODE"],
            r["STOCK_NAME"], r["SIDE"], int(r["QTY"]), float(r["PRICE"]),
            float(r["AMOUNT"]) if r["AMOUNT"] else None, r["ORDER_CHANNEL"], r["STATUS"],
        ])
    wb.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="Restamp rows to this trade date (YYYY-MM-DD)")
    parser.add_argument("--encoding", choices=list(ENCODINGS), default="utf-8")
    parser.add_argument("--out", type=Path, default=HERE / "data")
    args = parser.parse_args()

    fixture = load_fixture()
    date = args.date or fixture["trade_date"]
    rows = build_rows(fixture, date)

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"eod_trades_{date}.csv"
    xlsx_path = args.out / f"eod_trades_{date}.xlsx"
    write_csv(rows, csv_path, args.encoding)
    write_xlsx(rows, xlsx_path)
    print(f"wrote {csv_path} ({len(rows)} rows, {args.encoding})")
    print(f"wrote {xlsx_path}")


if __name__ == "__main__":
    main()
