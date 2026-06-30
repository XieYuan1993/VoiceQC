"""SQLAlchemy 2.0 declarative models — single source of truth.

Both apps/api and apps/worker import from here. Alembic's autogenerate
walks these classes when running `make makemigration`.

Conventions (ported from Voicebot-Platform):
- snake_case Python attributes; for the four Auth.js-managed tables, the
  column NAME is camelCase to satisfy `@auth/pg-adapter`'s hardcoded SQL.
- UUID PKs default to gen_random_uuid() server-side (pgcrypto).
- Postgres ENUM types are created in migrations; models reference them by
  name with create_type=False to avoid duplicate CREATE TYPE on autogen.
- Flat projects: a `projects` table scopes recordings + evaluation config;
  RBAC stays a global `users.role` (all users may access all projects).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint/index names — keeps Alembic diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---------------------------------------------------------------------------
# Postgres ENUM type references (definitions live in migrations).
# ---------------------------------------------------------------------------

USER_ROLES = ("admin", "compliance_manager", "reviewer", "broker", "auditor")

user_role_enum = ENUM(*USER_ROLES, name="user_role", create_type=False)
batch_status_enum = ENUM(
    "open",
    "processing",
    "completed",
    "completed_with_errors",
    "failed",
    name="batch_status",
    create_type=False,
)
# `evaluating` joins the flow in Phase 2; Phase 1 goes transcribing -> completed.
recording_status_enum = ENUM(
    "uploaded",
    "converting",
    "transcribing",
    "evaluating",
    "completed",
    "failed",
    name="recording_status",
    create_type=False,
)


def _now() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Auth.js v5 (@auth/pg-adapter) — exact camelCase column names required.
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    email_verified: Mapped[datetime | None] = mapped_column(
        "emailVerified",
        DateTime(timezone=True),
    )
    image: Mapped[str | None] = mapped_column(Text)

    # VoiceQA additions (not part of Auth.js's required schema):
    # NULL password_hash = SSO-only account (Phase 4).
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(
        user_role_enum,
        nullable=False,
        server_default=text("'reviewer'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = _now()


class Account(Base):
    """OAuth provider rows (Entra ID, Phase 4). Auth.js manages this table."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        "userId",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[str] = mapped_column(
        "providerAccountId",
        Text,
        nullable=False,
    )
    refresh_token: Mapped[str | None] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[int | None] = mapped_column(BigInteger)
    id_token: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    session_state: Mapped[str | None] = mapped_column(Text)
    token_type: Mapped[str | None] = mapped_column(Text)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        "userId",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    session_token: Mapped[str] = mapped_column(
        "sessionToken",
        Text,
        nullable=False,
        unique=True,
    )


class VerificationToken(Base):
    """Auth.js spells the table singular: `verification_token`."""

    __tablename__ = "verification_token"

    identifier: Mapped[str] = mapped_column(Text, primary_key=True)
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token: Mapped[str] = mapped_column(Text, primary_key=True)


# ---------------------------------------------------------------------------
# Local-credential support.
# ---------------------------------------------------------------------------


