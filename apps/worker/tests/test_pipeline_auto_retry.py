import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from worker.tasks import batch, pipeline


class _Session:
    def __init__(self, recording) -> None:
        self.recording = recording
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, _model, _recording_id):
        return self.recording

    def commit(self) -> None:
        self.committed = True


def test_terminal_stt_failure_schedules_persisted_provider_retry(monkeypatch) -> None:
    recording = SimpleNamespace(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        auto_retry_remaining=2,
        rerun_asr_provider="tencent",
        rerun_asr_model="16k_zh_en",
        gcs_uri_broker=None,
        gcs_uri_customer=None,
        gcs_uri_mono="gs://bucket/mono.flac",
        stt_operation_name="old-task",
        stt_started_at=datetime.now(UTC),
        status="transcribing",
        failed_stage=None,
        error=None,
        attempts=5,
    )
    session = _Session(recording)
    dispatched = []
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        pipeline,
        "_dispatch_auto_retry",
        lambda *args: dispatched.append(args),
    )

    pipeline._fail(str(recording.id), "stt", RuntimeError("provider failed"))

    assert session.committed is True
    assert recording.status == "transcribing"
    assert recording.failed_stage is None
    assert recording.stt_operation_name is None
    assert recording.stt_started_at is None
    assert recording.auto_retry_remaining == 1
    assert recording.attempts == 0
    assert dispatched == [(str(recording.id), "stt", "tencent", "16k_zh_en")]


def test_permanent_provider_failure_is_not_automatically_retried(monkeypatch) -> None:
    recording = SimpleNamespace(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        auto_retry_remaining=2,
        rerun_asr_provider="tencent",
        rerun_asr_model="16k_zh_en",
        gcs_uri_broker=None,
        gcs_uri_customer=None,
        gcs_uri_mono="gs://bucket/mono.flac",
        stt_operation_name="old-task",
        stt_started_at=datetime.now(UTC),
        status="transcribing",
        failed_stage=None,
        error=None,
        attempts=0,
    )
    session = _Session(recording)
    dispatched = []
    progress_updates = []
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        pipeline,
        "_dispatch_auto_retry",
        lambda *args: dispatched.append(args),
    )
    monkeypatch.setattr(batch.update_progress, "delay", progress_updates.append)
    monkeypatch.setattr(batch.dispatch_stt_waiting, "delay", lambda: None)

    pipeline._fail(
        str(recording.id),
        "stt",
        RuntimeError("Tencent ASR FailedOperation.UserHasNoAmount"),
    )

    assert recording.status == "failed"
    assert recording.failed_stage == "stt"
    assert recording.auto_retry_remaining == 2
    assert recording.stt_started_at is None
    assert dispatched == []
    assert progress_updates == [str(recording.batch_id)]


def test_stt_timeout_starts_only_after_remote_slot_is_claimed() -> None:
    now = datetime.now(UTC)
    queued = SimpleNamespace(stt_started_at=None)
    running = SimpleNamespace(stt_started_at=now - timedelta(minutes=31))

    assert pipeline._stt_timed_out(queued, now) is False
    assert pipeline._stt_timed_out(running, now) is True


def test_stt_slot_marks_transcribing_stage_as_started() -> None:
    rec = SimpleNamespace(
        status="transcribing",
        stt_started_at=datetime.now(UTC),
        stt_operation_name=None,
    )

    assert batch._stage_has_started(None, rec) is True


def test_uploaded_recording_is_still_queued_not_running() -> None:
    rec = SimpleNamespace(status="uploaded")

    assert batch._stage_has_started(None, rec) is False


def test_available_stt_slots_are_bounded_by_remote_limit(monkeypatch) -> None:
    monkeypatch.setattr(batch.settings, "STT_MAX_IN_FLIGHT", 3)

    assert batch._available_stt_slots(0) == 3
    assert batch._available_stt_slots(2) == 1
    assert batch._available_stt_slots(3) == 0
    assert batch._available_stt_slots(5) == 0


class _DispatchResult:
    def __init__(self, *, scalar=None, rows=None) -> None:
        self.scalar = scalar
        self.rows = rows

    def scalar_one(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _DispatchSession:
    def __init__(self, active, rows) -> None:
        self.results = [
            _DispatchResult(),
            _DispatchResult(scalar=active),
            _DispatchResult(rows=rows),
        ]
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, _statement, _params=None):
        return self.results.pop(0)

    def commit(self) -> None:
        self.committed = True


def test_dispatcher_reserves_only_available_stt_slots(monkeypatch) -> None:
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            rerun_asr_provider="tencent",
            rerun_asr_model="16k_zh_en",
            stt_started_at=None,
            updated_at=None,
        )
        for _ in range(2)
    ]
    session = _DispatchSession(active=1, rows=rows)
    dispatched = []
    monkeypatch.setattr(batch.settings, "STT_MAX_IN_FLIGHT", 3)
    monkeypatch.setattr(batch, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        pipeline.transcribe,
        "delay",
        lambda *args: dispatched.append(args),
    )

    queued = batch.dispatch_stt_waiting()

    assert queued == 2
    assert session.committed is True
    assert all(row.stt_started_at is not None for row in rows)
    assert dispatched == [
        (str(row.id), "tencent", "16k_zh_en") for row in rows
    ]
