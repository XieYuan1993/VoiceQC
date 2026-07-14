from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from voiceqa_shared.db_models import Transaction
from worker.recon.engine import InstrView, Params, TxnView, run_match
from worker.tasks.recon import _transaction_action_views

HK = ZoneInfo("Asia/Hong_Kong")
D = "2026-06-11"
PRESET_CONDITION = "待報\uff08條件單\uff09"


def hk(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{D}T{hhmm}:00+08:00").astimezone(HK)


def order_row(
    row_id: str,
    order_id: str,
    at: str,
    status: str,
    execution_type: str,
    *,
    qty: int = 20000,
    info: str = "--",
    upstream: str = "HKEX",
) -> Transaction:
    return Transaction(
        id=row_id,
        import_id=row_id,
        ext_txn_id=order_id,
        trade_date=hk(at).date(),
        ordered_at=hk(at),
        executed_at=hk(at),
        broker_code="AE012",
        client_account="606248",
        client_name="Client",
        stock_code="6955",
        stock_name=None,
        side="sell",
        quantity=0 if execution_type == "NewExec" else qty,
        price=6.06,
        channel="phone",
        raw={
            "ext_txn_id": order_id,
            "order_status": status,
            "execution_type": execution_type,
            "order_quantity": str(qty),
            "order_price": "6.06",
            "broker_name": "Tony Chan",
            "info": info,
            "upstream_broker": upstream,
        },
    )


def test_reconciliation_uses_order_action_rows_not_trade_exec_fills() -> None:
    rows = [
        order_row("00000000-0000-0000-0000-000000000001", "A1", "10:00", "已委託", "NewExec"),
        order_row(
            "00000000-0000-0000-0000-000000000002",
            "A1",
            "10:05",
            "部分成交",
            "TradeExec",
            qty=2000,
        ),
        order_row("00000000-0000-0000-0000-000000000003", "A1", "10:06", "成交", "TradeExec"),
    ]

    views = _transaction_action_views(rows)

    assert [v.id for v in views] == ["00000000-0000-0000-0000-000000000001"]
    assert views[0].quantity == 20000
    assert views[0].action_type == "new"


def test_preset_order_matches_the_pending_record_not_later_newexec() -> None:
    rows = [
        order_row(
            "00000000-0000-0000-0000-000000000011",
            "A2",
            "09:30",
            PRESET_CONDITION,
            "",
        ),
        order_row("00000000-0000-0000-0000-000000000012", "A2", "14:00", "已委託", "NewExec"),
    ]

    views = _transaction_action_views(rows)

    assert [v.id for v in views] == ["00000000-0000-0000-0000-000000000011"]
    assert views[0].action_type == "preset"


def test_filters_do_not_turn_preset_newexec_into_manual_action() -> None:
    rows = [
        order_row(
            "00000000-0000-0000-0000-000000000031",
            "A5",
            "09:30",
            PRESET_CONDITION,
            "",
        ),
        order_row("00000000-0000-0000-0000-000000000032", "A5", "14:00", "已委託", "NewExec"),
    ]

    views = _transaction_action_views(rows, {"execution_types": ["NewExec"]})

    assert views == []


def test_system_generated_rows_are_excluded_from_reconciliation_scope() -> None:
    rows = [
        order_row(
            "00000000-0000-0000-0000-000000000021",
            "A3",
            "16:10",
            "已過期",
            "ExpiredExec",
            upstream="HKEX",
        ),
        order_row(
            "00000000-0000-0000-0000-000000000022",
            "A4",
            "13:52",
            "已拒絕",
            "RejectedExec",
            info="rms.limit_code.udss",
        ),
    ]

    assert _transaction_action_views(rows) == []


def test_call_may_precede_order_within_configured_window() -> None:
    transaction = TxnView(
        id="T-late",
        anchor=hk("10:10"),
        broker_code="AE012",
        client_account="0188",
        client_name="Client",
        stock_code="700",
        stock_name=None,
        side="buy",
        quantity=100,
        price=10,
        channel="phone",
    )
    instruction = InstrView(
        id="I-late",
        recording_id="R-late",
        call_started_at=hk("10:00"),
        call_duration_seconds=120,
        broker_ext="2012",
        stock_code="700",
        stock_name_raw=None,
        side="buy",
        quantity=100,
        price=10,
        price_type="limit",
        client_name_raw=None,
        client_account_raw=None,
    )

    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(after_minutes=3),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )

    assert len(result.matched) == 1


def test_call_outside_configured_window_is_scored_by_default() -> None:
    transaction = TxnView(
        id="T-window",
        anchor=hk("16:30"),
        broker_code="AE012",
        client_account="0188",
        client_name="Client",
        stock_code="700",
        stock_name=None,
        side="buy",
        quantity=100,
        price=10,
        channel="phone",
    )
    instruction = InstrView(
        id="I-window",
        recording_id="R-window",
        call_started_at=hk("10:00"),
        call_duration_seconds=120,
        broker_ext="2012",
        stock_code="700",
        stock_name_raw=None,
        side="buy",
        quantity=100,
        price=10,
        price_type="limit",
        client_name_raw=None,
        client_account_raw=None,
    )

    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(before_hours=6, after_minutes=15),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )

    assert len(result.matched) == 1
    assert result.matched[0].breakdown["components"]["time"] == 0.2

    legacy_result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(
            before_hours=6,
            after_minutes=15,
            enforce_candidate_time_window=True,
        ),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )
    assert legacy_result.matched == []


