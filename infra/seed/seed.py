"""Seed the admin user, default app settings, and mock brokers.

Idempotent — re-running is safe: the admin user is only created if absent,
settings are only inserted for missing keys (never clobbering admin edits),
brokers are upserted by code.

Run via `make seed` (== `uv run python infra/seed/seed.py` from repo root).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Allow `python infra/seed/seed.py` directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from voiceqa_shared.db_models import (
    AppSetting,
    Broker,
    EvalCriterion,
    ExtractionField,
    IndustryTerm,
    Project,
    TxnSourceConfig,
    User,
)
from voiceqa_shared.passwords import hash_password

MAPPING_TEMPLATE = REPO_ROOT / "mocks" / "data" / "mapping_template.json"

# REST connector for the mock back-office (mocks/backoffice_api, :7880).
# When Quam shares the real API, edit this source in the UI — no code.
MOCK_API_SOURCE = {
    "name": "Mock Quam back-office API",
    "kind": "api",
    "config": {
        "base_url": "http://localhost:7880",
        "auth_kind": "api_key_header",
        "auth_header": "X-API-Key",
        "path_template": "/api/v1/trades?trade_date={date}",
        "pagination": {
            "page_param": "page",
            "size_param": "page_size",
            "page_size": 100,
            "items_field": "trades",
            "total_field": "total",
        },
        "timezone": "Asia/Hong_Kong",
        "field_mapping": {
            "ext_txn_id": "trade_ref",
            "executed_at": "exec_time",
            "ordered_at": "order_time",
            "broker_code": "ae_code",
            "client_account": "account_no",
            "client_name": "client_name",
            "stock_code": "stock_code",
            "stock_name": "stock_name",
            "side": "side",
            "quantity": "qty",
            "price": "price",
            "amount": "amount",
            "channel": "order_channel",
            "status": "status",
        },
        "side_values": {"buy": ["B", "BUY"], "sell": ["S", "SELL"]},
        "channel_values": {"phone": ["PHONE"], "online": ["INTERNET", "MOBILE"]},
        "status_filter": {"include": ["FILLED"]},
    },
    "api_key": "quam-mock-key",
}

# Starter HK-brokerage criteria (DESIGN.md Phase 2). `description` is the
# rubric fed verbatim to the evaluator — edit in the UI as Quam refines it.
SEED_CRITERIA = [
    {
        "key": "identity_verification",
        "name": "Client identity verified",
        "description": (
            "The broker must verify the caller's identity before accepting any order: "
            "full name plus account number (or at least an account suffix). Recognising "
            "the caller's voice alone does NOT count. Pass only if an explicit identity "
            "check happens before the first order is accepted."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "critical",
        "weight": 2.0,
        "sort_order": 1,
    },
    {
        "key": "order_readback",
        "name": "Order read back and confirmed",
        "description": (
            "Before submitting each order the broker must read back the complete details "
            "— stock name or code, buy/sell side, quantity, and price (or market order) — "
            "and obtain the client's explicit confirmation. Pass only if every order in "
            "the call was read back and confirmed."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "critical",
        "weight": 2.0,
        "sort_order": 2,
    },
    {
        "key": "no_unauthorized_advice",
        "name": "No unauthorised investment advice",
        "description": (
            "The broker must not give unsolicited investment advice, price predictions, "
            "or buy/sell recommendations. Factual information (current price, order "
            "status, product features) is allowed. Fail if the broker volunteers "
            "recommendations or predictions."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "critical",
        "weight": 2.0,
        "sort_order": 3,
    },
    {
        "key": "risk_disclosure",
        "name": "Risk disclosure where required",
        "description": (
            "If the client asks for an opinion, or the order involves derivatives or "
            "leveraged products, the broker must give an appropriate risk warning. For "
            "plain equity orders where no advice is sought, this criterion passes by "
            "default."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "warning",
        "weight": 1.0,
        "sort_order": 4,
    },
    {
        "key": "professional_conduct",
        "name": "Professional conduct",
        "description": (
            "The broker is courteous and professional throughout: a proper greeting "
            "identifying the firm, polite tone, no over-familiarity that compromises "
            "professionalism, and a proper closing. Score 1 (poor) to 5 (exemplary)."
        ),
        "category": "quality",
        "score_type": "scale_1_5",
        "severity": "info",
        "weight": 1.0,
        "sort_order": 5,
    },
]

# scope=trade fields are SYSTEM (locked): reconciliation depends on them.
SEED_FIELDS = [
    {"key": "stock_code", "label": "Stock code", "field_type": "string", "scope": "trade", "is_system": True, "sort_order": 1},
    {"key": "stock_name", "label": "Stock name", "field_type": "string", "scope": "trade", "is_system": True, "sort_order": 2},
    {"key": "side", "label": "Side", "field_type": "enum", "enum_options": ["buy", "sell", "amend", "cancel", "unknown"], "scope": "trade", "is_system": True, "sort_order": 3},
    {"key": "quantity", "label": "Quantity", "field_type": "number", "scope": "trade", "is_system": True, "sort_order": 4},
    {"key": "price", "label": "Price", "field_type": "number", "scope": "trade", "is_system": True, "sort_order": 5},
    {"key": "price_type", "label": "Price type", "field_type": "enum", "enum_options": ["market", "limit", "unknown"], "scope": "trade", "is_system": True, "sort_order": 6},
    {"key": "client_name", "label": "Client name", "field_type": "string", "scope": "trade", "is_system": True, "sort_order": 7},
    {"key": "client_account", "label": "Client account", "field_type": "string", "scope": "trade", "is_system": True, "sort_order": 8},
    # Call-scope starters — admins add more in the UI.
    {"key": "call_purpose", "label": "Call purpose", "field_type": "enum", "enum_options": ["place_order", "amend_or_cancel", "inquiry", "complaint", "other"], "scope": "call", "is_system": False, "sort_order": 10, "description": "The caller's primary purpose."},
    {"key": "complaint_mentioned", "label": "Complaint mentioned", "field_type": "boolean", "scope": "call", "is_system": False, "sort_order": 11, "description": "True if the client expresses dissatisfaction or complains."},
]

# Industry terms ship as a CSV (same file the admin UI's import accepts).
TERMS_CSV = REPO_ROOT / "mocks" / "data" / "industry_terms.csv"


def load_terms_csv() -> list[dict]:
    """Parse mocks/data/industry_terms.csv (aliases are pipe-separated)."""
    import csv

    if not TERMS_CSV.exists():
        return []
    rows = []
    with TERMS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "category": row["category"].strip(),
                    "canonical": row["canonical"].strip(),
                    "stock_code": row["stock_code"].strip() or None,
                    "aliases": [a for a in row["aliases"].split("|") if a.strip()],
                    "notes": row["notes"].strip() or None,
                }
            )
    return rows

# Defaults match DESIGN.md §6/§8. Values here are inserted only when the key
# is missing, so admin edits survive re-seeding.
DEFAULT_SETTINGS: dict[str, object] = {
    "audio.broker_channel": "left",
    # ASR provider on noisy Cantonese telephony. Tencent's 16k_zh_en is the
    # "普方英大模型" and currently gives the best Quam test results. Existing
    # projects keep their saved setting; this default only applies to new seeds.
    "asr.provider": "tencent",
    "asr.model": "16k_zh_en",
    "asr.language_mode": "yue-Hant-HK",
    # Industry terms passed to the ASR as a glossary hint. Safe for Gemini (a
    # prompt hint); on chirp use with care (high boost degrades output).
    "asr.adaptation": "stock_only",
    "asr.adaptation_boost": 5,
    "asr.mono_speaker_repair": True,
    "asr.mono_speaker_repair_model": "gemini-3.5-flash",
    "llm.model": "gemini-3.5-flash",
    # Matches the mock recorder convention (mocks/README.md, contract 3).
    "filename.parse_regex": (
        r"^(?P<broker_ext>\d{4})_(?P<date>\d{8})_(?P<time>\d{6})"
        r"_(?P<direction>IN|OUT)_(?P<caller>\d+)\.wav$"
    ),
    "retention.days": 365,
    "recon.weights": {
        "stock": 0.35,
        "side": 0.15,
        "quantity": 0.20,
        "price": 0.10,
        "client": 0.15,
        "time": 0.05,
    },
    "recon.thresholds": {"auto_match": 0.75, "needs_review": 0.45},
    "recon.time_window": {"before_hours": 6, "after_minutes": 15},
    "recon.phone_only": True,
    "recon.transaction_filters": {
        "order_statuses": [
            "已委託",
            "成交",
            "部分成交",
            "已過期",
            "待報",
            "已撤單",
            "待報（保價）",
            "已修改",
            "待報（條件單）",
            "已拒絕",
        ],
        "execution_types": [
            "",
            "TradeExec",
            "NewExec",
            "ExpiredExec",
            "ReplaceExec",
            "CanceledExec",
        ],
    },
    "budget.llm_daily_tokens": 10_000_000,
    "budget.stt_daily_seconds": 180_000,
}

# Mirrors mocks/data/brokers.csv — the golden-day fixture's AE codes.
SEED_BROKERS = [
    ("AE012", "Alex Cheung", ["2012"]),
    ("AE015", "Bonnie Ho", ["2015"]),
    ("AE020", "Carmen Lau", ["2020"]),
]


async def seed() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL not set; run `make bootstrap` first")
    # Accept a plain managed-Postgres URL — force the asyncpg driver.
    for _prefix in ("postgresql://", "postgres://"):
        if db_url.startswith(_prefix):
            db_url = "postgresql+asyncpg://" + db_url[len(_prefix) :]
            break

    admin_email = os.environ.get("SEED_ADMIN_EMAIL", "admin@local.test")
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD", "voiceqa-admin-1")

    engine = create_async_engine(db_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with SessionLocal() as session:
            # --- Admin user --------------------------------------------------
            user = (
                await session.execute(select(User).where(User.email == admin_email))
            ).scalar_one_or_none()
            if user is None:
                user = User(
                    id=uuid.uuid4(),
                    email=admin_email,
                    name="Admin",
                    role="admin",
                    password_hash=hash_password(admin_password),
                    email_verified=datetime.now(UTC),
                )
                session.add(user)
                created_user = True
            else:
                created_user = False

            # --- Default project --------------------------------------------
            # Config (settings/criteria/fields/terms) is scoped to a project.
            # Use the existing default if present (e.g. the backfilled one),
            # else create a generic "Default" project for a fresh install.
            project = (
                await session.execute(
                    select(Project).where(Project.is_default.is_(True)).limit(1)
                )
            ).scalar_one_or_none()
            if project is None:
                project = (
                    await session.execute(select(Project).order_by(Project.created_at).limit(1))
                ).scalar_one_or_none()
            if project is None:
                project = Project(slug="default", name="Default", is_default=True)
                session.add(project)
                await session.flush()
            pid = project.id

            # --- Default settings (insert-if-missing) ------------------------
            existing_keys = set(
                (
                    await session.execute(
                        select(AppSetting.key).where(AppSetting.project_id == pid)
                    )
                ).scalars().all()
            )
            created_settings = 0
            for key, value in DEFAULT_SETTINGS.items():
                if key not in existing_keys:
                    session.add(AppSetting(project_id=pid, key=key, value=value))
                    created_settings += 1

            # --- Brokers ------------------------------------------------------
            created_brokers = 0
            for code, name, extensions in SEED_BROKERS:
                broker = await session.get(Broker, code)
                if broker is None:
                    session.add(Broker(code=code, name=name, phone_extensions=extensions))
                    created_brokers += 1

            # --- Industry terms (insert-if-missing by canonical) --------------
            terms = load_terms_csv()
            existing_terms = set(
                (
                    await session.execute(
                        select(IndustryTerm.canonical).where(IndustryTerm.project_id == pid)
                    )
                ).scalars().all()
            )
            created_terms = 0
            for t in terms:
                if t["canonical"] not in existing_terms:
                    session.add(IndustryTerm(project_id=pid, **t))
                    created_terms += 1

            # --- Evaluation criteria + extraction fields (insert-if-missing) --
            existing_criteria = set(
                (
                    await session.execute(
                        select(EvalCriterion.key).where(EvalCriterion.project_id == pid)
                    )
                ).scalars().all()
            )
            created_criteria = 0
            for c in SEED_CRITERIA:
                if c["key"] not in existing_criteria:
                    session.add(EvalCriterion(project_id=pid, **c))
                    created_criteria += 1

            existing_fields = set(
                (
                    await session.execute(
                        select(ExtractionField.key).where(ExtractionField.project_id == pid)
                    )
                ).scalars().all()
            )
            created_fields = 0
            for f in SEED_FIELDS:
                if f["key"] not in existing_fields:
                    session.add(ExtractionField(project_id=pid, **f))
                    created_fields += 1

            # --- Transaction sources (insert-if-missing by name) --------------
            from voiceqa_shared.crypto import encrypt_str

            existing_sources = set(
                (await session.execute(select(TxnSourceConfig.name))).scalars().all()
            )
            created_sources = 0
            import json as _json

            # Load every mapping_template*.json (mock schema + real broker exports).
            for tpl_path in sorted(MAPPING_TEMPLATE.parent.glob("mapping_template*.json")):
                template = _json.loads(tpl_path.read_text(encoding="utf-8"))
                if template["name"] not in existing_sources:
                    session.add(
                        TxnSourceConfig(
                            name=template["name"],
                            kind=template["kind"],
                            config=template["config"],
                        )
                    )
                    created_sources += 1
            if MOCK_API_SOURCE["name"] not in existing_sources:
                session.add(
                    TxnSourceConfig(
                        name=MOCK_API_SOURCE["name"],
                        kind=MOCK_API_SOURCE["kind"],
                        config=MOCK_API_SOURCE["config"],
                        credentials_enc=encrypt_str(MOCK_API_SOURCE["api_key"]),
                    )
                )
                created_sources += 1

            await session.commit()

        print(
            f"seed: ok\n"
            f"  admin     {admin_email}  ({'created' if created_user else 'existing'})\n"
            f"  settings  {created_settings} inserted, "
            f"{len(DEFAULT_SETTINGS) - created_settings} already present\n"
            f"  brokers   {created_brokers} inserted, "
            f"{len(SEED_BROKERS) - created_brokers} already present\n"
            f"  terms     {created_terms} inserted, "
            f"{len(terms) - created_terms} already present\n"
            f"  criteria  {created_criteria} inserted, "
            f"{len(SEED_CRITERIA) - created_criteria} already present\n"
            f"  fields    {created_fields} inserted, "
            f"{len(SEED_FIELDS) - created_fields} already present\n"
            f"  sources   {created_sources} inserted"
        )
        if created_user:
            print(f"  password  {admin_password!r}  (from SEED_ADMIN_PASSWORD — change in prod)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
