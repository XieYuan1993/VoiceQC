"""Seed the FWD demo speech-adaptation glossary from its scenario workbook."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openpyxl import load_workbook
from sqlalchemy import MetaData, create_engine, delete, insert, select, update

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

CARD_ID_RE = re.compile(r"^K\d+$", re.IGNORECASE)
SEPARATORS_RE = re.compile(r"[\u3001,\uff0c;/\uff1b\n]+")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SeedTerm:
    canonical: str
    category: str = "jargon"
    boost: float = 7
    notes: str | None = None


def _sync_dsn(value: str) -> str:
    return value.replace("+asyncpg", "+psycopg").replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


def _clean(value: object) -> str:
    return SPACE_RE.sub(" ", str(value or "").strip())


def _add(terms: dict[str, SeedTerm], term: SeedTerm) -> None:
    value = _clean(term.canonical).strip("-\u2014")
    if len(value) < 2 or value.replace(" ", "").isdigit():
        return
    current = terms.get(value)
    if current is None or term.boost > current.boost:
        terms[value] = SeedTerm(value, term.category, term.boost, term.notes)


def extract_terms(workbook_path: Path) -> list[SeedTerm]:
    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    required = {"场景清单", "热词修复演示集", "知识卡片清单", "产品资料"}
    missing = sorted(required.difference(workbook.sheetnames))
    if missing:
        raise ValueError(f"workbook is missing sheets: {', '.join(missing)}")

    terms: dict[str, SeedTerm] = {}
    _add(terms, SeedTerm("富衛", boost=11, notes="FWD brand hotword"))
    _add(terms, SeedTerm("富衛保險", boost=11, notes="FWD brand phrase"))

    product_sheet = workbook["产品资料"]
    for row in product_sheet.iter_rows(min_row=2, values_only=True):
        product_name = _clean(row[1] if len(row) > 1 else None)
        if product_name:
            _add(
                terms,
                SeedTerm(product_name, boost=9, notes="FWD product name"),
            )

    card_sheet = workbook["知识卡片清单"]
    for row in card_sheet.iter_rows(min_row=2, values_only=True):
        card_id = _clean(row[0] if row else None)
        if not CARD_ID_RE.fullmatch(card_id):
            continue
        triggers = _clean(row[2] if len(row) > 2 else None)
        for trigger in SEPARATORS_RE.split(triggers):
            trigger = trigger.strip()
            if trigger:
                _add(
                    terms,
                    SeedTerm(trigger, boost=7, notes=f"FWD knowledge trigger {card_id}"),
                )

    scene_sheet = workbook["场景清单"]
    for row in scene_sheet.iter_rows(min_row=2, values_only=True):
        source_path = _clean(row[11] if len(row) > 11 else None)
        agent_name = source_path.split("/", 1)[0].strip() if "/" in source_path else ""
        if agent_name:
            category = "person" if " " in agent_name else "jargon"
            _add(
                terms,
                SeedTerm(
                    agent_name,
                    category=category,
                    boost=8,
                    notes="FWD demo agent" if category == "person" else "FWD hotline term",
                ),
            )

    # The hotword sheet contains known *wrong* ASR spellings. Deliberately do
    # not add those spellings: Tencent would otherwise be encouraged to emit
    # the errors we are trying to repair. The canonical brand terms above are
    # the positive adaptation phrases.
    return sorted(terms.values(), key=lambda item: (-item.boost, item.category, item.canonical))


def extract_correction_rules(workbook_path: Path) -> list[dict[str, str]]:
    """Turn the workbook's observed bad brand spellings into contextual LLM hints."""
    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    sheet = workbook["热词修复演示集"]
    contexts_by_wrong: dict[str, list[str]] = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        wrong = _clean(row[6] if len(row) > 6 else None)
        if not wrong:
            continue
        language = _clean(row[2] if len(row) > 2 else None)
        hotline = _clean(row[3] if len(row) > 3 else None)
        example = _clean(row[5] if len(row) > 5 else None)
        kind = _clean(row[7] if len(row) > 7 else None)
        context = "; ".join(
            value
            for value in (
                f"{language} {hotline} opening greeting".strip(),
                kind,
                f"observed: {example}" if example else "",
            )
            if value
        )
        values = contexts_by_wrong.setdefault(wrong, [])
        if context and context not in values and len(values) < 3:
            values.append(context)
    return [
        {
            "wrong": wrong,
            "correct": "富衛",
            "context": " | ".join(contexts_by_wrong[wrong]),
        }
        for wrong in sorted(contexts_by_wrong)
    ]


def seed(database_url: str, slug: str, workbook_path: Path, *, dry_run: bool = False) -> None:
    terms = extract_terms(workbook_path)
    correction_rules = extract_correction_rules(workbook_path)
    if dry_run:
        for term in terms:
            print(f"{term.category:7} {term.boost:>4.1f} {term.canonical}")
        print(f"Would seed {len(terms)} terms and {len(correction_rules)} correction rules")
        return

    engine = create_engine(_sync_dsn(database_url), pool_pre_ping=True)
    metadata = MetaData()
    metadata.reflect(bind=engine, only=("projects", "industry_terms", "app_settings"))
    projects = metadata.tables["projects"]
    industry_terms = metadata.tables["industry_terms"]
    app_settings = metadata.tables["app_settings"]

    created = updated = 0
    with engine.begin() as connection:
        project_id = connection.execute(
            select(projects.c.id).where(projects.c.slug == slug)
        ).scalar_one_or_none()
        if project_id is None:
            raise ValueError(f"project not found: {slug}")

        existing = {
            row.canonical: row.id
            for row in connection.execute(
                select(industry_terms.c.id, industry_terms.c.canonical).where(
                    industry_terms.c.project_id == project_id
                )
            )
        }
        for term in terms:
            values = {
                "category": term.category,
                "stock_code": None,
                "aliases": [],
                "boost": term.boost,
                "active": True,
                "notes": term.notes,
            }
            term_id = existing.get(term.canonical)
            if term_id is None:
                connection.execute(
                    insert(industry_terms).values(
                        project_id=project_id,
                        canonical=term.canonical,
                        **values,
                    )
                )
                created += 1
            else:
                connection.execute(
                    update(industry_terms).where(industry_terms.c.id == term_id).values(**values)
                )
                updated += 1

        correction_key = "asr.post_correction_replacements"
        connection.execute(
            delete(app_settings).where(
                app_settings.c.project_id == project_id,
                app_settings.c.key == correction_key,
            )
        )
        connection.execute(
            insert(app_settings).values(
                project_id=project_id,
                key=correction_key,
                value=correction_rules,
            )
        )

    print(
        f"FWD glossary ready: {created} created, {updated} updated "
        f"({len(terms)} terms, {len(correction_rules)} correction rules)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--slug", default="fwd-insurance-demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url and not args.dry_run:
        raise SystemExit("DATABASE_URL is required")
    seed(database_url, args.slug, args.workbook, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
