from __future__ import annotations

import base64
import hashlib
import hmac

from worker.tasks.monitoring import EvaluatingIssue, _feishu_sign, _format_monitor_message


def test_feishu_sign_matches_custom_bot_algorithm() -> None:
    timestamp = "1700000000"
    secret = "test-secret"
    expected = base64.b64encode(
        hmac.new(f"{timestamp}\n{secret}".encode(), b"", hashlib.sha256).digest()
    ).decode("utf-8")

    assert _feishu_sign(timestamp, secret) == expected


def test_format_monitor_message_includes_affected_recordings() -> None:
    message = _format_monitor_message(
        total_evaluating=3,
        stale_seconds=1200,
        timeout_seconds=3600,
        issues=[
            EvaluatingIssue(
                recording_id="rid-1",
                filename="call.wav",
                batch_name="0513_Amy",
                age_minutes=25,
                updated_minutes=25,
                issue="stale running evaluation",
                error=None,
            )
        ],
    )

    assert "attention needed" in message
    assert "call.wav" in message
    assert "0513_Amy" in message
