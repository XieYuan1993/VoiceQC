import hashlib
import json
import wave
from pathlib import Path

import pytest
from worker.asr.base import ChannelFile
from worker.asr.dyna_asr import DynaASR, chunks, corrected_segments


def segment(speaker=0, start=1000, end=2000, text="text"):
    return {"speakerId": speaker, "startTime": start, "endTime": end, "text": text}


def test_chunks_and_role_mapping_use_audio_not_flow_labels():
    source = chunks([segment(0), segment(1, 2000, 3000)])
    result = corrected_segments(
        "2|00:01.000 - 00:02.000|first\n1|00:02.000 - 00:03.000|second", source[0]
    )
    assert [item["speakerId"] for item in result] == [0, 1]
    assert len(chunks([segment(start=i * 1000, end=(i + 1) * 1000) for i in range(121)])) == 2


@pytest.mark.parametrize(
    "text", ["invalid", "1|00:01.000 - 00:02.000|", "1|00:03.000 - 00:04.000|changed"]
)
def test_flow_format_empty_and_timing_changes_rejected(text):
    with pytest.raises(RuntimeError):
        corrected_segments(text, chunks([segment()])[0])


def test_first_upload_and_operation_contains_no_credentials(tmp_path, monkeypatch):
    from worker.asr import dyna_asr

    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(64000))
    data = source.read_bytes()
    monkeypatch.setattr(
        dyna_asr.gcs,
        "download_uri_to_file",
        lambda uri, destination: Path(destination).write_bytes(data),
    )
    calls = []
    adapter = DynaASR("gs://bucket/raw.wav")

    def request(method, path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/init"):
            return [
                {
                    "file_uuid": "file-1",
                    "file_status": "pending",
                    "parts": [{"part_number": 1, "offset": 0, "size": len(data)}],
                }
            ]
        if path.endswith("/task"):
            return {"task_uuid": "task-1"}
        return {}

    monkeypatch.setattr(adapter, "_request", request)
    operation = json.loads(
        adapter.start_batch(
            [
                ChannelFile("gs://bucket/b.flac", "broker"),
                ChannelFile("gs://bucket/c.flac", "customer"),
            ],
            language_mode="cmn-Hans-CN",
            adaptation_phrases=[],
            model="dyna-auto",
        )
    )
    part = next(kwargs for path, kwargs in calls if path.endswith("/part"))
    assert part["data"]["part_hash"] == hashlib.md5(data).hexdigest()
    assert part["files"]["part_data"][1] == data
    assert any(path.endswith("/complete") for path, _ in calls)
    assert operation["engine"] == "manual_split_16k"
    assert "auth" not in operation
    assert "token" not in json.dumps(operation).lower()


def test_resume_uses_saved_flow_and_preserves_roles(monkeypatch):
    adapter = DynaASR()
    cache = {"stt-results/rec/dyna/task-1/raw.json": [segment(0), segment(1, 2000, 3000)]}
    calls = []
    monkeypatch.setattr(adapter, "_read", lambda key: cache.get(key))
    monkeypatch.setattr(adapter, "_save", lambda key, value: cache.update({key: value}))

    def request(method, path, **kwargs):
        calls.append(path)
        return {
            "result": {
                "status": 1,
                "result": "2|00:01.000 - 00:02.000|customer\n1|00:02.000 - 00:03.000|agent",
            }
        }

    monkeypatch.setattr(adapter, "_request", request)
    operation = json.dumps(
        {
            "task": "task-1",
            "prefix": "stt-results/rec/dyna",
            "files": {"broker": "b", "customer": "c"},
            "broker_channel": "right",
            "duration": 3,
            "flow": "saved-flow",
            "robot_id": 123,
        }
    )
    result = adapter.fetch_result(operation)
    assert result[0].segments[0].text == "agent"
    assert result[1].segments[0].text == "customer"
    assert adapter.fetch_result(operation)[0].segments[0].text == "agent"
    assert len(calls) == 1


def test_mono_rejected_explicitly():
    with pytest.raises(RuntimeError, match="stereo"):
        DynaASR("gs://bucket/mono.wav").start_batch(
            [ChannelFile("m", "mixed")],
            language_mode="auto",
            adaptation_phrases=[],
            model="dyna-auto",
        )


def test_long_call_yields_between_flow_chunks(monkeypatch):
    adapter = DynaASR()
    audio = [segment(i % 2, i * 1000, (i + 1) * 1000) for i in range(121)]
    groups = chunks(audio)
    cache = {"p/task/raw.json": audio}
    calls = []
    monkeypatch.setattr(adapter, "_read", lambda key: cache.get(key))
    monkeypatch.setattr(adapter, "_save", lambda key, value: cache.update({key: value}))

    def request(method, path, **kwargs):
        group = groups[len(calls)]
        calls.append(path)

        def timestamp(value):
            return f"{value // 60000:02d}:{value // 1000 % 60:02d}.{value % 1000:03d}"

        text = "\n".join(
            f"1|{timestamp(item['startTime'])} - {timestamp(item['endTime'])}|text"
            for item, _ in group
        )
        return {"result": {"status": 1, "result": text}}

    monkeypatch.setattr(adapter, "_request", request)
    operation = json.dumps(
        {
            "task": "task",
            "prefix": "p",
            "files": {"broker": "b", "customer": "c"},
            "broker_channel": "left",
            "duration": 121,
            "flow": "f",
            "robot_id": 1,
        }
    )
    assert adapter.fetch_result(operation) is None
    assert len(calls) == 1
    results = adapter.fetch_result(operation)
    assert sum(len(result.segments) for result in results) == 121
    assert len(calls) == 2
