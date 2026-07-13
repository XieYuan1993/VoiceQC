from datetime import datetime

from worker.tasks.ingest import (
    HK,
    _apply_txt_metadata,
    _match_metadata_for_audio,
    _metadata_key_from_start,
    _parse_call_export_text,
)

TXT = """Call Export
===========

Call Start Time:   11 May 2026 08:16:54
Call End Time:   11 May 2026 08:17:03
Call Duration: 00:00:10
Extension: 9539
Other Party: 97871494
Call Direction: Outgoing
Caller Number: 9539
Called Number: 97871494
Extension Name: Amy Lam
"""


class Rec:
    broker_ext = None
    broker_name = None
    caller_number = None
    direction = "unknown"
    call_started_at = None


def test_parse_call_export_text_metadata():
    meta = _parse_call_export_text(TXT)

    assert meta["started_at"] == datetime(2026, 5, 11, 8, 16, 54, tzinfo=HK)
    assert meta["broker_ext"] == "9539"
    assert meta["broker_name"] == "Amy Lam"
    assert meta["caller_number"] == "97871494"
    assert meta["direction"] == "OUT"
    assert _metadata_key_from_start(meta) == "20260511_081654"


def test_match_metadata_by_same_or_contained_name():
    metadata = {
        "abc123.txt": {"broker_ext": "1111"},
        "2476510.txt": {"broker_ext": "9539"},
    }

    assert _match_metadata_for_audio("2476510.wav", metadata)["broker_ext"] == "9539"
    assert _match_metadata_for_audio("prefix_2476510_call.wav", metadata)["broker_ext"] == "9539"


def test_match_metadata_by_call_start_time_key():
    meta = _parse_call_export_text(TXT)
    metadata = {"2476510.txt": meta}

    assert _match_metadata_for_audio("20260511_081654.wav", metadata) == meta


def test_apply_txt_metadata_to_recording_like_object():
    meta = _parse_call_export_text(TXT)
    rec = Rec()

    _apply_txt_metadata(rec, meta)

    assert rec.broker_ext == "9539"
    assert rec.broker_name == "Amy Lam"
    assert rec.caller_number == "97871494"
    assert rec.direction == "OUT"
    assert rec.call_started_at == datetime(2026, 5, 11, 8, 16, 54, tzinfo=HK)
