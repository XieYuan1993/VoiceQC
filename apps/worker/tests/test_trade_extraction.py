from worker.tasks.evaluate import (
    _merge_trade_outputs,
    _normalize_stock_code,
    _trade_chunks,
    build_trade_response_schema,
)


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
