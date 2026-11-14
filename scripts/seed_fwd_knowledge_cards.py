"""Import the FWD workbook's knowledge cards without running ASR or evaluation."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from voiceqa_shared.db_models import KnowledgeCard, KnowledgeFaq, Project
from voiceqa_shared.knowledge_cards import parse_card_workbook, parse_faq_workbook

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--slug", default="fwd-insurance-demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cards = parse_card_workbook(args.workbook.read_bytes())
    faqs = parse_faq_workbook(args.workbook.read_bytes(), required=False)
    if args.dry_run:
        print(
            f"Found {len(cards)} cards, {len(faqs)} FAQs and {sum(len(card['trigger_words']) for card in cards)} triggers"
        )
        return
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    with create_engine(url).begin() as connection, Session(bind=connection) as session:
        project_id = session.execute(
            select(Project.id).where(Project.slug == args.slug)
        ).scalar_one_or_none()
        if project_id is None:
            raise SystemExit(f"Project not found: {args.slug}")
        for faq in faqs:
            statement = insert(KnowledgeFaq).values(project_id=project_id, **faq)
            session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_knowledge_faqs_project_code",
                    set_={
                        key: getattr(statement.excluded, key)
                        for key in ("category", "question", "answer", "source", "demo_notice")
                    }
                    | {"active": True, "updated_at": datetime.now(UTC)},
                )
            )
        for card in cards:
            statement = insert(KnowledgeCard).values(project_id=project_id, **card)
            session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_knowledge_cards_project_code",
                    set_={
                        "title": statement.excluded.title,
                        "trigger_words": statement.excluded.trigger_words,
                        "content": statement.excluded.content,
                        "active": True,
                        "updated_at": datetime.now(UTC),
                    },
                )
            )
        session.flush()
        session.commit()
    print(f"Imported {len(cards)} knowledge cards and {len(faqs)} FAQs into {args.slug}")


if __name__ == "__main__":
    main()
