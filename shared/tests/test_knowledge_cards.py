import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from voiceqa_shared.knowledge_cards import (
    CONTENT_COLUMNS,
    match_knowledge_cards,
    parse_card_workbook,
    parse_faq_workbook,
    related_faq_codes,
)


def card(words=None, active=True):
    return {
        "id": "card-id",
        "code": "K11",
        "title": "FPS",
        "trigger_words": words or ["轉數快", "QR code", "FPS"],
        "content": {},
        "active": active,
    }


def test_faq_workbook_parser_and_legacy_references():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "常见问题库"
    sheet.append(["编号", "分类", "问题", "答案", "关联卡片"])
    sheet.append(["F01", "理赔", "Question?", "Answer", "K01"])
    sheet.append(["问答数", 1])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    assert parse_faq_workbook(buffer.getvalue())[0]["answer"] == "Answer"
    assert related_faq_codes({"related_questions": "f01 Question; F02 another"}) == ["F01", "F02"]
    assert related_faq_codes({"related_faq_codes": [], "related_questions": "F01"}) == []


def test_faq_seed_contains_43_valid_questions():
    payload = json.loads(
        (
            Path(__file__).resolve().parents[2] / "infra/migrations/data/0021_fwd_faqs.json"
        ).read_text(encoding="utf-8")
    )
    assert len(payload) == 43
    assert len({row["code"] for row in payload}) == 43
    assert all(row["question"] and row["answer"] and row["demo_notice"] for row in payload)


def segment(text):
    return {"text": text, "start_ms": 1000, "end_ms": 2000}


def workbook_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "知识卡片清单"
    sheet.append(["卡片", "标题", "触发词", *CONTENT_COLUMNS.values()])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def test_matches_simplified_traditional_and_english_spacing():
    matches = match_knowledge_cards([card()], [segment("我想用转数快。請用qrCode。FPS payment。")])
    assert matches[0]["hits"][0]["matched_terms"] == ["轉數快", "QR code", "FPS"]
    assert matches[0]["hits"][0]["start_ms"] == 1000
    assert matches[0]["hits"][0]["segment_index"] == 0


def test_numeric_boundary_and_separators():
    assert not match_knowledge_cards([card(["1000"])], [segment("保障10000元")])
    assert match_knowledge_cards([card(["1000"])], [segment("保障1,000元")])


def test_english_trigger_is_not_substring_of_another_word():
    assert not match_knowledge_cards([card(["App"])], [segment("happy customer")])
    assert match_knowledge_cards([card(["App"])], [segment("use APP please")])


def test_inactive_and_nonmatching_cards_are_not_returned():
    assert not match_knowledge_cards([card(active=False)], [segment("FPS")])
    assert not match_knowledge_cards([card()], [segment("早晨你好")])


def test_repeated_mentions_produce_one_card_with_multiple_hits():
    matches = match_knowledge_cards([card()], [segment("FPS FPS"), segment("QR code")])
    assert len(matches) == 1
    assert len(matches[0]["hits"]) == 2
    assert matches[0]["hits"][0]["matched_terms"] == ["FPS"]


def test_import_preserves_content_and_skips_notes():
    raw = workbook_bytes(
        [
            ["K01", "索償", "索償、FPS,FPS", "要點", "步驟", "回覆", "產品", "問題", "來源"],
            ["内部备注", "not a card"],
        ]
    )
    cards = parse_card_workbook(raw)
    assert len(cards) == 1
    assert cards[0]["trigger_words"] == ["索償", "FPS"]
    assert cards[0]["content"]["source"] == "來源"
    assert "FWD" in cards[0]["content"]["demo_notice"]


def test_duplicate_codes_abort_import():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_card_workbook(workbook_bytes([["K01", "one", "FPS"], ["K01", "two", "App"]]))


def test_missing_trigger_aborts_import():
    with pytest.raises(ValueError, match="Invalid title"):
        parse_card_workbook(workbook_bytes([["K01", "one", ""]]))


def test_invalid_workbook_is_rejected():
    with pytest.raises(ValueError, match="Invalid XLSX"):
        parse_card_workbook(b"not an xlsx")


def test_seed_snapshot_has_nineteen_cards_and_no_demo_scenario_as_trigger():
    path = (
        Path(__file__).resolve().parents[2] / "infra/migrations/data/0020_fwd_knowledge_cards.json"
    )
    cards = json.loads(path.read_text(encoding="utf-8"))
    assert len(cards) == 19
    assert len({item["code"] for item in cards}) == 19
    assert sum(len(item["trigger_words"]) for item in cards) == 92
    assert all("trigger_calls" not in item for item in cards)
