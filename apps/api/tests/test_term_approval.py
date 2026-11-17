import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.routers import terms
from app.schemas import TermIn
from app.term_approval import mark_pending, merge_rules, require_admin
from fastapi import HTTPException
from voiceqa_shared.db_models import AppSetting, IndustryTerm


def test_pending_deactivates_even_admin_and_retains_submitter():
    term = SimpleNamespace(active=True, approval_status="approved")
    mark_pending(term, SimpleNamespace(email="submitter@example.test", role="admin"))
    assert term.active is False
    assert term.approval_status == "pending"
    assert term.submitted_by == "submitter@example.test"
    assert term.submitted_at is not None
    assert term.reviewed_at is None


@pytest.mark.parametrize("role", ["reviewer", "compliance_manager", "broker", "auditor"])
def test_approval_admin_only(role):
    with pytest.raises(HTTPException) as error:
        require_admin(SimpleNamespace(role=role))
    assert error.value.status_code == 403
    require_admin(SimpleNamespace(role="admin"))


def test_rules_conflict_and_deduplicate_without_mutating_live_settings():
    old = [{"wrong": "bad", "correct": "good"}]
    assert merge_rules(old, old) == old
    assert len(old) == 1
    with pytest.raises(HTTPException) as error:
        merge_rules(old, [{"wrong": "bad", "correct": "different"}])
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        merge_rules([], [{"wrong": str(i), "correct": "x"} for i in range(501)])


@pytest.mark.anyio
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_review_publishes_rules_only_on_approval(monkeypatch, decision):
    project, tid = uuid.uuid4(), uuid.uuid4()
    term = IndustryTerm(
        id=tid,
        project_id=project,
        canonical="good",
        category="jargon",
        aliases=[],
        active=False,
        approval_status="pending",
        pending_rules=[{"wrong": "bad", "correct": "good", "context": "call"}],
        created_at=datetime.now(UTC),
        submitted_by="author@example.test",
    )
    user = SimpleNamespace(role="admin", id=uuid.uuid4(), email="admin@example.test")
    added, audits = [], []

    class Session:
        async def execute(self, statement, *args):
            if "FROM industry_terms" in str(statement):
                assert "FOR UPDATE" in str(statement)
                assert project in statement.compile().params.values()
                return SimpleNamespace(scalar_one_or_none=lambda: term)

        async def get(self, model, key):
            assert key == (project, "asr.post_correction_replacements")
            return None

        def add(self, row):
            added.append(row)

        async def commit(self):
            pass

    monkeypatch.setattr(terms, "log_audit", lambda *args, **kw: audits.append(kw))
    result = await terms.review_term(
        tid, decision, project, user, Session(), SimpleNamespace(ip=None, user_agent=None)
    )
    assert result.active == (decision == "approve")
    assert result.approval_status == ("approved" if decision == "approve" else "rejected")
    assert result.reviewed_by == user.email
    assert result.submitted_by == "author@example.test"
    assert bool(added) == (decision == "approve")
    if added:
        assert isinstance(added[0], AppSetting)
        assert added[0].value == term.pending_rules
    assert audits[0]["action"] == f"terms.{decision}"


@pytest.mark.anyio
async def test_create_ignores_client_activation(monkeypatch):
    added = []

    class Session:
        async def execute(self, statement, *args):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

        def add(self, term):
            term.id, term.created_at = uuid.uuid4(), datetime.now(UTC)
            added.append(term)

        async def flush(self):
            pass

        async def commit(self):
            pass

    monkeypatch.setattr(terms, "log_audit", lambda *args, **kw: None)
    result = await terms.create_term(
        TermIn(category="jargon", canonical="good", active=True),
        uuid.uuid4(),
        SimpleNamespace(email="author@test", id=uuid.uuid4()),
        Session(),
        SimpleNamespace(ip=None, user_agent=None),
    )
    assert result.active is False
    assert result.approval_status == "pending"


@pytest.mark.anyio
async def test_review_cannot_access_other_project_or_reapprove(monkeypatch):
    class Session:
        async def execute(self, statement, *args):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    with pytest.raises(HTTPException) as error:
        await terms.review_term(
            uuid.uuid4(), "approve", uuid.uuid4(), SimpleNamespace(role="admin"), Session(), None
        )
    assert error.value.status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["approved", "rejected"])
async def test_nonpending_review_rejected(state):
    class Session:
        async def execute(self, statement, *args):
            return SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(approval_status=state)
            )

    with pytest.raises(HTTPException) as error:
        await terms.review_term(
            uuid.uuid4(), "approve", uuid.uuid4(), SimpleNamespace(role="admin"), Session(), None
        )
    assert error.value.status_code == 409


@pytest.mark.anyio
async def test_update_resubmits_and_cannot_activate(monkeypatch):
    project, tid = uuid.uuid4(), uuid.uuid4()
    term = IndustryTerm(
        id=tid,
        project_id=project,
        canonical="old",
        category="jargon",
        aliases=[],
        pending_rules=[],
        active=True,
        approval_status="approved",
        created_at=datetime.now(UTC),
    )

    class Session:
        async def execute(self, statement, *args):
            sql = str(statement)
            if "FOR UPDATE" in sql:
                assert project in statement.compile().params.values()
                return SimpleNamespace(scalar_one_or_none=lambda: term)
            return SimpleNamespace(scalar_one_or_none=lambda: None)

        async def commit(self):
            pass

    monkeypatch.setattr(terms, "log_audit", lambda *args, **kw: None)
    result = await terms.update_term(
        tid,
        TermIn(category="jargon", canonical="new", active=True),
        project,
        SimpleNamespace(id=uuid.uuid4(), email="editor@test"),
        Session(),
        SimpleNamespace(ip=None, user_agent=None),
    )
    assert result.active is False
    assert result.approval_status == "pending"
    assert result.submitted_by == "editor@test"


@pytest.mark.anyio
async def test_csv_import_pending(monkeypatch):
    import io

    from fastapi import UploadFile

    added = []

    class Session:
        async def execute(self, statement, *args):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        def add(self, term):
            added.append(term)

        async def commit(self):
            pass

    monkeypatch.setattr(terms, "log_audit", lambda *args, **kw: None)
    file = UploadFile(
        file=io.BytesIO(b"category,canonical,stock_code,aliases,notes\njargon,test,,,\n"),
        filename="terms.csv",
    )
    result = await terms.import_csv(
        file,
        uuid.uuid4(),
        SimpleNamespace(id=uuid.uuid4(), email="importer@test"),
        Session(),
        SimpleNamespace(ip=None, user_agent=None),
    )
    assert result.created == 1
    assert added[0].active is False
    assert added[0].approval_status == "pending"
    assert added[0].submitted_by == "importer@test"