class PasswordResetToken(Base):
    """Single-use, expiring reset tokens. Only the sha256 of the token is stored."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_password_reset_tokens_user_id", "user_id"),)


# ---------------------------------------------------------------------------
# Projects — flat workspaces that scope recordings + evaluation config.
# RBAC stays global (users.role); all users may access all projects.
# ---------------------------------------------------------------------------


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Optional feature modules, e.g. {"trade_reconciliation": true}.
    modules: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    # Free-text domain/context for the evaluator prompt — replaces the old
    # hard-coded "Hong Kong securities brokerage" preamble.
    eval_prompt_context: Mapped[str | None] = mapped_column(Text)
    # UI branding (accent colour, etc.) for the redesigned dashboard.
    branding: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # At most one project is the default (partial unique index).
    __table_args__ = (
        Index(
            "uq_projects_is_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


# ---------------------------------------------------------------------------
# Brokers (AE codes) — bridges txn broker_code ↔ recorder extensions, and
# scopes the `broker` role to its own calls via user_broker_codes.
# ---------------------------------------------------------------------------


class Broker(Base):
    __tablename__ = "brokers"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_extensions: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = _now()


class UserBrokerCode(Base):
    """Maps a `broker`-role user to the AE code(s) whose calls they may see."""

    __tablename__ = "user_broker_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    broker_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("brokers.code", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = _now()


# ---------------------------------------------------------------------------
# Evaluation config (Phase 2): criteria + extraction fields are admin-edited
# and drive both the Gemini prompt AND its response schema. Evaluations
# snapshot the config they ran under (no version tables — see DESIGN.md §5).
# ---------------------------------------------------------------------------


class EvalCriterion(Base):
    __tablename__ = "eval_criteria"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # The rubric — fed verbatim to the evaluator prompt.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'compliance'")
    )  # compliance | quality
    score_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pass_fail'")
    )  # pass_fail | scale_1_5
    severity: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'warning'")
    )  # info | warning | critical
    weight: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_eval_criteria_project_id_key"),
        Index("ix_eval_criteria_project_id", "project_id"),
    )


class ExtractionField(Base):
    """What to pull out of each call. scope=trade fields are system-seeded
    and locked (reconciliation depends on them); admins add call-scope
    fields on top."""

    __tablename__ = "extraction_fields"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    field_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'string'")
    )  # string | number | boolean | date | enum
    enum_options: Mapped[list[str] | None] = mapped_column(JSONB)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'call'"))
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_extraction_fields_project_id_key"),
        Index("ix_extraction_fields_project_id", "project_id"),
    )


class ChecklistItem(Base):
    """Required script/checklist items the agent must cover; the evaluator
    semantic-matches whether each was addressed in the call (no exact wording)."""

    __tablename__ = "checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)  # the required item / question
    description: Mapped[str | None] = mapped_column(Text)  # what counts as "covered"
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_checklist_items_project_id_key"),
        Index("ix_checklist_items_project_id", "project_id"),
    )


class KbDocument(Base):
    """A knowledge-base document (policy / product reference) for a project.
    Chunked + embedded by the worker so calls can be checked for answer
    correctness against it (RAG)."""

    __tablename__ = "kb_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)  # optional URL / filename
    content: Mapped[str] = mapped_column(Text, nullable=False)  # raw text, re-chunkable
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'processing'")
    )  # processing | ready | failed
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_kb_documents_project_id", "project_id"),)


class KbChunk(Base):
    """A chunk of a KbDocument with its embedding. Postgres here has no pgvector,
    so the embedding is a JSON float array and similarity is computed in Python
    over a small per-project KB."""

    __tablename__ = "kb_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kb_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(JSONB, nullable=False)  # list[float], 768-dim
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        Index("ix_kb_chunks_project_id", "project_id"),
        Index("ix_kb_chunks_document_id", "document_id"),
    )


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )  # pending | running | completed | failed
    llm_model: Mapped[str | None] = mapped_column(Text)
    criteria_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    fields_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    overall_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    risk_flags: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    extracted_call_fields: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    # Conversation analytics — customer-side sentiment, intent, topics, complaints
    # and follow-ups, produced by the same evaluation LLM call (no extra request).
    sentiment_label: Mapped[str | None] = mapped_column(Text)  # positive|neutral|negative|frustrated|mixed
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(3, 2))  # -1.00..1.00, customer
    customer_intent: Mapped[str | None] = mapped_column(Text)
    topics: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    is_complaint: Mapped[bool | None] = mapped_column(Boolean)
    complaint_category: Mapped[str | None] = mapped_column(Text)
    follow_up_actions: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    # Checklist / script-adherence — frozen items + per-item coverage + % covered.
    checklist_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    checklist_results: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    checklist_score: Mapped[float | None] = mapped_column(Numeric(5, 2))  # % required items covered
    # Answer correctness (RAG) — agent claims judged against the project knowledge base.
    correctness_findings: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    correctness_score: Mapped[float | None] = mapped_column(Numeric(5, 2))  # % checkable claims correct
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unreviewed'")
    )  # unreviewed | approved | overridden
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("recording_id", "run_seq", name="uq_evaluations_recording_id_run_seq"),
        Index("ix_evaluations_recording_id", "recording_id"),
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Copies, not FKs — results stay self-describing after criteria edits.
    criterion_key: Mapped[str] = mapped_column(Text, nullable=False)
    criterion_name: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    severity: Mapped[str | None] = mapped_column(Text)
    override_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    override_passed: Mapped[bool | None] = mapped_column(Boolean)
    override_note: Mapped[str | None] = mapped_column(Text)
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_evaluation_results_evaluation_id", "evaluation_id"),)


class TradeInstruction(Base):
    """LLM-extracted trade instructions — first-class because Phase-3
    reconciliation joins on them. One call may contain several."""

    __tablename__ = "trade_instructions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Normalized via industry_terms at persist time ("0700" -> "700").
    stock_code: Mapped[str | None] = mapped_column(Text)
    stock_name_raw: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unknown'")
    )  # buy | sell | amend | cancel | unknown
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 2))
    price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    price_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unknown'")
    )  # market | limit | unknown
    client_name_raw: Mapped[str | None] = mapped_column(Text)
    client_account_raw: Mapped[str | None] = mapped_column(Text)
    time_in_call_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    extra_fields: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    evidence_quote: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_trade_instructions_evaluation_id", "evaluation_id"),
        Index("ix_trade_instructions_recording_id", "recording_id"),
        Index("ix_trade_instructions_stock_code", "stock_code"),
    )


class LlmUsage(Base):
    """Daily token rollup per callsite/model — ported from Voicebot's
    gemini_usage, minus the org dimension (single-tenant)."""

    __tablename__ = "llm_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    callsite: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        UniqueConstraint("day", "callsite", "model", name="uq_llm_usage_day_callsite_model"),
    )


# ---------------------------------------------------------------------------
# Transactions + reconciliation (Phase 3).
# ---------------------------------------------------------------------------


class TxnSourceConfig(Base):
    """A way to get the day's trades: CSV/XLSX mapping template or REST API
    connector. config shape per kind documented in mocks/README.md."""

    __tablename__ = "txn_source_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # csv | api
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    config: Mapped[Any] = mapped_column(JSONB, nullable=False)
    # AES-256-GCM via voiceqa_shared.crypto (API keys, basic-auth passwords).
    credentials_enc: Mapped[str | None] = mapped_column(Text)
    schedule_cron: Mapped[str | None] = mapped_column(Text)
    last_pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TxnImport(Base):
    __tablename__ = "txn_imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("txn_source_configs.id", ondelete="SET NULL"),
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # csv_upload | api_pull
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    file_name: Mapped[str | None] = mapped_column(Text)
    # Raw uploaded file retained as evidence.
    gcs_uri: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )  # pending | processing | completed | failed
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    errors: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_txn_imports_trade_date", "trade_date"),)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("txn_imports.id", ondelete="CASCADE"),
        nullable=False,
    )
    ext_txn_id: Mapped[str | None] = mapped_column(Text)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    # When the order was placed (better recon anchor than execution time for
    # limit orders); falls back to executed_at when the source lacks it.
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    broker_code: Mapped[str | None] = mapped_column(Text)
    client_account: Mapped[str | None] = mapped_column(Text)
    client_name: Mapped[str | None] = mapped_column(Text)
    # Normalized, no leading zeros ("700").
    stock_code: Mapped[str | None] = mapped_column(Text)
    stock_name: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str] = mapped_column(Text, nullable=False)  # buy | sell
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 2))
    price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    channel: Mapped[str | None] = mapped_column(Text)  # phone | online | None=unknown
    raw: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))

    __table_args__ = (
        Index("ix_transactions_trade_date", "trade_date"),
        Index("ix_transactions_broker_code_executed_at", "broker_code", "executed_at"),
        Index("ix_transactions_stock_code_trade_date", "stock_code", "trade_date"),
        Index(
            "uq_transactions_ext_txn_id_trade_date",
            "ext_txn_id",
            "trade_date",
            unique=True,
            postgresql_where=text("ext_txn_id IS NOT NULL"),
        ),
    )


class ReconRun(Base):
    __tablename__ = "recon_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'running'")
    )  # running | completed | failed
    params_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    stats: Mapped[Any | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    started_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_recon_runs_trade_date", "trade_date"),)


class ReconItem(Base):
    """One row per reconciliation finding. The three requirement scenarios:
    matched / txn_no_recording / recording_no_txn."""

    __tablename__ = "recon_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recon_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)  # info | suspicious | breach
    # SET NULL so historical runs survive re-imports / deletions.
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
    )
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="SET NULL"),
    )
    trade_instruction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trade_instructions.id", ondelete="SET NULL"),
    )
    score: Mapped[float | None] = mapped_column(Numeric(6, 4))
    score_breakdown: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    match_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unmatched'")
    )  # auto_matched | needs_review | unmatched | confirmed | rejected | manual_linked
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_recon_items_run_id_item_type", "run_id", "item_type"),
        Index("ix_recon_items_transaction_id", "transaction_id"),
        Index("ix_recon_items_recording_id", "recording_id"),
    )


# ---------------------------------------------------------------------------
# App settings + audit.
# ---------------------------------------------------------------------------


class SsoConfig(Base):
    """Azure AD / Microsoft Entra ID SSO — a single admin-edited config row.

    Stored in the DB (not env) so admins enable/configure SSO via the UI
    without a redeploy; apps/web's lazy NextAuth init reads this row and
    conditionally adds the Entra provider. The client secret is AES-256-GCM
    encrypted (voiceqa_shared.crypto / apps/web/src/lib/crypto.ts twin).
    """

    __tablename__ = "sso_config"

    # Enforced singleton: only id=1 ever exists.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=text("1"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    tenant_id: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(Text)
    client_secret_enc: Mapped[str | None] = mapped_column(Text)
    allowed_email_domains: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    # [{"group_id": "...", "role": "compliance_manager"}], first match wins.
    group_role_mappings: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    auto_provision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    default_role: Mapped[str] = mapped_column(
        user_role_enum, nullable=False, server_default=text("'reviewer'")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_sso_config_singleton"),)


class AppSetting(Base):
    """Key/value config edited by admins (recon weights, filename regex, ...).

    Each key's value shape is validated by a per-key pydantic model at the
    API layer; the table itself is schemaless JSONB.
    """

    __tablename__ = "app_settings"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# Ingest pipeline (Phase 1): batches -> recordings -> transcripts.
# ---------------------------------------------------------------------------


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(Text)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        batch_status_enum,
        nullable=False,
        server_default=text("'open'"),
    )
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = _now()
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_upload_batches_project_id", "project_id"),)


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("upload_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Nullable so retention can purge the audio (NULL = audio purged); the
    # raw uri is always set at ingest time.
    gcs_uri_raw: Mapped[str | None] = mapped_column(Text)
    gcs_uri_broker: Mapped[str | None] = mapped_column(Text)
    gcs_uri_customer: Mapped[str | None] = mapped_column(Text)
    gcs_uri_mono: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(10, 2))
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str | None] = mapped_column(Text)
    # Parsed from the filename via app_settings filename.parse_regex.
    call_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    broker_ext: Mapped[str | None] = mapped_column(Text)
    caller_number: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unknown'"))
    language_mode: Mapped[str | None] = mapped_column(Text)
    # Client identity as stated IN the call (extracted by the evaluator) — the
    # telephony metadata often lacks it. Denormalized here for display/search.
    client_name: Mapped[str | None] = mapped_column(Text)
    client_account: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        recording_status_enum,
        nullable=False,
        server_default=text("'uploaded'"),
    )
    failed_stage: Mapped[str | None] = mapped_column(Text)  # convert|stt|eval|budget
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    stt_operation_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("batch_id", "sha256", name="uq_recordings_batch_id_sha256"),
        Index("ix_recordings_project_id", "project_id"),
        Index("ix_recordings_batch_id", "batch_id"),
        Index("ix_recordings_status", "status"),
        Index("ix_recordings_call_started_at", "call_started_at"),
        Index("ix_recordings_broker_ext_call_started_at", "broker_ext", "call_started_at"),
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    stt_model: Mapped[str] = mapped_column(Text, nullable=False)
    language_detected: Mapped[str | None] = mapped_column(Text)
    # Channel-tagged, time-interleaved plain text. Trigram GIN index (in the
    # migration) — Postgres FTS tokenizes Chinese poorly, trigram substring
    # search is the pragmatic choice.
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    billed_seconds: Mapped[float | None] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = _now()


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_role: Mapped[str] = mapped_column(Text, nullable=False)  # broker|customer|mixed
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("ix_transcript_segments_transcript_id_start_ms", "transcript_id", "start_ms"),)


# ---------------------------------------------------------------------------
# Industry terms — consumed by STT adaptation, the LLM glossary (Phase 2),
# and the recon alias resolver (Phase 3).
# ---------------------------------------------------------------------------


class IndustryTerm(Base):
    __tablename__ = "industry_terms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)  # stock|jargon|person|other
    canonical: Mapped[str] = mapped_column(Text, nullable=False)
    # Normalized, no leading zeros ("700"), stocks only.
    stock_code: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    boost: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("project_id", "canonical", name="uq_industry_terms_project_id_canonical"),
        Index("ix_industry_terms_stock_code", "stock_code"),
        Index("ix_industry_terms_project_id", "project_id"),
    )


class SttUsage(Base):
    """Daily audio-seconds rollup per provider/model — budget guard input."""

    __tablename__ = "stt_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    audio_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (UniqueConstraint("day", "provider", "model", name="uq_stt_usage_day_provider_model"),)


class AuditLog(Base):
    """Append-only audit trail — mutations AND sensitive reads.

    No update/delete path exists in the app by design; even admins only read.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = _now()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    # Kept even if the user row is later deleted.
    actor_email: Mapped[str | None] = mapped_column(Text)
    # Verb-object, e.g. auth.login_failed, recording.play_audio, criteria.update
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[Any | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_user_id_occurred_at", "user_id", "occurred_at"),
        Index("ix_audit_log_object_type_object_id", "object_type", "object_id"),
    )
