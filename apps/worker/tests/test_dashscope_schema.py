from worker.llm.dashscope import _schema_hint
from worker.tasks.evaluate import build_trade_response_schema


def test_dashscope_schema_hint_contains_nested_trade_contract() -> None:
    hint = _schema_hint(build_trade_response_schema())

    assert "trade_instructions!" in hint
    assert "stock_code?" in hint
    assert "stock_name_raw?" in hint
    assert "price_type!" in hint
    assert "Do not rename keys" in hint
