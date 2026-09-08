from worker.tasks import pipeline


def test_apply_output_script_converts_simplified_to_hong_kong_traditional() -> None:
    assert pipeline._apply_output_script("客户买卖证券", "traditional") == "客戶買賣證券"


def test_apply_output_script_preserves_provider_output_when_disabled() -> None:
    assert pipeline._apply_output_script("客户买卖证券", "original") == "客户买卖证券"
