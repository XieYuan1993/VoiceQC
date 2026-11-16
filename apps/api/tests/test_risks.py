import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.routers import risks
from voiceqa_shared.complaint_risks import PHRASES, detect_risk


def test_risk_rules_match_frontend_and_scenarios():
    source = (
        Path(__file__).resolve().parents[2] / "web/src/lib/supervisor-notification.ts"
    ).read_text(encoding="utf-8")
    assert json.loads(re.search(r"const phrases = (\[.*?\]);", source).group(1)) == PHRASES
    assert detect_risk("點解你哋嘅服務咁差")["risk_type"] == "dissatisfaction"
    assert detect_risk("我非常的不高兴")["risk_type"] == "dissatisfaction"
    assert detect_risk("我要投訴")["risk_type"] == "complaint"
    assert detect_risk("我要搵你主管")["risk_type"] == "supervisor"
    assert detect_risk("我不想投诉你") is None
    assert detect_risk("我想查詢保單") is None
    assert detect_risk("我要投訴, 搵你主管", "supervisor")["risk_type"] == "supervisor"


@pytest.mark.anyio
async def test_empty_inbox_scopes_by_project_and_broker(monkeypatch):
    project = uuid.uuid4()
    statements = []

    async def scope(session, user):
        return {"1234"}

    monkeypatch.setattr(risks, "_scope_extensions", scope)

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(
                scalar_one=lambda: 0, scalars=lambda: SimpleNamespace(all=lambda: [])
            )

    result = await risks.list_risks(
        page=1, q="", kind=None, project_id=project, user=None, session=Session()
    )
    assert result["total"] == 0
    for statement in statements:
        assert project in statement.compile().params.values()
        assert "broker_ext" in str(statement)
        assert "customer" in statement.compile().params.values()


@pytest.mark.anyio
async def test_risk_inbox_groups_evidence_per_recording(monkeypatch):
    project, recording_id = uuid.uuid4(), uuid.uuid4()

    async def scope(session, user):
        return None

    monkeypatch.setattr(risks, "_scope_extensions", scope)
    rec = SimpleNamespace(
        id=recording_id, original_filename="demo.wav", call_started_at=None, status="completed"
    )
    segment = SimpleNamespace(text="我要投訴", start_ms=1000, end_ms=2000)
    responses = [
        SimpleNamespace(scalar_one=lambda: 1),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [rec])),
        SimpleNamespace(all=lambda: [(recording_id, segment)]),
    ]

    class Session:
        async def execute(self, statement):
            return responses.pop(0)

    result = await risks.list_risks(
        page=1, q="", kind=None, project_id=project, user=None, session=Session()
    )
    assert result["total"] == 1
    assert result["items"][0]["hits"][0]["label"] == "投訴升級"
    assert result["items"][0]["hits"][0]["start_ms"] == 1000
