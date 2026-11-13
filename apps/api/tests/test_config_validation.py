import pytest
from app.routers.config import VALIDATORS, _v_correction_replacements


def test_correction_replacements_accept_contextual_rules() -> None:
    _v_correction_replacements(
        [{"wrong": "安撫", "correct": "富衛", "context": "opening greeting"}]
    )


def test_correction_replacements_reject_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        _v_correction_replacements(
            [{"wrong": "安撫", "correct": "富衛", "context": "greeting", "force": True}]
        )


def test_audio_review_setting_requires_boolean() -> None:
    validator = VALIDATORS["asr.audio_review_enabled"]
    validator(True)
    validator(False)
    with pytest.raises(ValueError):
        validator("true")
