from worker import mono_speaker_repair


class FakeAdapter:
    def __init__(self, parsed):
        self.parsed = parsed

    def generate_structured(self, prompt, response_schema, *, model, temperature=0.2):
        return self.parsed, 10, 5


class FakeSession:
    def execute(self, stmt):
        return None

    def commit(self):
        return None


def test_repair_mono_transcript_labels_roles(monkeypatch):
    monkeypatch.setattr(
        mono_speaker_repair,
        "_adapter",
        lambda: FakeAdapter(
            {
                "turns": [
                    {"timestamp": "00:01", "speaker": "broker", "text": "請問戶口號碼"},
                    {"timestamp": "00:03", "speaker": "customer", "text": "我想買入700"},
                ]
            }
        ),
    )
    monkeypatch.setattr(mono_speaker_repair, "record_llm_usage_sync", lambda *a, **k: None)

    repaired = mono_speaker_repair.repair_mono_transcript(
        "[00:01] mixed: 請問戶口號碼\n[00:03] mixed: 我想買入700",
        model="test-model",
        session=FakeSession(),
    )

    assert repaired == "[00:01] broker: 請問戶口號碼\n[00:03] customer: 我想買入700"


def test_repair_mono_transcript_keeps_original_on_failure(monkeypatch):
    class BrokenAdapter:
        def generate_structured(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(mono_speaker_repair, "_adapter", lambda: BrokenAdapter())

    original = "[00:01] mixed: 測試"
    assert (
        mono_speaker_repair.repair_mono_transcript(
            original, model="test-model", session=FakeSession()
        )
        == original
    )
