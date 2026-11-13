# ruff: noqa: RUF001

from worker import transcript_correction
from worker.transcript_correction import (
    TranscriptTurn,
    correct_project_transcript,
    correct_turns_with_llm,
)


class FakeAdapter:
    def __init__(self, parsed):
        self.parsed = parsed
        self.prompts: list[str] = []

    def generate_structured(self, prompt, response_schema, *, model, temperature=0.2):
        self.prompts.append(prompt)
        return self.parsed, 100, 40


def test_project_post_correction_is_opt_in(monkeypatch):
    monkeypatch.setattr(transcript_correction, "get_setting", lambda *a, **k: False)
    monkeypatch.setattr(
        transcript_correction,
        "_adapter",
        lambda *_args: (_ for _ in ()).throw(AssertionError("adapter should not be created")),
    )
    turns = [("broker", 1_000, "富衛保險你好，請問有甚麼可以幫到你？")]

    corrected, changed = correct_project_transcript(
        turns,
        session=object(),
        project_id="project-id",
    )

    assert changed is False
    assert corrected == turns


def test_corrects_hotword_and_repeated_identifier_without_changing_metadata(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    turns = [
        TranscriptTurn("broker", 1_000, "早晨，安撫，我係Anna"),
        TranscriptTurn("customer", 3_000, "保單號碼係123465"),
        TranscriptTurn("broker", 5_000, "確認保單號碼123456"),
        TranscriptTurn("customer", 7_000, "係，123456無錯"),
    ]
    adapter = FakeAdapter(
        {
            "turns": [
                {"id": 0, "text": "早晨，富衛，我係Anna", "numeric_evidence_ids": []},
                {
                    "id": 1,
                    "text": "保單號碼係123456",
                    "numeric_evidence_ids": [2, 3],
                },
            ]
        }
    )

    corrected, applied = correct_turns_with_llm(
        turns,
        adapter=adapter,
        model="test-model",
        glossary=[{"term": "富衛", "category": "jargon", "aliases": []}],
        replacements=[
            {"wrong": "安撫", "correct": "富衛", "context": "opening greeting"}
        ],
        session=object(),
        allow_numeric_changes=True,
    )

    assert applied is True
    assert corrected == [
        TranscriptTurn("broker", 1_000, "早晨，富衛，我係Anna"),
        TranscriptTurn("customer", 3_000, "保單號碼係123456"),
        TranscriptTurn("broker", 5_000, "確認保單號碼123456"),
        TranscriptTurn("customer", 7_000, "係，123456無錯"),
    ]
    assert "安撫" in adapter.prompts[0]
    assert "富衛" in adapter.prompts[0]


def test_rejects_numeric_change_without_supporting_turn(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    original = TranscriptTurn("customer", 3_000, "我個戶口係012345，麻煩你幫我查一查資料")
    adapter = FakeAdapter(
        {
            "turns": [
                {
                    "id": 0,
                    "text": "我個戶口係012346，麻煩你幫我查一查資料",
                    "numeric_evidence_ids": [],
                },
            ]
        }
    )

    corrected, applied = correct_turns_with_llm(
        [original],
        adapter=adapter,
        model="test-model",
        glossary=[],
        replacements=[],
        session=object(),
    )

    assert applied is False
    assert corrected == [original]


def test_rejects_numeric_change_with_only_one_supporting_turn(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    turns = [
        TranscriptTurn("customer", 1_000, "我個戶口係012345"),
        TranscriptTurn("broker", 2_000, "我聽到你講012346"),
    ]
    adapter = FakeAdapter(
        {
            "turns": [
                {
                    "id": 0,
                    "text": "我個戶口係012346",
                    "numeric_evidence_ids": [1],
                },
            ]
        }
    )

    corrected, applied = correct_turns_with_llm(
        turns,
        adapter=adapter,
        model="test-model",
        glossary=[],
        replacements=[],
        session=object(),
    )

    assert applied is False
    assert corrected == turns


def test_rejects_identifier_regrouping(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    original = TranscriptTurn("customer", 1_000, "麻煩你幫我查一查，保單號碼係9233901")
    adapter = FakeAdapter(
        {
            "turns": [
                {
                    "id": 0,
                    "text": "麻煩你幫我查一查，保單號碼係923390(1)",
                    "numeric_evidence_ids": [1, 2],
                }
            ]
        }
    )

    corrected, applied = correct_turns_with_llm(
        [original],
        adapter=adapter,
        model="test-model",
        glossary=[],
        replacements=[],
        session=object(),
    )

    assert applied is False
    assert corrected == [original]


def test_rejects_spoken_chinese_number_change(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    original = TranscriptTurn("customer", 1_000, "保單尾號係二三六零，麻煩你幫我查一查")
    adapter = FakeAdapter(
        {
            "turns": [
                {
                    "id": 0,
                    "text": "保單尾號係二三六一，麻煩你幫我查一查",
                    "numeric_evidence_ids": [],
                }
            ]
        }
    )

    corrected, applied = correct_turns_with_llm(
        [original],
        adapter=adapter,
        model="test-model",
        glossary=[],
        replacements=[],
        session=object(),
    )

    assert applied is False
    assert corrected == [original]


def test_rejects_large_paraphrase(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    original = TranscriptTurn(
        "customer",
        1_000,
        "我想查詢保單目前的狀況，麻煩你幫我核對一下資料",
    )
    adapter = FakeAdapter(
        {
            "turns": [
                {
                    "id": 0,
                    "text": "客戶要求立即取消所有服務並且退款，原因並不清楚",
                    "numeric_evidence_ids": [],
                }
            ]
        }
    )

    corrected, applied = correct_turns_with_llm(
        [original],
        adapter=adapter,
        model="test-model",
        glossary=[],
        replacements=[],
        session=object(),
    )

    assert applied is False
    assert corrected == [original]


def test_rejects_chunk_when_llm_returns_a_context_only_id(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    turns = [
        TranscriptTurn("broker", 1_000, "第一句需要保留完整"),
        TranscriptTurn("customer", 2_000, "第二句亦需要保留完整"),
    ]
    adapter = FakeAdapter(
        {
            "turns": [
                {"id": 99, "text": "不應出現的句子", "numeric_evidence_ids": []},
            ]
        }
    )

    corrected, applied = correct_turns_with_llm(
        turns,
        adapter=adapter,
        model="test-model",
        glossary=[],
        replacements=[],
        session=object(),
    )

    assert applied is False
    assert corrected == turns


def test_retries_one_transient_llm_failure(monkeypatch):
    monkeypatch.setattr(transcript_correction, "record_llm_usage_sync", lambda *a, **k: None)
    monkeypatch.setattr(transcript_correction.time, "sleep", lambda _seconds: None)

    class FlakyAdapter:
        calls = 0

        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("connection reset")
            return {"turns": []}, 10, 2

    adapter = FlakyAdapter()
    turns = [
        TranscriptTurn(
            "broker",
            1_000,
            "這是一句足夠長而且不需要修改的測試內容，用來確認連線失敗後會重試",
        )
    ]

    corrected, applied = correct_turns_with_llm(
        turns,
        adapter=adapter,
        model="test-model",
        glossary=[],
        replacements=[],
        session=object(),
    )

    assert applied is False
    assert corrected == turns
    assert adapter.calls == 2