def test_us_ticker_uses_extended_before_window() -> None:
    transaction = TxnView(
        id="T-us-window",
        anchor=hk("23:30"),
        broker_code="AE012",
        client_account="0188",
        client_name="Client",
        stock_code="RKLB",
        stock_name=None,
        side="buy",
        quantity=100,
        price=10,
        channel="phone",
    )
    instruction = InstrView(
        id="I-us-window",
        recording_id="R-us-window",
        call_started_at=hk("10:00"),
        call_duration_seconds=120,
        broker_ext="2012",
        stock_code="RKLB",
        stock_name_raw=None,
        side="buy",
        quantity=100,
        price=10,
        price_type="limit",
        client_name_raw=None,
        client_account_raw=None,
    )

    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(before_hours=6, us_before_hours=18, after_minutes=15),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )

    assert len(result.matched) == 1
    assert result.matched[0].breakdown["window_before_hours"] == 18


def test_broker_full_name_can_rescue_extension_mismatch() -> None:
    transaction = TxnView(
        id="T-name",
        anchor=hk("10:02"),
        broker_code="AE012",
        client_account="0188",
        client_name="Client",
        stock_code="700",
        stock_name=None,
        side="buy",
        quantity=100,
        price=10,
        channel="phone",
        broker_name="Ting Shu Fai",
    )
    instruction = InstrView(
        id="I-name",
        recording_id="R-name",
        call_started_at=hk("10:00"),
        call_duration_seconds=120,
        broker_ext="9999",
        stock_code="700",
        stock_name_raw=None,
        side="buy",
        quantity=100,
        price=10,
        price_type="limit",
        client_name_raw=None,
        client_account_raw=None,
        broker_name="Shufai Ting",
    )

    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(after_minutes=3),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )

    assert len(result.matched) == 1
    assert result.matched[0].breakdown["broker_name_match"] is True


def test_close_broker_romanisation_is_accepted() -> None:
    transaction = TxnView(
        id="T-romanisation",
        anchor=hk("10:02"),
        broker_code="QUAMIB",
        client_account="0188",
        client_name="Client",
        stock_code="700",
        stock_name=None,
        side="buy",
        quantity=100,
        price=10,
        channel="phone",
        broker_name="Paul Leng",
    )
    instruction = InstrView(
        id="I-romanisation",
        recording_id="R-romanisation",
        call_started_at=hk("10:00"),
        call_duration_seconds=120,
        broker_ext="9999",
        stock_code="700",
        stock_name_raw=None,
        side="buy",
        quantity=100,
        price=10,
        price_type="limit",
        client_name_raw=None,
        client_account_raw=None,
        broker_name="Paul Leung",
    )

    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(),
        alias_map={},
        broker_extensions={},
    )

    assert len(result.matched) == 1
    assert result.matched[0].breakdown["broker_name_match"] is True


def test_same_chinese_broker_name_is_accepted() -> None:
    transaction = TxnView(
        id="T-chinese-name",
        anchor=hk("10:02"),
        broker_code="QUAMIB",
        client_account="0188",
        client_name="Client",
        stock_code="700",
        stock_name=None,
        side="buy",
        quantity=100,
        price=10,
        channel="phone",
        broker_name="陳大文",
    )
    instruction = InstrView(
        id="I-chinese-name",
        recording_id="R-chinese-name",
        call_started_at=hk("10:00"),
        call_duration_seconds=120,
        broker_ext="9999",
        stock_code="700",
        stock_name_raw=None,
        side="buy",
        quantity=100,
        price=10,
        price_type="limit",
        client_name_raw=None,
        client_account_raw=None,
        broker_name="陳大文",
    )

    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(),
        alias_map={},
        broker_extensions={},
    )

    assert len(result.matched) == 1
    assert result.matched[0].breakdown["broker_name_match"] is True


def test_numeric_broker_metadata_is_treated_as_unknown() -> None:
    transaction = TxnView(
        id="T-numeric-name",
        anchor=hk("10:02"),
        broker_code="QUAMIB",
        client_account="0188",
        client_name="Client",
        stock_code="700",
        stock_name=None,
        side="buy",
        quantity=100,
        price=10,
        channel="phone",
        broker_name="Chanel Leung",
    )
    instruction = InstrView(
        id="I-numeric-name",
        recording_id="R-numeric-name",
        call_started_at=hk("10:00"),
        call_duration_seconds=120,
        broker_ext="9292",
        stock_code="700",
        stock_name_raw=None,
        side="buy",
        quantity=100,
        price=10,
        price_type="limit",
        client_name_raw=None,
        client_account_raw=None,
        broker_name="9292",
    )

    result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(),
        alias_map={},
        broker_extensions={},
    )

    assert len(result.matched) == 1
    assert result.matched[0].breakdown["broker_name_match"] is False
    assert result.matched[0].breakdown["penalty"]
