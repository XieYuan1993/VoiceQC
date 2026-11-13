# ruff: noqa: RUF001
import pytest
from worker import transcript_correction as correction
from worker.transcript_correction import TranscriptTurn, _repair_greeting_term

GLOSSARY = [{"term": "富衛"}, {"term": "富衛保險"}]
RULES = [{"wrong": "安富", "correct": "富衛", "context": "opening greeting"}]


def test_brand_artifact_can_remove_false_digit_without_changing_real_numbers(monkeypatch):
    monkeypatch.setattr(correction, "record_llm_usage_sync", lambda *a, **k: None)
    original = "5萬份保險，我叫Kelly，請問有甚麼可以幫到你？保單01234567，金額500。"

    class Adapter:
        def generate_structured(self, *args, **kwargs):
            return (
                {
                    "turns": [
                        {
                            "id": 0,
                            "text": "富衛保險，我叫Kelly，請問有甚麼可以幫到你？保單11234567，金額600。",
                            "numeric_evidence_ids": [],
                        }
                    ]
                },
                1,
                1,
            )

    turns = [TranscriptTurn("broker", 108000, original)]
    result, changed = correction.correct_turns_with_llm(
        turns,
        adapter=Adapter(),
        model="test",
        glossary=GLOSSARY,
        replacements=RULES,
        session=None,
    )
    assert changed
    assert result[0].text == original.replace("5萬份保險", "富衛保險")
    assert result[0].role == "broker"
    assert result[0].start_ms == 108000


@pytest.mark.parametrize(
    "role,text,glossary,rules,candidate",
    [
        (
            "customer",
            "5萬份保險，我叫Kelly，請問有甚麼可以幫到你？",
            GLOSSARY,
            RULES,
            "富衛保險，我叫Kelly，請問有甚麼可以幫到你？",
        ),
        (
            "broker",
            "保單有5萬份保險，我叫Kelly，請問有甚麼可以幫到你？",
            GLOSSARY,
            RULES,
            "富衛保險，我叫Kelly，請問有甚麼可以幫到你？",
        ),
        (
            "broker",
            "5萬份保險，我叫Kelly，請問有甚麼可以幫到你？",
            [],
            RULES,
            "富衛保險，我叫Kelly，請問有甚麼可以幫到你？",
        ),
        (
            "broker",
            "5萬份保險，我叫Kelly，請問有甚麼可以幫到你？",
            GLOSSARY,
            [],
            "富衛保險，我叫Kelly，請問有甚麼可以幫到你？",
        ),
        ("broker", "5萬份保險，保單01234567。", GLOSSARY, RULES, "富衛保險，保單01234567。"),
        (
            "broker",
            "5萬份保險，我叫Kelly，請問有甚麼可以幫到你？",
            GLOSSARY,
            RULES,
            "平安保險，我叫Kelly，請問有甚麼可以幫到你？",
        ),
        (
            "broker",
            "未知公司，我叫Kelly，請問有甚麼可以幫到你？",
            GLOSSARY,
            RULES,
            "富衛保險，我叫Kelly，請問有甚麼可以幫到你？",
        ),
    ],
)
def test_unapproved_or_non_greeting_context_is_unchanged(role, text, glossary, rules, candidate):
    assert _repair_greeting_term(TranscriptTurn(role, 0, text), candidate, glossary, rules) == text


def test_approved_term_only_leaves_rest_of_sentence_verbatim():
    text = "早晨，安富，我係Kelly，請問有咩可以幫到你？"
    candidate = "早晨，富衛，我係Kelly，請問有甚麼可以幫到您？"
    assert _repair_greeting_term(
        TranscriptTurn("broker", 0, text), candidate, GLOSSARY, RULES
    ) == text.replace("安富", "富衛")
