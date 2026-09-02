import uuid
from datetime import date

import pytest
from app.routers.batches import _get_batch
from fastapi import HTTPException
from voiceqa_shared.db_models import UploadBatch


class FakeSession:
    def __init__(self, batch: UploadBatch | None):
        self.batch = batch

    async def get(self, _model, _batch_id):
        return self.batch


def _batch(project_id: uuid.UUID) -> UploadBatch:
    return UploadBatch(
        project_id=project_id,
        name="Scoped batch",
        trade_date=date(2026, 5, 13),
        created_by=uuid.uuid4(),
    )


@pytest.mark.anyio
async def test_get_batch_accepts_batch_in_active_project() -> None:
    project_id = uuid.uuid4()
    batch = _batch(project_id)

    result = await _get_batch(FakeSession(batch), uuid.uuid4(), project_id)

    assert result is batch


@pytest.mark.anyio
async def test_get_batch_hides_batch_from_another_project() -> None:
    batch = _batch(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await _get_batch(FakeSession(batch), uuid.uuid4(), uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "batch not found"
