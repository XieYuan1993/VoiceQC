from worker import audio_review


def segment(text="Policy 12345678", start=1000):
    return {
        "role": "customer",
        "start_ms": start,
        "end_ms": start + 2000,
        "text": text,
        "confidence": 0.5,
    }


def test_disabled_does_not_load_audio(monkeypatch):
    monkeypatch.setattr(audio_review, "get_setting", lambda *args: False)
    original = [segment()]
    assert audio_review.review_project_audio(original, files=[], session=None, project_id=None) == (
        original,
        None,
    )


def test_numeric_conflict_preserves_original(monkeypatch):
    monkeypatch.setattr(
        audio_review,
        "hear_clip",
        lambda *args, **kwargs: ({"text": "Policy 12345679", "uncertain": False}, {}),
    )
    original = [segment()]
    reviewed, evidence = audio_review.review_segments(
        original, clip_loader=lambda *args: b"wav", glossary=[], replacements=[]
    )
    assert reviewed == original
    assert evidence[0]["reason"] == "numeric_conflict"
    assert evidence[0]["suggested_text"] == "Policy 12345679"


def test_text_only_correction_preserves_timing(monkeypatch):
    monkeypatch.setattr(
        audio_review,
        "hear_clip",
        lambda *args, **kwargs: (
            {"text": "Please check the policy details today", "uncertain": False},
            {},
        ),
    )
    original = [segment("Please check the polisy details today")]
    reviewed, evidence = audio_review.review_segments(
        original, clip_loader=lambda *args: b"wav", glossary=[], replacements=[]
    )
    assert reviewed == original
    assert evidence[0]["status"] == "needs_review"


def test_failure_is_nonfatal(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(audio_review, "hear_clip", fail)
    original = [segment()]
    reviewed, evidence = audio_review.review_segments(
        original, clip_loader=lambda *args: b"wav", glossary=[], replacements=[]
    )
    assert reviewed == original
    assert evidence[0]["status"] == "failed"


def test_selection_is_bounded_and_spaced():
    segments = [segment(start=index * 10000) for index in range(10)]
    assert len(audio_review.select_targets(segments, [])) == 3


def test_uncertain_candidate_is_not_applied(monkeypatch):
    monkeypatch.setattr(
        audio_review,
        "hear_clip",
        lambda *args, **kwargs: ({"text": "Policy 12345678", "uncertain": True}, {}),
    )
    original = [segment()]
    reviewed, evidence = audio_review.review_segments(
        original, clip_loader=lambda *args: b"wav", glossary=[], replacements=[]
    )
    assert reviewed == original
    assert evidence[0]["reason"] == "uncertain"


def test_chinese_text_difference_remains_advisory(monkeypatch):
    monkeypatch.setattr(
        audio_review,
        "hear_clip",
        lambda *args, **kwargs: ({"text": "富衛保險你好", "uncertain": False}, {}),
    )
    original = [segment("安富保險你好")]
    reviewed, evidence = audio_review.review_segments(
        original, clip_loader=lambda *args: b"wav", glossary=[], replacements=[]
    )
    assert reviewed == original
    assert evidence[0]["reason"] == "text_difference"


def test_deadline_skips_requests(monkeypatch):
    monkeypatch.setattr(audio_review, "TOTAL_SECONDS", 0)

    def fail(*args, **kwargs):
        raise AssertionError("audio must not be loaded")

    original = [segment()]
    reviewed, evidence = audio_review.review_segments(
        original, clip_loader=fail, glossary=[], replacements=[]
    )
    assert reviewed == original
    assert evidence[0]["reason"] == "deadline"
