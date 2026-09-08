import uuid

import pytest
from app.routers.recordings import _get_scoped
from fastapi import HTTPException
from voiceqa_shared.db_models import Recording, User


class FakeSession:
    def __init__(self, recording: Recording | None):
        self.recording = recording

    async def get(self, _model, _recording_id):
        return self.recording


def _recording(project_id: uuid.UUID) -> Recording:
    return Recording(
        project_id=project_id,
        batch_id=uuid.uuid4(),
        original_filename="call.wav",
        sha256="0" * 64,
        size_bytes=1,
    )


def _admin() -> User:
    return User(id=uuid.uuid4(), role="admin")


@pytest.mark.anyio
async def test_get_scoped_accepts_recording_in_active_project() -> None:
    project_id = uuid.uuid4()
    recording = _recording(project_id)

    result = await _get_scoped(FakeSession(recording), _admin(), uuid.uuid4(), project_id)

    assert result is recording


@pytest.mark.anyio
async def test_get_scoped_hides_recording_from_another_project() -> None:
    recording = _recording(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await _get_scoped(FakeSession(recording), _admin(), uuid.uuid4(), uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "recording not found"
