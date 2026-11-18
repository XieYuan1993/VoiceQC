import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.routers import evaluations
from fastapi import HTTPException


def fixture_data(status="completed", crs=None):
    now = datetime.now(UTC)
    rec = SimpleNamespace(id=uuid.uuid4(), original_filename="客戶錄音.wav")
    ev = SimpleNamespace(
        id=uuid.uuid4(),
        recording_id=rec.id,
        status=status,
        run_seq=3,
        summary="客戶查詢付款",
        created_at=now,
        completed_at=now,
        extracted_call_fields={"crs": crs} if crs is not None else {},
    )
    return rec, ev


@pytest.mark.anyio
@pytest.mark.parametrize(
    "events",
    [
        [],
        [
            {
                "enquiry": "我要查詢保單",
                "category": "20 Life",
                "event_detail": "Policy services",
                "content_detail": "付款狀況",
                "reason": "已付款",
                "rationale": "客戶表示已付款",
                "evidence_quote": "我已經交咗錢",
                "needs_review": True,
                "evidence_verified": False,
                "extra_field": "preserved",
            }
        ],
    ],
)
async def test_export_preserves_selected_run_and_multilingual_results(monkeypatch, events):
    project = uuid.uuid4()
    crs = {"mode": "crs_classification", "source": "llm", "events": events}
    rec, ev = fixture_data(crs=crs)
    audits = []
    statements = []

    class Session:
        committed = False

        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalar_one_or_none=lambda: ev)

        async def commit(self):
            self.committed = True

    async def scoped(session, user, rid, pid):
        assert rid == rec.id and pid == project
        return rec

    monkeypatch.setattr(evaluations, "_get_scoped", scoped)
    monkeypatch.setattr(evaluations, "log_audit", lambda *args, **kw: audits.append(kw))
    session = Session()
    response = await evaluations.export_evaluation(
        ev.id,
        project,
        SimpleNamespace(id=uuid.uuid4(), email="reader@test"),
        session,
        SimpleNamespace(ip=None, user_agent=None),
    )
    payload = json.loads(response.body.decode("utf-8"))
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].endswith('_run_3.json"')
    assert payload["evaluation"]["id"] == str(ev.id)
    assert payload["evaluation"]["crs"] == crs
    assert payload["recording"]["filename"] == rec.original_filename
    assert payload["project_id"] == str(project)
    assert "llm_model" not in payload["evaluation"]
    assert "客戶" in response.body.decode("utf-8")
    assert session.committed
    assert audits[0]["action"] == "evaluation.export"
    assert project in statements[0].compile().params.values()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,crs,code",
    [
        ("running", {"mode": "crs_classification"}, 409),
        ("failed", {"mode": "crs_classification"}, 409),
        ("completed", None, 404),
        ("completed", {"mode": "other"}, 404),
    ],
)
async def test_no_incomplete_or_noncrs_export(monkeypatch, status, crs, code):
    rec, ev = fixture_data(status, crs)

    async def get_evaluation(*args):
        return ev

    async def scoped(*args):
        return rec

    monkeypatch.setattr(evaluations, "_get_project_evaluation", get_evaluation)
    monkeypatch.setattr(evaluations, "_get_scoped", scoped)
    with pytest.raises(HTTPException) as error:
        await evaluations.export_evaluation(ev.id, uuid.uuid4(), None, None, None)
    assert error.value.status_code == code


@pytest.mark.anyio
async def test_export_denied_for_other_project():
    class Session:
        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    with pytest.raises(HTTPException) as error:
        await evaluations.export_evaluation(uuid.uuid4(), uuid.uuid4(), None, Session(), None)
    assert error.value.status_code == 404


@pytest.mark.anyio
async def test_export_respects_recording_row_scope(monkeypatch):
    _, ev = fixture_data(crs={"mode": "crs_classification"})

    async def get_evaluation(*args):
        return ev

    async def deny(*args):
        raise HTTPException(404, "recording not found")

    monkeypatch.setattr(evaluations, "_get_project_evaluation", get_evaluation)
    monkeypatch.setattr(evaluations, "_get_scoped", deny)
    with pytest.raises(HTTPException) as error:
        await evaluations.export_evaluation(ev.id, uuid.uuid4(), None, None, None)
    assert error.value.status_code == 404
