import uuid
from datetime import date

import pytest
from app.routers.recon import _get_run
from fastapi import HTTPException
from voiceqa_shared.db_models import ReconRun


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, run: ReconRun | None):
        self.run = run
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return ScalarResult(self.run)


def _run(project_id: uuid.UUID) -> ReconRun:
    return ReconRun(
        id=uuid.uuid4(),
        project_id=project_id,
        trade_date=date(2026, 5, 13),
        params_snapshot={},
    )


@pytest.mark.anyio
async def test_get_run_accepts_run_in_active_project() -> None:
    project_id = uuid.uuid4()
    run = _run(project_id)

    result = await _get_run(FakeSession(run), run.id, project_id)

    assert result is run


@pytest.mark.anyio
async def test_get_run_hides_run_from_another_project() -> None:
    session = FakeSession(None)

    with pytest.raises(HTTPException) as exc_info:
        await _get_run(session, uuid.uuid4(), uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "run not found"
