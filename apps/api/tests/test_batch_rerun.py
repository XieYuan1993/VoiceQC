import uuid
from datetime import UTC, datetime

from app.routers.batches import _prepare_stt_rerun
from app.schemas import BatchSttRerunIn
from voiceqa_shared.db_models import Recording


def _recording(**overrides) -> Recording:
    values = {
        "project_id": uuid.uuid4(),
        "batch_id": uuid.uuid4(),
        "original_filename": "call.wav",
        "sha256": "a" * 64,
        "size_bytes": 100,
        "gcs_uri_raw": "gs://bucket/raw.wav",
        "status": "completed",
        "attempts": 4,
        "auto_retry_remaining": 0,
    }
    values.update(overrides)
    return Recording(**values)


def test_prepare_bulk_rerun_uses_normalized_audio_and_persists_options() -> None:
    rec = _recording(
        gcs_uri_mono="gs://bucket/mono.flac",
        stt_operation_name="old-task",
        stt_started_at=datetime.now(UTC),
    )
    payload = BatchSttRerunIn(
        asr_provider="tencent",
        asr_model="16k_zh_en",
        auto_retry_limit=2,
    )

    stage = _prepare_stt_rerun(rec, payload)

    assert stage == "stt"
    assert rec.status == "transcribing"
    assert rec.attempts == 0
    assert rec.auto_retry_remaining == 2
    assert rec.rerun_asr_provider == "tencent"
    assert rec.rerun_asr_model == "16k_zh_en"
    assert rec.stt_operation_name is None
    assert rec.stt_started_at is None


def test_prepare_bulk_rerun_falls_back_to_conversion() -> None:
    rec = _recording(gcs_uri_mono=None)

    stage = _prepare_stt_rerun(
        rec,
        BatchSttRerunIn(asr_provider="qwen", auto_retry_limit=0),
    )

    assert stage == "convert"
    assert rec.status == "uploaded"


def test_prepare_bulk_rerun_skips_purged_audio() -> None:
    rec = _recording(gcs_uri_raw=None, gcs_uri_mono=None)

    stage = _prepare_stt_rerun(rec, BatchSttRerunIn(asr_provider="tencent"))

    assert stage is None
    assert rec.status == "completed"
