# Mock integration package

Quam has not yet shared their transaction-system or telephony-recorder details, so this package **mocks both integration surfaces** with explicit, plausible contracts. Development proceeds against these; when the real details arrive, only configuration changes (see [Swap-in checklist](#swap-in-checklist-when-quam-shares-real-details)).

Everything derives from one fixture — [`data/golden_day.json`](data/golden_day.json) — a single trading day (2026-06-11) where call audio and transactions are mutually consistent and **every reconciliation outcome is known in advance**:

| Expected outcome | Count | Cases |
|---|---|---|
| Auto-matched | 7 txns | T1↔R1, T2↔R2, T3+T4↔R3 (multi-trade call), T5+T6↔R4 (split fill), T7↔R5 (Mandarin call) |
| Needs review | 1 | T8↔R8 (booked 6,000 vs instructed 8,000; no account spoken) |
| Txn, no recording → **breach** | 1 | T9 (phone-channel ICBC buy, no call exists) |
| Recording, no txn → **suspicious** | 1 | R6 (clear Meituan sell instruction, never booked) |
| Recording, no txn → info | 1 | R7 (balance/IPO inquiry, no trade discussed) |
| Excluded by import/recon filters | 3 | T10, T11 (INTERNET channel), T12 (CANCELLED status) |

Evaluation criteria also get known failures: **R2** skips the order read-back, **R8** skips identity verification.

## Contents

| Path | What it is |
|---|---|
| `data/golden_day.json` | Canonical fixture: brokers, clients, 8 scripted calls (Cantonese/Mandarin), 12 transactions, expected outcomes |
| `generate_eod_files.py` | → `data/eod_trades_<date>.csv` / `.xlsx` (file-import connector input) |
| `backoffice_api/main.py` | Mock REST API on :7880 (REST connector target) |
| `recorder/generate_recordings.py` | → stereo WAVs + `manifest.json` ground truth (batch-upload input) |
| `data/mapping_template.json` | The app-side CSV column-mapping config matching this schema |
| `data/brokers.csv` | AE code ↔ phone extension mapping (seed for `brokers` table) |
| `data/industry_terms.csv` | HK stock names/aliases + broker jargon (seed for `industry_terms`) |

## Quickstart

```bash
# EOD trade files (CSV + XLSX); --encoding big5 / utf-8-sig for realism, --date to restamp
uv run mocks/generate_eod_files.py

# Mock back-office API
uv run mocks/backoffice_api/main.py &
curl -H 'X-API-Key: quam-mock-key' \
  'http://localhost:7880/api/v1/trades?trade_date=2026-06-11&page=1&page_size=50'

# Synthetic recordings (macOS say + ffmpeg), plus a zip for batch-upload testing
uv run mocks/recorder/generate_recordings.py --zip
```

## Assumed contract 1 — EOD trade export (file)

CSV (UTF-8 / UTF-8-BOM / Big5-HKSCS) or XLSX (sheet `EOD_TRADES`), one row per **execution** (a partially-filled order appears as multiple rows sharing `ORDER_TIME`):

| Column | Example | Notes |
|---|---|---|
| `TRADE_REF` | `TRD-20260611-0001` | Unique per execution |
| `TRADE_DATE` | `2026-06-11` | |
| `ORDER_TIME` / `EXEC_TIME` | `2026-06-11 09:45:58` | **Naive HKT** (no timezone suffix); `EXEC_TIME` empty for cancelled rows |
| `ACCOUNT_NO` | `0188-100234` | |
| `CLIENT_NAME` | `CHAN TAI MAN 陳大文` | Romanized + Chinese, single field |
| `AE_CODE` | `AE012` | **Empty for internet/mobile orders** |
| `STOCK_CODE` | `00700` | **Zero-padded 5-digit HKEX style** (app normalizes to `700`) |
| `SIDE` | `B` / `S` | |
| `QTY` / `PRICE` / `AMOUNT` | `10000` / `612.00` / `6120000.00` | |
| `ORDER_CHANNEL` | `PHONE` / `INTERNET` / `MOBILE` | **Drives breach detection** — only PHONE requires a recording |
| `STATUS` | `FILLED` / `CANCELLED` | Import must filter to `FILLED` or cancelled phone orders become false breaches |

## Assumed contract 2 — back-office REST API

- `GET /api/v1/trades?trade_date=YYYY-MM-DD&page=1&page_size=50[&ae_code=][&order_channel=]`
- Auth: `X-API-Key` header (mock key: `quam-mock-key`)
- Response: `{trade_date, page, page_size, total, trades: [{trade_ref, trade_date, order_time, exec_time, account_no, client_name, ae_code, stock_code, stock_name, side, qty, price, amount, order_channel, status}]}`
- Page through until `page × page_size ≥ total`. `GET /api/v1/healthz` for the connector's "Test connection".
- Mock serves the fixture restamped to **any** requested date (set `MOCK_SERVE_ANY_DATE=0` to restrict to 2026-06-11).

## Assumed contract 3 — telephony recorder

- One stereo WAV per call, 16 kHz 16-bit PCM, **left = broker, right = customer** (`audio.broker_channel = left`)
- Filename: `{ext}_{YYYYMMDD}_{HHMMSS}_{IN|OUT}_{caller}.wav`, regex with named groups:
  `^(?P<broker_ext>\d{4})_(?P<date>\d{8})_(?P<time>\d{6})_(?P<direction>IN|OUT)_(?P<caller>\d+)\.wav$`
- Broker identity via extension → `brokers.phone_extensions` (see `data/brokers.csv`)
- `recorder/recordings/<date>/manifest.json` carries per-file ground truth for tests

**Limits of the synthetic audio**: `say` voices are clean studio TTS — fine for proving the pipeline (channel split, batch STT, evaluation, recon) but useless for judging real-world ASR accuracy on telephony audio. The Phase 1 STT spike still needs 3–5 real Quam recordings.

## Swap-in checklist (when Quam shares real details)

1. **File schema** → edit `data/mapping_template.json` equivalent in the app (saved mapping template; column names, encoding, side/channel/status vocabularies). No code.
2. **API** → update the REST source config (base URL, auth kind, path template, pagination, field mapping) and re-run "Test connection". No code.
3. **Recorder** → update `app_settings.filename.parse_regex` and `audio.broker_channel`; confirm sample rate/format with one real file through the pipeline.
4. **Re-validate** → run the golden-fixture recon test, then a real day side-by-side, before retiring the mocks.

## Open questions these mocks make concrete (take to Quam)

- Does the export have `ORDER_CHANNEL` (or equivalent)? Without it, every online order looks like a breach.
- Are partial fills separate rows? How are amended/cancelled orders represented?
- Timezone and encoding of the export; XLSX or CSV; delivery (SFTP drop? API? both?).
- Recorder filename convention, channel layout, and whether calls can span multiple files (transfers/holds).
