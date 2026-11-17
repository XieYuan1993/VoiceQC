import uuid

import pytest
from app.routers.config import _v_navigation
from app.routers.workspace import amendment_query, summarize_enquiries
from sqlalchemy.dialects import postgresql


def test_navigation_validation_and_settings_lockout():
    _v_navigation({"/review": False, "/evaluator": True})
    _v_navigation({})
    for value in ({"/settings": False}, {"/unknown": True}, {"/review": "false"}, []):
        with pytest.raises(ValueError):
            _v_navigation(value)


def test_crs_summary_counts_events_not_runs_or_qa_payloads():
    result = summarize_enquiries(
        [
            None,
            {"other": "qa"},
            {
                "crs": {
                    "mode": "crs_classification",
                    "events": [{"category": "Life"}, {"category": "Life"}, {"category": "Claims"}],
                }
            },
            {"crs": {"mode": "crs_classification", "events": []}},
        ]
    )
    assert result == (2, 3, [{"label": "Life", "count": 2}, {"label": "Claims", "count": 1}])


def test_amendment_history_is_project_and_broker_scoped():
    project = uuid.uuid4()
    query = amendment_query(project, ["1234"])
    compiled = query.compile(dialect=postgresql.dialect())
    assert "recordings.project_id =" in str(compiled)
    assert "recordings.broker_ext IN" in str(compiled)
    assert "CAST(transcripts.id AS TEXT)" in str(compiled)
    assert project in compiled.params.values()
    assert "transcript.edit" in compiled.params.values()
    assert "LEFT OUTER JOIN transcripts" in str(compiled)
    assert "recording_id" in compiled.params.values()


@pytest.mark.anyio
async def test_overview_uses_latest_completed_scoped_runs(monkeypatch):
    from types import SimpleNamespace

    from app.routers import workspace

    async def extensions(*args):
        return ["1234"]

    monkeypatch.setattr(workspace, "_scope_extensions", extensions)
    statements = []

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            if len(statements) == 1:
                return SimpleNamespace(
                    all=lambda: [("completed", 2), ("failed", 1), ("transcribing", 1)]
                )
            if len(statements) == 2:
                return SimpleNamespace(scalar_one=lambda: 1)
            if len(statements) == 3:
                compiled = statement.compile(dialect=postgresql.dialect())
                assert "max(evaluations.run_seq)" in str(compiled)
                assert "completed" in compiled.params.values()
                assert "recordings.broker_ext IN" in str(compiled)
                return SimpleNamespace(
                    scalars=lambda: SimpleNamespace(
                        all=lambda: [
                            {
                                "crs": {
                                    "mode": "crs_classification",
                                    "events": [{"category": "Life"}],
                                }
                            }
                        ]
                    )
                )
            return SimpleNamespace(scalar_one=lambda: 3)

    result = await workspace.overview(uuid.uuid4(), SimpleNamespace(), Session())
    assert result["recordings"] == 4
    assert result["processing"] == 1
    assert result["failed"] == 1
    assert result["risk_recordings"] == 1
    assert result["enquiries"] == 1
    assert result["amendments"] == 3
