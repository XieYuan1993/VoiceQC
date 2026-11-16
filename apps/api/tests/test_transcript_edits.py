import uuid
from types import SimpleNamespace

import pytest
from app.routers.recordings import _single_asr_override
from app.routers.transcript_edits import TranscriptEditIn, format_transcript, validate_edit
from fastapi import HTTPException


def test_edit_optimistic_concurrency_and_empty_text():
    for payload, code in [
        (TranscriptEditIn(expected_text="old", text="new"), 409),
        (TranscriptEditIn(expected_text="same", text="  "), 400),
    ]:
        with pytest.raises(HTTPException) as error:
            validate_edit(payload, "same", True)
        assert error.value.status_code == code


def test_hotword_annotations_require_permission_and_source():
    payload = TranscriptEditIn(
        expected_text="安富你好", text="富衛你好", wrong="安富", correct="富衛"
    )
    validate_edit(payload, "安富你好", True)
    with pytest.raises(HTTPException) as error:
        validate_edit(payload, "安富你好", False)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException):
        validate_edit(
            TranscriptEditIn(expected_text="你好", text="你好", wrong="missing", correct="word"),
            "你好",
            True,
        )
    validate_edit(TranscriptEditIn(expected_text="你好", text="您好"), "你好", False)
    validate_edit(
        TranscriptEditIn(expected_text="富衛你好", text="富衛你好", correct="富衛"),
        "富衛你好",
        True,
    )


def test_full_text_stays_consistent_with_timed_segments():
    segments = [
        SimpleNamespace(start_ms=1000, channel_role="broker", text="您好"),
        SimpleNamespace(start_ms=62000, channel_role="customer", text="查詢保單"),
    ]
    assert format_transcript(segments) == "[00:01] broker: 您好\n[01:02] customer: 查詢保單"


def test_single_dyna_override_and_existing_default():
    rec = SimpleNamespace(
        gcs_uri_raw="raw",
        gcs_uri_broker="b",
        gcs_uri_customer="c",
        original_filename="call.WAV",
        rerun_asr_provider="tencent",
        rerun_asr_model="16k_zh_en",
    )
    assert _single_asr_override(rec, "stt", "dyna", "manual_split_16k_yue") == (
        "dyna",
        "manual_split_16k_yue",
    )
    assert _single_asr_override(rec, "stt", None, None) == ("tencent", "16k_zh_en")
    for stage, provider, model in [
        ("eval", "dyna", "manual_split_16k"),
        ("stt", None, "manual_split_16k"),
        ("stt", "dyna", "wrong"),
    ]:
        with pytest.raises(HTTPException):
            _single_asr_override(rec, stage, provider, model)


@pytest.mark.anyio
@pytest.mark.parametrize("hotword", [False, True])
async def test_segment_save_updates_full_text_and_audits(monkeypatch, hotword):
    from app.routers import transcript_edits

    project, recording_id, transcript_id, segment_id = [uuid.uuid4() for _ in range(4)]
    rec = SimpleNamespace(id=recording_id, status="completed")
    transcript = SimpleNamespace(id=transcript_id, full_text="old")
    segment = SimpleNamespace(
        id=segment_id,
        transcript_id=transcript_id,
        start_ms=1000,
        channel_role="broker",
        text="安富你好",
    )
    audits, writes, inserts, commits = [], [], [], []

    async def scoped(session, user, rid, pid):
        assert (rid, pid) == (recording_id, project)
        return rec

    monkeypatch.setattr(transcript_edits, "_get_scoped", scoped)
    monkeypatch.setattr(
        transcript_edits, "log_audit", lambda session, **kwargs: audits.append(kwargs)
    )

    class Session:
        async def execute(self, statement, *args):
            sql = str(statement)
            if "FROM recordings" in sql:
                assert "FOR UPDATE" in sql
                assert project in statement.compile().params.values()
                return SimpleNamespace(scalar_one=lambda: rec)
            if "FROM transcripts" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: transcript)
            if "FROM transcript_segments" in sql:
                if "transcript_segments.id =" in sql:
                    assert transcript_id in statement.compile().params.values()
                    return SimpleNamespace(scalar_one_or_none=lambda: segment)
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [segment]))
            if "INSERT INTO industry_terms" in sql:
                inserts.append(statement)

        async def get(self, model, key):
            return None

        def add(self, value):
            writes.append(value)

        async def flush(self):
            pass

        async def commit(self):
            commits.append(True)

    payload = TranscriptEditIn(
        expected_text="安富你好",
        text="富衛你好",
        **({"wrong": "安富", "correct": "富衛"} if hotword else {}),
    )
    result = await transcript_edits.edit_segment(
        recording_id,
        segment_id,
        payload,
        project,
        SimpleNamespace(id=uuid.uuid4(), email="admin@example.test", role="admin"),
        Session(),
        SimpleNamespace(ip=None, user_agent=None),
    )
    assert result == {"changed": True, "hotword_saved": hotword}
    assert transcript.full_text == "[00:01] broker: 富衛你好"
    assert commits == [True]
    assert any(
        entry["action"] == "transcript.edit" and entry["details"]["before"] == "安富你好"
        for entry in audits
    )
    if hotword:
        assert writes[0].project_id == project
        assert writes[0].value[0]["correct"] == "富衛"
        assert inserts[0].compile().params["aliases"] == []


@pytest.mark.anyio
async def test_edit_cannot_bypass_project_scope(monkeypatch):
    from app.routers import transcript_edits

    async def deny(*args):
        raise HTTPException(404, "not found")

    monkeypatch.setattr(transcript_edits, "_get_scoped", deny)
    with pytest.raises(HTTPException) as error:
        await transcript_edits.edit_segment(
            uuid.uuid4(),
            uuid.uuid4(),
            TranscriptEditIn(expected_text="old", text="new"),
            uuid.uuid4(),
            None,
            None,
            None,
        )
    assert error.value.status_code == 404
