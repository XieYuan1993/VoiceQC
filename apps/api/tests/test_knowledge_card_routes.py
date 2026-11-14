import io
import uuid
from types import SimpleNamespace

import pytest
from app.routers import knowledge_cards
from app.routers.knowledge_cards import list_cards
from fastapi import UploadFile
from voiceqa_shared.db_models import KnowledgeCard


@pytest.mark.anyio
async def test_list_cards_filters_by_project_and_active():
    project_id = uuid.uuid4()
    statements = []

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    assert await list_cards(project_id=project_id, user=None, session=Session()) == []
    statement = statements[0]
    assert project_id in statement.compile().params.values()
    sql = str(statement)
    assert "knowledge_cards.project_id =" in sql
    assert "knowledge_cards.active IS true" in sql
    assert statement.column_descriptions[0]["entity"] is KnowledgeCard


@pytest.mark.anyio
@pytest.mark.parametrize("existing,created,updated", [([], 1, 0), (["K01"], 0, 1)])
async def test_import_upserts_into_only_requested_project(monkeypatch, existing, created, updated):
    project_id = uuid.uuid4()
    statements = []
    commits = []
    monkeypatch.setattr(
        knowledge_cards,
        "parse_card_workbook",
        lambda raw: [{"code": "K01", "title": "Title", "trigger_words": ["FPS"], "content": {}}],
    )
    monkeypatch.setattr(knowledge_cards, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge_cards, "parse_faq_workbook", lambda raw, required: [])

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: existing))

        async def commit(self):
            commits.append(True)

    result = await knowledge_cards.import_cards(
        file=UploadFile(filename="cards.xlsx", file=io.BytesIO(b"fake")),
        project_id=project_id,
        user=SimpleNamespace(id=uuid.uuid4(), email="admin@example.test"),
        session=Session(),
        meta=SimpleNamespace(ip=None, user_agent=None),
    )
    assert (result.created, result.updated, result.total) == (created, updated, 1)
    assert project_id in statements[0].compile().params.values()
    assert statements[1].compile().params["project_id"] == project_id
    assert "ON CONFLICT ON CONSTRAINT uq_knowledge_cards_project_code" in str(statements[1])
    assert commits == [True]
