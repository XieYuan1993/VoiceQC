from app.routers.recordings import _format_segment_time, _safe_export_text, _speaker_label


def test_fwd_export_uses_two_speaker_labels() -> None:
    assert _speaker_label("broker") == "Speaker 1"
    assert _speaker_label("mixed") == "Speaker 1"
    assert _speaker_label("customer") == "Speaker 2"


def test_fwd_export_formats_times_and_pipe_safe_text() -> None:
    assert _format_segment_time(3_723_004) == "01:02:03.004"
    assert _safe_export_text("保單|查詢\n下一行") == "保單 查詢 下一行"
