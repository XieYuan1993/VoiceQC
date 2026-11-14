"""Workbook ingestion and deterministic transcript keyword matching."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from functools import lru_cache

from opencc import OpenCC
from openpyxl import load_workbook

SHEET = "知识卡片清单"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
CONTENT_COLUMNS = {
    "key_points": "要点",
    "procedure": "办理步骤\uff0f所需文件",
    "suggested_reply": "建议回复",
    "related_products": "相关产品",
    "related_questions": "相关问题",
    "source": "出处",
}


@lru_cache(maxsize=1)
def _converter():
    return OpenCC("t2s")


def _normalize(value: str) -> str:
    value = _converter().convert(unicodedata.normalize("NFKC", value)).casefold()
    value = re.sub(r"(?<=\d)[,\s]+(?=\d)", "", value)
    value = "".join(character if character.isalnum() else " " for character in value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", value)
    return " ".join(value.split())


def parse_card_workbook(raw: bytes) -> list[dict]:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Workbook exceeds the 5 MB limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError("Workbook expands beyond the size limit")
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid XLSX workbook") from exc
    try:
        if SHEET not in workbook.sheetnames:
            raise ValueError(f"Missing sheet: {SHEET}")
        rows = workbook[SHEET].iter_rows(values_only=True)
        header = next(rows, ())
        columns = {
            str(value).strip(): index for index, value in enumerate(header) if value is not None
        }
        required = {"卡片", "标题", "触发词", *CONTENT_COLUMNS.values()}
        missing = required.difference(columns)
        if missing:
            raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
        cards = []
        seen = set()
        for row_number, row in enumerate(rows, 2):
            if row_number > 501:
                raise ValueError("Workbook exceeds 500 rows")

            def cell(name, current_row=row):
                index = columns[name]
                return str(current_row[index] or "").strip() if index < len(current_row) else ""

            code = cell("卡片").upper()
            if not re.fullmatch(r"K\d+", code):
                continue
            title = cell("标题")
            words = list(
                dict.fromkeys(
                    word.strip()
                    for word in re.split(r"[、,\uff0c;\uff1b\n]+", cell("触发词"))
                    if word.strip()
                )
            )
            if not title or not words or len(words) > 50 or any(len(word) > 200 for word in words):
                raise ValueError(f"Invalid title or trigger words at row {row_number}")
            if code in seen:
                raise ValueError(f"Duplicate card: {code}")
            seen.add(code)
            content = {key: cell(column) for key, column in CONTENT_COLUMNS.items()}
            content["demo_notice"] = "示範資料\uff0c未經 FWD 核實"
            cards.append({"code": code, "title": title, "trigger_words": words, "content": content})
        if not cards:
            raise ValueError("No knowledge cards found")
        return cards
    finally:
        workbook.close()


def match_knowledge_cards(cards: list[dict], segments: list[dict]) -> list[dict]:
    normalized = [_normalize(segment["text"]) for segment in segments]
    matches = []
    for card in cards:
        if not card.get("active", True):
            continue
        patterns = []
        for word in card["trigger_words"]:
            term = _normalize(word)
            if not term:
                continue
            pattern = re.escape(term).replace(r"\ ", r"\s*")
            if term.isascii():
                pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
            patterns.append((word, re.compile(pattern)))
        hits = []
        for index, (text, segment) in enumerate(zip(normalized, segments, strict=True)):
            words = list(dict.fromkeys(word for word, pattern in patterns if pattern.search(text)))
            if words:
                hits.append(
                    {
                        "segment_index": index,
                        "start_ms": segment["start_ms"],
                        "end_ms": segment["end_ms"],
                        "matched_terms": words,
                    }
                )
        if hits:
            matches.append(
                {
                    "card": {key: value for key, value in card.items() if key != "active"},
                    "hits": hits,
                }
            )
    return matches
