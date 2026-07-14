"""Golden-fixture test for the recon engine (pure, no DB).

Mirrors mocks/data/golden_day.json: 11 imported transactions (the cancelled
row never reaches the engine), 10 trade instructions across 7 recordings,
one zero-instruction recording. Known truth (mocks/README.md):

- 7 auto-matches, incl. one multi-trade call (T3+T4 -> R3) and one split
  fill (T5+T6 share R4's single instruction)
- 1 needs-review (T8: booked 6,000 vs instructed 8,000, no account spoken)
- 1 breach (T9: phone order, no recording)
- 1 suspicious (R6's Meituan sell never booked)
- 1 info (R7: inquiry call, no instructions)
- 2 excluded internet transactions
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from worker.recon.engine import InstrView, Params, RecordingView, TxnView, fold, run_match
from worker.tasks.recon import _passes_transaction_filters

HK = ZoneInfo("Asia/Hong_Kong")
D = "2026-06-11"


def hk(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{D}T{hhmm}:00+08:00").astimezone(HK)


BROKER_EXTENSIONS = {"AE012": {"2012"}, "AE015": {"2015"}, "AE020": {"2020"}}

ALIAS_MAP = {
    fold(name): code
    for code, names in {
        "700": ["騰訊控股", "騰訊", "Tencent"],
        "5": ["匯豐控股", "匯豐", "HSBC"],
        "939": ["建設銀行", "建行", "CCB"],
        "1810": ["小米集團", "小米", "Xiaomi"],
        "3988": ["中國銀行", "中行", "BOC"],
        "1299": ["友邦保險", "友邦", "AIA"],
        "2318": ["中國平安", "平安", "Ping An"],
        "3690": ["美團", "Meituan"],
        "1398": ["工商銀行", "工行", "ICBC"],
    }.items()
    for name in names
}


def txn(tid, ordered, broker, account, name, code, side, qty, price, channel="phone"):
    return TxnView(
        id=tid,
        anchor=hk(ordered),
        broker_code=broker,
        client_account=account,
        client_name=name,
        stock_code=code,
        stock_name=None,
        side=side,
        quantity=qty,
        price=price,
        channel=channel,
    )


def instr(
    iid, rec, started, ext, code, name_raw, side, qty, price, ptype, client=None, account=None
):
    return InstrView(
        id=iid,
        recording_id=rec,
        call_started_at=hk(started),
        call_duration_seconds=120,
        broker_ext=ext,
        stock_code=code,
        stock_name_raw=name_raw,
        side=side,
        quantity=qty,
        price=price,
        price_type=ptype,
        client_name_raw=client,
        client_account_raw=account,
    )


TXNS = [
    txn("T1", "09:45", "AE012", "0188-100234", "CHAN TAI MAN 陳大文", "700", "buy", 10000, 612.0),
    txn("T2", "10:06", "AE015", "0188-100567", "WONG SIU MEI 黃小美", "939", "sell", 40000, 6.62),
    txn("T3", "10:34", "AE012", "0188-101888", "LEE KA HO 李家豪", "5", "buy", 5000, 102.5),
    txn("T4", "10:32", "AE012", "0188-101888", "LEE KA HO 李家豪", "1810", "sell", 20000, 55.25),
    txn("T5", "11:15", "AE020", "0188-102456", "CHEUNG MAN KIT 張文傑", "3988", "buy", 60000, 3.55),
    txn("T6", "11:15", "AE020", "0188-102456", "CHEUNG MAN KIT 張文傑", "3988", "buy", 40000, 3.55),
    txn("T7", "11:47", "AE015", "0188-103999", "NG WING YAN 吳詠欣", "1299", "buy", 2000, 88.65),
    txn("T8", "15:12", "AE015", "0188-105321", "KWOK YEE LING 郭綺玲", "2318", "buy", 6000, 35.9),
    txn("T9", "14:40", "AE015", "0188-106654", "HO CHUN YIN 何俊賢", "1398", "buy", 50000, 5.84),
    txn(
        "T10",
        "12:15",
        None,
        "0188-100567",
        "WONG SIU MEI 黃小美",
        "700",
        "sell",
        3000,
        614.2,
        channel="online",
    ),
    txn(
        "T11",
        "15:41",
        None,
        "0188-103999",
        "NG WING YAN 吳詠欣",
        "2800",
        "buy",
        10000,
        19.84,
        channel="online",
    ),
]

INSTRS = [
    instr(
        "I1",
        "R1",
        "09:42",
        "2012",
        "700",
        "騰訊",
        "buy",
        10000,
        612.0,
        "limit",
        client="陳大文",
        account="0188100234",
    ),
    instr(
        "I2",
        "R2",
        "10:05",
        "2015",
        "939",
        "建行",
        "sell",
        40000,
        None,
        "market",
        client="黃小美",
        account="0567",
    ),
    instr(
        "I3a",
        "R3",
        "10:31",
        "2012",
        "5",
        "匯豐",
        "buy",
        5000,
        102.5,
        "limit",
        client="李家豪",
        account="0188101888",
    ),
    instr(
        "I3b",
        "R3",
        "10:31",
        "2012",
        "1810",
        "小米",
        "sell",
        20000,
        None,
        "market",
        client="李家豪",
        account="0188101888",
    ),
    # Split fill: ONE instruction for 100k serves T5 (60k) + T6 (40k).
    instr(
        "I4",
        "R4",
        "11:12",
        "2020",
        "3988",
        "中國銀行",
        "buy",
        100000,
        3.55,
        "limit",
        client="張文傑",
        account="0188102456",
    ),
    instr(
        "I5",
        "R5",
        "11:46",
        "2015",
        "1299",
        "友邦保險",
        "buy",
        2000,
        None,
        "market",
        client="吳詠欣",
        account="0188103999",
    ),
    # R6: clean instruction, never booked -> suspicious.
    instr(
        "I6",
        "R6",
        "14:21",
        "2020",
        "3690",
        "美團",
        "sell",
        15000,
        118.0,
        "limit",
        client="林志強",
        account="4777",
    ),
    # R8: ASR-garbled code (1318) but glossary name resolves 平安 -> 2318;
    # instructed 8,000 vs booked 6,000; no account spoken.
    instr(
        "I8",
        "R8",
        "15:10",
        "2015",
        "1318",
        "平安",
        "buy",
        8000,
        35.9,
        "limit",
        client="郭綺玲",
        account=None,
    ),
]


def run():
    return run_match(
        TXNS,
        INSTRS,
        zero_instr_recordings=["R7"],
        params=Params(),
        alias_map=ALIAS_MAP,
        broker_extensions=BROKER_EXTENSIONS,
    )


def test_buckets_match_golden_truth():
    result = run()
    by_txn = {m.txn_id: m for m in result.matched}

    auto = {t for t, m in by_txn.items() if m.status == "auto_matched"}
    review = {t for t, m in by_txn.items() if m.status == "needs_review"}
    assert auto == {"T1", "T2", "T3", "T4", "T5", "T6", "T7"}
    assert review == {"T8"}

    assert result.txn_no_recording == ["T9"]
    assert result.suspicious_instructions == ["I6"]
    assert result.info_recordings == ["R7"]
    assert result.stats["txns_excluded_channel"] == 2


def test_multi_trade_call_and_split_fill():
    result = run()
    by_txn = {m.txn_id: m for m in result.matched}
    # Multi-trade call: two different instructions, same recording.
    assert by_txn["T3"].recording_id == by_txn["T4"].recording_id == "R3"
    assert by_txn["T3"].instr_id != by_txn["T4"].instr_id
    # Split fill: both executions consume the SAME instruction.
    assert by_txn["T5"].instr_id == by_txn["T6"].instr_id == "I4"


def test_garbled_code_rescued_by_glossary_name():
    result = run()
    pair = next(m for m in result.matched if m.txn_id == "T8")
    assert pair.instr_id == "I8"
    assert pair.breakdown["components"]["stock"] == 1.0
    assert "name" in pair.breakdown["stock_note"]


def test_side_mismatch_disqualifies():
    original = next(t for t in TXNS if t.id == "T1")
    flipped = TxnView(**{**original.__dict__, "side": "sell"})
    result = run_match(
        [flipped],
        INSTRS,
        [],
        params=Params(),
        alias_map=ALIAS_MAP,
        broker_extensions=BROKER_EXTENSIONS,
    )
    assert not [m for m in result.matched if m.txn_id == "T1"]


def test_stock_conflict_with_four_strong_fields_is_review_only():
    transaction = txn("STOCK", "10:00", "AE012", "39984", "Client", "386", "sell", 20000, 4.67)
    instruction = instr(
        "BAD-STOCK",
        "R-STOCK",
        "09:59",
        "2012",
        "360",
        None,
        "sell",
        20000,
        4.67,
        "limit",
        account="39984",
    )
    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(),
        alias_map={},
        broker_extensions=BROKER_EXTENSIONS,
    )
    pair = result.matched[0]
    assert pair.status == "needs_review"
    assert pair.breakdown["hard_conflicts"] == ["stock"]
    assert len(pair.breakdown["high_agreement_fields"]) >= 4
    assert pair.breakdown["conflict_fields"][0] == {
        "field": "stock",
        "transaction": "386",
        "recording": "360",
    }


def test_replace_amend_broker_conflict_is_review_only():
    transaction = TxnView(
        id="REPLACE",
        anchor=hk("13:18"),
        broker_code=None,
        broker_name="Chanel Leung",
        client_account="39984",
        client_name=None,
        stock_code="386",
        stock_name=None,
        side="sell",
        quantity=20000,
        price=4.66,
        previous_price=4.67,
        channel="phone",
        action_type="replace",
    )
    instruction = InstrView(
        id="AMEND",
        recording_id="R-AMEND",
        call_started_at=hk("13:16"),
        call_duration_seconds=180,
        broker_ext=None,
        broker_name="Enson Chan",
        stock_code="386",
        stock_name_raw="386",
        side="amend",
        quantity=None,
        price=4.66,
        price_type="limit",
        client_name_raw=None,
        client_account_raw="39984",
        evidence_quote="386 from 4.67 to 4.66",
    )
    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(),
        alias_map={},
        broker_extensions={},
    )
    pair = result.matched[0]
    assert pair.status == "needs_review"
    assert pair.breakdown["amend_evidence"]["old_price_match"] is True
    assert "broker" in pair.breakdown["capped"]


def test_unmatched_reasons_distinguish_day_window_and_content():
    transactions = [
        txn("NO-DAY", "10:00", "AE012", "1", "A", "700", "buy", 1, 1),
        txn("NO-WINDOW", "10:00", "AE015", "2", "B", "700", "buy", 1, 1),
        txn("NO-MATCH", "10:00", "AE020", "3", "C", "700", "buy", 1, 1),
    ]
    recordings = [
        RecordingView("R-OLD", hk("01:00"), "2015", None, "old.wav"),
        RecordingView("R-NEAR", hk("09:59"), "2020", None, "near.wav"),
    ]
    result = run_match(
        transactions,
        [],
        [],
        params=Params(before_hours=2),
        alias_map={},
        broker_extensions=BROKER_EXTENSIONS,
        recording_contexts=recordings,
    )
    assert result.unmatched_reasons == {
        "NO-DAY": "no_broker_recordings_day",
        "NO-WINDOW": "no_recordings_in_window",
        "NO-MATCH": "no_matching_recording",
    }
    assert result.candidates["NO-MATCH"][0]["recording_id"] == "R-NEAR"


def test_transaction_filters_use_imported_order_metadata():
    class Txn:
        def __init__(self):
            self.raw = {"order_status": "已委託", "execution_type": "NewExec"}

    assert _passes_transaction_filters(
        Txn(),
        {
            "order_statuses": ["已委託", "成交"],
            "execution_types": ["NewExec", "TradeExec"],
        },
    )
    assert not _passes_transaction_filters(
        Txn(),
        {
            "order_statuses": ["成交"],
            "execution_types": ["NewExec", "TradeExec"],
        },
    )
    assert not _passes_transaction_filters(
        Txn(),
        {
            "order_statuses": ["已委託", "成交"],
            "execution_types": ["TradeExec"],
        },
    )
