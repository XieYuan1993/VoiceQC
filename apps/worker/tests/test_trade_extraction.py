from datetime import UTC, datetime
from types import SimpleNamespace

from worker.tasks.evaluate import (
    _add_evaluation_summary_hint,
    _merge_trade_outputs,
    _normalize_stock_code,
    _prior_trade_context,
    _six_digit_account,
    _trade_chunks,
    build_trade_prompt,
    build_trade_response_schema,
)
from worker.trade_normalization import normalize_trade_item, recover_stock_code


def test_trade_stock_normalization_preserves_us_tickers() -> None:
    assert _normalize_stock_code("00700") == "700"
    assert _normalize_stock_code("nvda") == "NVDA"
    assert _normalize_stock_code("BRK.B") == "BRK.B"


def test_long_trade_transcript_is_chunked_with_overlap() -> None:
    text = "\n".join(f"[{index:02d}:00] broker: line {index}" for index in range(12))

    chunks = _trade_chunks(text, max_chars=100)

    assert len(chunks) > 1
    assert set(chunks[0].splitlines()[-2:]) <= set(chunks[1].splitlines())


def test_six_digit_account_prefers_account_label_then_call_opening() -> None:
    assert _six_digit_account("[00:03] broker: \u6236\u53e3 606 248, confirm") == "606248"
    assert (
        _six_digit_account("[00:01] customer: 123456 [00:20] broker: buy 100000 shares") == "123456"
    )
    assert _six_digit_account("[00:01] broker: phone 91234567") is None


def test_prior_call_prompt_is_context_only_for_same_account() -> None:
    rec = SimpleNamespace(
        call_started_at=None,
        broker_name="Broker",
        broker_ext="2012",
    )
    prompt = build_trade_prompt(
        rec,
        "[00:10] customer: make it 18 dollars",
        [],
        [],
        chunk_index=1,
        chunk_count=1,
        account_hint="606248",
        prior_context="[Prior call] discussed stock 688",
    )

    assert "verified client account hint: 606248" in prompt
    assert "Never extract or repeat an instruction that appears only in an earlier call" in prompt
    assert "inherit the stock only from the same-account context" in prompt


def test_prior_call_context_uses_existing_transcript_while_bulk_reevaluating() -> None:
    current = SimpleNamespace(
        id="current",
        project_id="project",
        call_started_at=datetime(2026, 5, 13, 10, 20, tzinfo=UTC),
        broker_ext="2012",
        broker_name="Broker",
    )
    prior = SimpleNamespace(
        id="prior",
        status="evaluating",
        call_started_at=datetime(2026, 5, 13, 10, 5, tzinfo=UTC),
        client_account=None,
    )
    transcript = SimpleNamespace(full_text="[00:02] broker: account 606248, stock 688")

    class Result:
        def all(self):
            return [(prior, transcript)]

    class Session:
        def execute(self, _statement):
            return Result()

    context = _prior_trade_context(Session(), current, "606248")

    assert context is not None
    assert "account 606248" in context
    assert "stock 688" in context


def test_evaluation_summary_only_recovers_fields_for_current_instruction() -> None:
    prompt = _add_evaluation_summary_hint(
        "CURRENT call contains an existing instruction",
        "The client instructed a sale of 2,000 shares at 6.06.",
    )

    assert "secondary, model-generated hint" in prompt
    assert "Never create an instruction solely from the summary" in prompt
    assert "cap that instruction's confidence at 0.65" in prompt


def test_trade_chunk_outputs_are_merged_and_deduplicated() -> None:
    instruction = {
        "stock_code": "NVDA",
        "stock_name_raw": None,
        "side": "buy",
        "quantity": 100,
        "price": 150,
        "price_type": "limit",
        "time_in_call_ms": 10_000,
        "confidence": 0.9,
        "evidence_quote": "buy one hundred NVDA",
    }

    overlapping_copy = {**instruction, "evidence_quote": "buy 100 NVDA"}
    merged = _merge_trade_outputs(
        [
            {"caller": {"name": "Client", "account": "888"}, "trade_instructions": [instruction]},
            {
                "caller": {"name": None, "account": None},
                "trade_instructions": [overlapping_copy],
            },
        ]
    )

    assert merged["caller"] == {"name": "Client", "account": "888"}
    assert merged["trade_instructions"] == [instruction]


def test_dedicated_trade_schema_is_small_and_trade_only() -> None:
    schema = build_trade_response_schema()

    assert set(schema["properties"]) == {"caller", "trade_instructions"}
    assert schema["required"] == ["caller", "trade_instructions"]


def test_provider_aliases_are_normalized_to_canonical_trade_fields() -> None:
    item = normalize_trade_item(
        {
            "security": {"code": "HK0697", "name": "首程控股"},
            "qty": 50_000,
            "order_type": "market price",
            "customer_name": "張生",
            "timestamp_ms": 12_000,
            "evidence": "HK 0697 market 沽5萬股",
        }
    )

    assert item["stock_code"] == "697"
    assert item["stock_name_raw"] == "首程控股"
    assert item["quantity"] == 50_000
    assert item["price_type"] == "market"
    assert item["client_name_raw"] == "張生"
    assert item["time_in_call_ms"] == 12_000


def test_stock_is_recovered_only_from_one_explicit_candidate() -> None:
    candidates = [
        ("4", "九龍倉集團"),
        ("2338", "濰柴動力"),
        ("2899", "紫金礦業"),
        ("2000", "晨訊科技"),
    ]

    assert recover_stock_code("2338 market沽6000股", candidates, quantity=6000) == "2338"
    assert recover_stock_code("market買2000股", candidates, quantity=2000) is None
    assert recover_stock_code("2338同2899都睇下", candidates) is None
    assert recover_stock_code("排兩個4, 做到為止", candidates) is None
    assert recover_stock_code("股票 HK 00004 沽1000股", candidates, quantity=1000) == "4"
