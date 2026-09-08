from worker.tasks import pipeline
from worker.tasks.evaluate import _output_language_instruction


def test_apply_output_script_converts_simplified_to_hong_kong_traditional() -> None:
    assert pipeline._apply_output_script("客户买卖证券", "traditional") == "客戶買賣證券"


def test_apply_output_script_preserves_provider_output_when_disabled() -> None:
    assert pipeline._apply_output_script("客户买卖证券", "original") == "客户买卖证券"


def test_apply_output_script_tree_converts_nested_evaluation_text() -> None:
    value = {
        "summary": "客户买入证券",
        "criteria": [{"key": "clear", "rationale": "没有问题"}],
        "score": 5,
    }
    assert pipeline._apply_output_script_tree(value, "traditional") == {
        "summary": "客戶買入證券",
        "criteria": [{"key": "clear", "rationale": "沒有問題"}],
        "score": 5,
    }


def test_traditional_evaluation_requests_hong_kong_traditional_output() -> None:
    instruction = _output_language_instruction("traditional")

    assert "Traditional Chinese (Hong Kong)" in instruction
    assert _output_language_instruction("original") == ""
