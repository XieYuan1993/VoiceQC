from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from voiceqa_shared.db_models import TradeInstruction, Transaction
from voiceqa_shared.recon_scope import recon_action_for_status
from worker.recon.engine import InstrView, Params, TxnView, run_match
from worker.tasks.recon import _is_match_eligible_instruction, _transaction_action_views

HK = ZoneInfo("Asia/Hong_Kong")
D = "2026-06-11"


def test_only_order_interactions_are_match_eligible() -> None:
    assert _is_match_eligible_instruction(TradeInstruction(extra_fields={}))
    assert _is_match_eligible_instruction(
        TradeInstruction(extra_fields={"interaction_type": "order_instruction"})
    )
    assert not _is_match_eligible_instruction(
        TradeInstruction(extra_fields={"interaction_type": "notification"})
    )
    assert not _is_match_eligible_instruction(
        TradeInstruction(extra_fields={"interaction_type": "inquiry"})
    )
PRESET_CONDITION = "待報\uff08條件單\uff09"


def test_reconciliation_status_aliases_include_rejected_not_expired() -> None:
    assert recon_action_for_status("\u5df2\u62d2\u7d55") == "new"
    assert recon_action_for_status("\u5df2\u62d2\u7edd") == "new"
    assert recon_action_for_status("\u5df2\u904e\u671f") is None
    assert recon_action_for_status("\u5df2\u8fc7\u671f") is None


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


def _legacy_test_reconciliation_uses_order_action_rows_not_trade_exec_fills() -> None:
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


def test_transaction_is_scoped_by_normalized_hkt_action_date() -> None:
    shifted = order_row(
        "00000000-0000-0000-0000-000000000099",
        "ET-SHIFT",
        "23:00",
        "\u5df2\u59d4\u8a17",
        "NewExec",
    )
    shifted.trade_date = date(2026, 6, 11)
    shifted.ordered_at = datetime(2026, 6, 12, 4, 0, tzinfo=HK)
    shifted.executed_at = shifted.ordered_at

    original_day = _transaction_action_views(
        [shifted],
        trade_date_from=date(2026, 6, 11),
        trade_date_to=date(2026, 6, 11),
    )
    normalized_day = _transaction_action_views(
        [shifted],
        trade_date_from=date(2026, 6, 12),
        trade_date_to=date(2026, 6, 12),
    )

    assert original_day == []
    assert [view.id for view in normalized_day] == [str(shifted.id)]


def test_preloaded_previous_day_without_action_time_does_not_leak() -> None:
    undated = order_row(
        "00000000-0000-0000-0000-000000000098",
        "NO-TIME",
        "23:00",
        "\u5df2\u59d4\u8a17",
        "NewExec",
    )
    undated.trade_date = date(2026, 6, 11)
    undated.ordered_at = None
    undated.executed_at = None

    views = _transaction_action_views(
        [undated],
        trade_date_from=date(2026, 6, 12),
        trade_date_to=date(2026, 6, 12),
    )

    assert views == []


def _legacy_test_preset_order_matches_the_pending_record_not_later_newexec() -> None:
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


def _legacy_test_filters_do_not_turn_preset_newexec_into_manual_action() -> None:
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


def _legacy_test_system_generated_rows_are_excluded_from_reconciliation_scope() -> None:
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


def test_reconciliation_scope_uses_only_fixed_order_statuses() -> None:
    allowed = [
        order_row(
            "00000000-0000-0000-0000-000000000041",
            "S1",
            "10:00",
            "\u5df2\u59d4\u8a17",
            "TradeExec",
        ),
        order_row(
            "00000000-0000-0000-0000-000000000042",
            "S2",
            "10:01",
            "\u5df2\u4fee\u6539",
            "",
        ),
        order_row(
            "00000000-0000-0000-0000-000000000043",
            "S3",
            "10:02",
            "\u5df2\u62d2\u7d55",
            "RejectedExec",
        ),
        order_row(
            "00000000-0000-0000-0000-000000000044",
            "S4",
            "10:03",
            "\u5df2\u64a4\u55ae",
            "NewExec",
        ),
    ]
    excluded = [
        order_row(
            "00000000-0000-0000-0000-000000000045",
            "S5",
            "10:04",
            "\u6210\u4ea4",
            "NewExec",
        ),
        order_row(
            "00000000-0000-0000-0000-000000000046",
            "S6",
            "10:05",
            "\u90e8\u5206\u6210\u4ea4",
            "ReplaceExec",
        ),
        order_row(
            "00000000-0000-0000-0000-000000000047",
            "S7",
            "10:06",
            "\u5df2\u904e\u671f",
            "ExpiredExec",
        ),
        order_row(
            "00000000-0000-0000-0000-000000000048",
            "S8",
            "10:07",
            PRESET_CONDITION,
            "",
        ),
    ]

    views = _transaction_action_views(
        [*allowed, *excluded],
        {"order_statuses": [], "execution_types": []},
    )

    assert [view.id for view in views] == [str(row.id) for row in allowed]
    assert [view.action_type for view in views] == ["new", "replace", "new", "cancel"]


def test_call_may_precede_order_within_configured_window() -> None:
    transaction = TxnView(
        id="T-late",
        anchor=hk("10:04"),
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
        params=Params(post_call_seconds=180),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )

    assert len(result.matched) == 1


def test_call_outside_pdf_window_is_review_only_when_content_is_strong() -> None:
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
    assert result.matched[0].status == "needs_review"
    assert "outside PDF D1" in result.matched[0].breakdown["capped"]

    score_only_result = run_match(
        [transaction],
        [instruction],
        [],
        params=Params(
            before_hours=6,
            after_minutes=15,
            enforce_candidate_time_window=False,
        ),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )
    assert len(score_only_result.matched) == 1
    assert score_only_result.matched[0].breakdown["components"]["time"] == 0.0


def test_us_ticker_outside_pdf_window_is_never_auto_matched() -> None:
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
    assert result.matched[0].status == "needs_review"


def test_pdf_window_includes_exactly_180_seconds_after_call_end() -> None:
    instruction = InstrView(
        id="I-boundary",
        recording_id="R-boundary",
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

    def transaction(tid: str, anchor: str) -> TxnView:
        return TxnView(
            id=tid,
            anchor=hk(anchor),
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

    at_boundary = run_match(
        [transaction("T-boundary", "10:05")],
        [instruction],
        [],
        params=Params(post_call_seconds=180),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )
    fractional_boundary = transaction("T-fractional-boundary", "10:05")
    fractional_boundary.anchor += timedelta(seconds=29, milliseconds=500)
    within_grace = run_match(
        [fractional_boundary],
        [instruction],
        [],
        params=Params(post_call_seconds=180),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )
    outside = run_match(
        [transaction("T-outside", "10:06")],
        [instruction],
        [],
        params=Params(post_call_seconds=180),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )

    assert len(at_boundary.matched) == 1
    assert at_boundary.matched[0].breakdown["components"]["time"] == 0.5
    assert len(within_grace.matched) == 1
    assert within_grace.matched[0].breakdown["components"]["time"] == 0.5
    assert "outside PDF D1" not in (within_grace.matched[0].breakdown.get("capped") or "")
    assert len(outside.matched) == 1
    assert outside.matched[0].status == "needs_review"

    next_day = transaction("T-next-day", "10:01")
    next_day.anchor += timedelta(days=1)
    cross_day = run_match(
        [next_day],
        [instruction],
        [],
        params=Params(post_call_seconds=180),
        alias_map={},
        broker_extensions={"AE012": {"2012"}},
    )
    assert cross_day.matched == []


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
