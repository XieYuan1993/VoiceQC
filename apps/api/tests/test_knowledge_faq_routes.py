import uuid
from types import SimpleNamespace

import pytest
from app.routers import knowledge_cards, knowledge_faqs
from app.schemas import KnowledgeCardIn, KnowledgeFaqIn
from fastapi import HTTPException


def card_content(**extra):
    return (
        dict.fromkeys(
            (
                "key_points",
                "procedure",
                "suggested_reply",
                "related_products",
                "related_questions",
                "source",
                "demo_notice",
            ),
            "",
        )
        | extra
    )


@pytest.mark.anyio
async def test_faq_read_and_edits_cannot_cross_projects():
    project = uuid.uuid4()
    item = SimpleNamespace(project_id=uuid.uuid4(), active=True, code="F01")

    class Session:
        async def get(self, model, key):
            return item

    for operation in (
        knowledge_faqs.get_faq(uuid.uuid4(), project, SimpleNamespace(role="admin"), Session()),
        knowledge_faqs._save_faq(
            KnowledgeFaqIn(code="F01", category="", question="Q", answer="A"),
            uuid.uuid4(),
            project,
            None,
            Session(),
            None,
        ),
        knowledge_cards._save_card(
            KnowledgeCardIn(code="K01", title="T", trigger_words=["FPS"], content=card_content()),
            uuid.uuid4(),
            project,
            None,
            Session(),
            None,
        ),
    ):
        with pytest.raises(HTTPException) as error:
            await operation
        assert error.value.status_code == 404


@pytest.mark.anyio
async def test_faq_links_resolve_only_in_same_project():
    project = uuid.uuid4()
    statements = []
    faq = SimpleNamespace(id=uuid.uuid4(), code="F01", question="Question", active=True)

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [faq]))

    card = SimpleNamespace(
        id=uuid.uuid4(),
        code="K01",
        title="Card",
        trigger_words=["FPS"],
        active=True,
        content={"related_questions": "F01 Question"},
    )
    result = await knowledge_cards.cards_with_faqs(Session(), project, [card])
    assert project in statements[0].compile().params.values()
    assert result[0]["related_faqs"][0]["id"] == faq.id
    assert result[0]["content"]["related_faq_codes"] == ["F01"]


@pytest.mark.anyio
async def test_unknown_faq_reference_rejected():
    class Session:
        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    payload = KnowledgeCardIn(
        code="K01",
        title="Card",
        trigger_words=["FPS"],
        content=card_content(related_faq_codes=["F99"]),
    )
    with pytest.raises(HTTPException) as error:
        await knowledge_cards._save_card(payload, None, uuid.uuid4(), None, Session(), None)
    assert error.value.status_code == 400


@pytest.mark.anyio
async def test_empty_answer_rejected_before_write():
    payload = KnowledgeFaqIn(code="F01", category="", question="Q", answer="  ")
    with pytest.raises(HTTPException) as error:
        await knowledge_faqs._save_faq(payload, None, uuid.uuid4(), None, None, None)
    assert error.value.status_code == 400


@pytest.mark.anyio
async def test_create_and_update_card_and_faq(monkeypatch):
    project = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.test")
    meta = SimpleNamespace(ip=None, user_agent=None)
    writes = []

    class Session:
        def add(self, item):
            writes.append(item)

        async def commit(self):
            pass

        async def get(self, model, key):
            return next(item for item in writes if item.id == key)

    monkeypatch.setattr(knowledge_cards, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge_faqs, "log_audit", lambda *args, **kwargs: None)
    session = Session()
    card = await knowledge_cards._save_card(
        KnowledgeCardIn(
            code="K20", title=" Card ", trigger_words=[" FPS ", "FPS"], content=card_content()
        ),
        None,
        project,
        user,
        session,
        meta,
    )
    assert card["title"] == "Card"
    assert card["trigger_words"] == ["FPS"]
    updated = await knowledge_cards._save_card(
        KnowledgeCardIn(
            code="K20", title="Changed", trigger_words=["FPS"], content=card_content(), active=False
        ),
        card["id"],
        project,
        user,
        session,
        meta,
    )
    assert not updated["active"]
    faq = await knowledge_faqs._save_faq(
        KnowledgeFaqIn(code="F44", category="Demo", question="Question", answer=" Answer "),
        None,
        project,
        user,
        session,
        meta,
    )
    assert faq["answer"] == "Answer"
    updated_faq = await knowledge_faqs._save_faq(
        KnowledgeFaqIn(
            code="F44", category="Demo", question="Question", answer="Changed", active=False
        ),
        faq["id"],
        project,
        user,
        session,
        meta,
    )
    assert not updated_faq["active"]
    assert all(item.project_id == project for item in writes)
