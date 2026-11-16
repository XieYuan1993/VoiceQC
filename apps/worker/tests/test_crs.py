from types import SimpleNamespace

import pytest
from voiceqa_shared.crs import catalogue, uses_crs
from worker.crs import build_crs_request, validate_crs


def event(**updates):
    return {
        "taxonomy_id": 1,
        "enquiry": "查詢理賠進度",
        "reason": catalogue()["reasons"][0],
        "rationale": "客戶要求跟進理賠。",
        "evidence_quote": "我想查理賠進度",
        **updates,
    }


def test_routing_does_not_change_quam_or_other_projects():
    assert uses_crs(SimpleNamespace(slug="fwd-insurance-demo", modules={}))
    assert uses_crs(SimpleNamespace(slug="other", modules={"crs_classification": True}))
    assert not uses_crs(
        SimpleNamespace(slug="quam-securities", modules={"trade_reconciliation": True})
    )
    assert not uses_crs(None)


def test_catalogue_and_whole_transcript_contract():
    assert len(catalogue()["entries"]) == 20
    prompt, schema = build_crs_request("開始\n" + "中間內容" * 5000 + "\n結尾問題")
    assert "結尾問題" in prompt and "開始" in prompt
    assert schema["required"] == ["events"]
    assert "criteria" not in schema["properties"]


def test_multiple_enquiries_use_canonical_labels_and_keep_uncertainty():
    parsed = validate_crs(
        {"events": [event(), event(taxonomy_id=0, reason="待確認", evidence_quote="unknown")]},
        "我想查理賠進度",
    )
    assert len(parsed["events"]) == 2
    assert parsed["events"][0]["category"] == catalogue()["entries"][0]["category"]
    assert parsed["events"][0]["evidence_verified"]
    assert parsed["events"][1]["needs_review"]
    assert parsed["events"][1]["category"] == "待確認"


@pytest.mark.parametrize(
    "payload",
    [
        {"events": []},
        {"events": [event(taxonomy_id=999)]},
        {"events": [event(reason="invented")]},
        {"events": [event(evidence_quote="")]},
        {"events": [event(taxonomy_id=True)]},
    ],
)
def test_invalid_model_output_rejected(payload):
    with pytest.raises(ValueError):
        validate_crs(payload, "我想查理賠進度")


def test_worker_crs_path_saves_result_without_quality_scoring(monkeypatch):
    import uuid

    from voiceqa_shared.db_models import Evaluation, Project, Recording, Transcript
    from worker.tasks import batch, evaluate

    project = Project(
        id=uuid.uuid4(), slug="fwd-insurance-demo", modules={"transcription_only": True}
    )
    rec = Recording(
        id=uuid.uuid4(),
        project_id=project.id,
        batch_id=uuid.uuid4(),
        status="evaluating",
        original_filename="demo.wav",
    )
    transcript = Transcript(recording_id=rec.id, full_text="我想查理賠進度")
    evaluations = []
    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, model, key):
            if model is Recording:
                return rec
            if model is Project:
                return project
            if model is Evaluation:
                return evaluations[0]

        def execute(self, statement):
            return SimpleNamespace(
                scalar_one_or_none=lambda: (
                    transcript if "FROM transcripts" in str(statement) else None
                ),
                scalars=lambda: SimpleNamespace(all=lambda: []),
            )

        def add(self, value):
            if isinstance(value, Evaluation):
                value.id = uuid.uuid4()
                evaluations.append(value)

        def commit(self):
            pass

    class Adapter:
        def generate_structured(self, prompt, schema, **kwargs):
            calls.append(schema)
            assert schema["required"] == ["events"]
            return {"events": [event()]}, 100, 50

    monkeypatch.setattr(evaluate, "SessionLocal", Session)
    monkeypatch.setattr(evaluate, "get_setting", lambda session, pid, key, default: default)
    monkeypatch.setattr(evaluate, "llm_tokens_today_sync", lambda session: 0)
    monkeypatch.setattr(evaluate, "record_llm_usage_sync", lambda *args, **kwargs: None)
    monkeypatch.setattr(evaluate, "_adapter", lambda: Adapter())
    monkeypatch.setattr(batch.update_progress, "delay", lambda *args: None)
    evaluate._evaluate_locked(SimpleNamespace(), str(rec.id))
    assert len(calls) == 1
    assert rec.status == "completed"
    assert evaluations[0].overall_score is None
    assert evaluations[0].criteria_snapshot == []
    assert evaluations[0].extracted_call_fields["crs"]["events"][0]["evidence_verified"]
