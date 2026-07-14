from worker.tasks.evaluate import (
    _merge_trade_outputs,
    _normalize_stock_code,
    _trade_chunks,
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
