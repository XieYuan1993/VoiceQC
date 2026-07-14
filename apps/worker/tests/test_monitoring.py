from __future__ import annotations

import base64
import hashlib
import hmac

from worker.tasks.monitoring import (
    EvaluatingMonitorSnapshot,
    _estimate_eta,
    _feishu_sign,
    _format_monitor_message,
)


def test_feishu_sign_matches_custom_bot_algorithm() -> None:
    timestamp = "1700000000"
    secret = "test-secret"
    expected = base64.b64encode(
        hmac.new(f"{timestamp}\n{secret}".encode(), b"", hashlib.sha256).digest()
    ).decode("utf-8")

    assert _feishu_sign(timestamp, secret) == expected


def test_format_monitor_message_summarizes_progress() -> None:
    message = _format_monitor_message(
        snapshot=EvaluatingMonitorSnapshot(
            queued=10,
            running=4,
            completed_recent=8,
            failed_recent=2,
            blocked=1,
            stale_queued=1,
            stale_running=0,
            timed_out=0,
        ),
        interval_seconds=1200,
    )

    assert "attention needed" in message
    assert "Queued: 10" in message
    assert "Running: 4" in message
    assert "Completed in last 20 min: 8" in message
    assert "Failed in last 20 min: 2" in message
    assert "ETA: ~28 min" in message


def test_eta_is_unknown_without_recent_throughput() -> None:
    eta = _estimate_eta(
        EvaluatingMonitorSnapshot(
            queued=3,
            running=1,
            completed_recent=0,
            failed_recent=0,
            blocked=0,
            stale_queued=0,
            stale_running=0,
            timed_out=0,
        ),
        interval_seconds=1200,
    )

    assert eta == "unknown (no recent throughput)"
