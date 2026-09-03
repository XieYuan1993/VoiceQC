from dataclasses import dataclass

from worker.tasks.pipeline import _collapse_duplicate_role_channels


@dataclass
class Segment:
    text: str


def test_duplicate_role_channels_are_collapsed_to_mixed() -> None:
    broker = [Segment("Welcome, account 123456"), Segment("Buy 700 at market")]
    customer = [Segment("Welcome, account 123456"), Segment("Buy 700 at market")]

    collapsed, duplicate = _collapse_duplicate_role_channels(
        [("broker", segment) for segment in broker]
        + [("customer", segment) for segment in customer]
    )

    assert duplicate is True
    assert collapsed == [("mixed", segment) for segment in broker]


def test_distinct_role_channels_are_preserved() -> None:
    segments = [
        ("broker", Segment("Welcome, please verify your account number")),
        ("customer", Segment("My account is 123456 and I want to buy Tencent")),
    ]

    collapsed, duplicate = _collapse_duplicate_role_channels(segments)

    assert duplicate is False
    assert collapsed == segments
