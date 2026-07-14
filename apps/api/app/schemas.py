"""Pydantic request/response schemas (Phase 0)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

# Login/reset lookups deliberately use plain `str` emails, not EmailStr:
# the DB row is the source of truth, and strict RFC validators reject
# reserved dev/test domains like admin@local.test.


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None
    role: str


class VerifyCredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class VerifyCredentialsResponse(BaseModel):
    """Shape consumed by apps/web's Auth.js Credentials authorize()."""

    id: uuid.UUID
    email: str
    name: str | None
    role: str
    session_version: int


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=1, max_length=1024)


class SsoStatusResponse(BaseModel):
    enabled: bool


# --- Phase 1: batches / recordings / transcripts ---------------------------


class BatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    trade_date: date


class BatchCounts(BaseModel):
    uploaded: int = 0
    converting: int = 0
    transcribing: int = 0
    evaluating: int = 0
    completed: int = 0
    failed: int = 0


class BatchOut(BaseModel):
    id: uuid.UUID
    name: str | None
    trade_date: date
    status: str
    total_files: int
    created_at: datetime
    finalized_at: datetime | None
    last_run_at: datetime | None = None
    counts: BatchCounts | None = None


class BatchListOut(BaseModel):
    items: list[BatchOut]
    total: int
    page: int
    page_size: int


class UploadFileResult(BaseModel):
    filename: str
    kind: str  # audio | zip
    recording_id: uuid.UUID | None = None
    duplicate: bool = False
    size_bytes: int


class DirectUploadInit(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(ge=1)
    content_type: str | None = Field(default=None, max_length=200)


class DirectUploadInitOut(BaseModel):
    upload_id: str
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str]
    expires_in_seconds: int
    filename: str
    kind: str
    size_bytes: int


class DirectUploadComplete(BaseModel):
    upload_id: str = Field(min_length=1, max_length=2000)
    filename: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(ge=1)
    sha256: str | None = Field(default=None, pattern="^[a-fA-F0-9]{64}$")


class RetryResult(BaseModel):
    retried: int


class BatchSttRerunIn(BaseModel):
    asr_provider: str = Field(pattern="^(tencent|qwen|google|gemini)$")
    asr_model: str | None = Field(default=None, min_length=1, max_length=200)
    auto_retry_limit: int = Field(default=2, ge=0, le=5)


class BulkBatchSttRerunOut(BaseModel):
    queued: int
    batches: int
    skipped_active: int
    skipped_no_audio: int


class RecordingOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    original_filename: str
    status: str
    failed_stage: str | None
    error: str | None
    duration_seconds: float | None
    broker_ext: str | None
    broker_name: str | None = None
    caller_number: str | None
    client_name: str | None = None
    client_account: str | None = None
    direction: str
    call_started_at: datetime | None
    language_mode: str | None
    has_transcript: bool = False
    overall_score: float | None = None  # latest completed eval's overall QA score
    created_at: datetime


class RecordingDetail(RecordingOut):
    sha256: str
    size_bytes: int
    sample_rate: int | None
    channels: int | None
    format: str | None


class RecordingListOut(BaseModel):
    items: list[RecordingOut]
    total: int
    page: int
    page_size: int


class RecordingReevaluateIn(BaseModel):
    recording_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class SegmentOut(BaseModel):
    channel_role: str
    start_ms: int
    end_ms: int
    text: str
    language: str | None
    confidence: float | None


class TranscriptOut(BaseModel):
    recording_id: uuid.UUID
    stt_model: str
    language_detected: str | None
    billed_seconds: float | None
    full_text: str
    segments: list[SegmentOut]


# --- Phase 1: industry terms + settings -------------------------------------


class TermIn(BaseModel):
    category: str = Field(pattern="^(stock|jargon|person|other)$")
    canonical: str = Field(min_length=1, max_length=200)
    stock_code: str | None = None
    aliases: list[str] = Field(default_factory=list)
    boost: float | None = Field(default=None, ge=0, le=20)
    active: bool = True
    notes: str | None = None


class TermOut(TermIn):
    id: uuid.UUID
    created_at: datetime


class TermImportResult(BaseModel):
    created: int
    updated: int


class SettingOut(BaseModel):
    key: str
    value: Any
    updated_at: datetime | None = None


class SettingPut(BaseModel):
    value: Any


# --- Phase 2: evaluation config + results -----------------------------------


class CriterionIn(BaseModel):
    key: str = Field(pattern="^[a-z0-9_]{1,64}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    category: str = Field(default="compliance", pattern="^(compliance|quality)$")
    score_type: str = Field(default="pass_fail", pattern="^(pass_fail|scale_1_5)$")
    severity: str = Field(default="warning", pattern="^(info|warning|critical)$")
    weight: float = Field(default=1.0, ge=0, le=10)
    active: bool = True
    sort_order: int = 0


class CriterionOut(CriterionIn):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class FieldIn(BaseModel):
    key: str = Field(pattern="^[a-z0-9_]{1,64}$")
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    field_type: str = Field(default="string", pattern="^(string|number|boolean|date|enum)$")
    enum_options: list[str] | None = None
    scope: str = Field(default="call", pattern="^(call|trade)$")
    active: bool = True
    sort_order: int = 0


class FieldOut(FieldIn):
    id: uuid.UUID
    is_system: bool
    created_at: datetime


class ChecklistItemIn(BaseModel):
    key: str = Field(pattern="^[a-z0-9_]{1,64}$")
    label: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    required: bool = True
    active: bool = True
    sort_order: int = 0


class ChecklistItemOut(ChecklistItemIn):
    id: uuid.UUID
    created_at: datetime


class KbDocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=1, max_length=200_000)


class KbDocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    source: str | None
    status: str  # processing | ready | failed
    chunk_count: int
    error: str | None
    char_count: int
    created_at: datetime


class KbDocumentDetailOut(KbDocumentOut):
    content: str


class KbDocumentPatchIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    source: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)


class KbRetrieveIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class KbRetrievalHit(BaseModel):
    seq: int
    content: str
    score: float


class KbRetrieveOut(BaseModel):
    hits: list[KbRetrievalHit]


class EvidenceOut(BaseModel):
    quote: str
    channel: str
    approx_ms: int | None = None


class ResultOut(BaseModel):
    criterion_key: str
    criterion_name: str
    score: float | None
    passed: bool | None
    rationale: str | None
    evidence: list[EvidenceOut]
    severity: str | None
    override_score: float | None = None
    override_passed: bool | None = None
    override_note: str | None = None
    overridden_at: datetime | None = None


class TradeOut(BaseModel):
    id: uuid.UUID
    seq: int
    stock_code: str | None
    stock_name_raw: str | None
    side: str
    quantity: float | None
    price: float | None
    price_type: str
    client_name_raw: str | None
    client_account_raw: str | None
    time_in_call_ms: int | None
    confidence: float | None
    evidence_quote: str | None


class EvaluationOut(BaseModel):
    id: uuid.UUID
    recording_id: uuid.UUID
    run_seq: int
    status: str
    llm_model: str | None
    summary: str | None
    overall_score: float | None
    risk_flags: list[dict[str, Any]]
    extracted_call_fields: dict[str, Any]
    sentiment_label: str | None
    sentiment_score: float | None
    customer_intent: str | None
    topics: list[str]
    is_complaint: bool | None
    complaint_category: str | None
    follow_up_actions: list[str]
    criteria_snapshot: list[dict[str, Any]]
    fields_snapshot: list[dict[str, Any]]
    checklist_snapshot: list[dict[str, Any]]
    checklist_results: list[dict[str, Any]]
    checklist_score: float | None
    correctness_findings: list[dict[str, Any]]
    correctness_score: float | None
    review_status: str
    review_note: str | None
    reviewed_at: datetime | None
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime
    completed_at: datetime | None
    results: list[ResultOut]
    trades: list[TradeOut]


class EvalRerunOut(BaseModel):
    recording_id: uuid.UUID
    status: str


class ReviewIn(BaseModel):
    action: str = Field(pattern="^(approve|override)$")
    note: str | None = Field(default=None, max_length=2000)


class ResultOverrideIn(BaseModel):
    passed: bool | None = None
    score: float | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=2000)


# --- Insights / management analytics ----------------------------------------


class LabelCount(BaseModel):
    label: str
    count: int


class TrendPoint(BaseModel):
    date: str  # YYYY-MM-DD
    calls: int
    complaints: int
    avg_sentiment: float | None


class AnalyticsOut(BaseModel):
    evaluated_calls: int
    analyzed_calls: int  # calls whose latest run carries conversation analytics
    avg_sentiment: float | None
    sentiment: list[LabelCount]
    complaint_count: int
    complaint_rate: float
    complaint_categories: list[LabelCount]
    top_topics: list[LabelCount]
    top_intents: list[LabelCount]
    trend: list[TrendPoint]
    avg_adherence: float | None  # avg script-adherence % across analysed calls
    avg_correctness: float | None  # avg answer-accuracy % (KB-grounded)
    incorrect_answer_calls: int  # calls with >=1 answer the KB contradicts


class AgentTrendPoint(BaseModel):
    date: str  # YYYY-MM-DD
    calls: int
    avg_score: float | None


class AgentScorecard(BaseModel):
    agent: str
    calls: int
    avg_score: float | None
    avg_adherence: float | None
    avg_correctness: float | None
    complaint_rate: float
    incorrect_answer_calls: int
    trend: list[AgentTrendPoint] = []  # chronological daily avg score (sparkline)


class AgentSummary(BaseModel):
    agents: int
    calls: int
    team_avg_score: float | None  # call-weighted across agents
    in_review_queue: int


class AgentScorecardsOut(BaseModel):
    agents: list[AgentScorecard]
    summary: AgentSummary


class AgentDetailOut(AgentScorecard):
    name: str | None = None  # broker display name, if the extension maps to one


# --- Review queue -----------------------------------------------------------

# Reason keys an item can carry; mirrors recordings._attention_ids().
ReviewReason = str  # complaint | wrong_answer | critical_risk | low_adherence


class ReviewQueueItem(BaseModel):
    recording_id: uuid.UUID
    original_filename: str
    broker_ext: str | None
    direction: str
    call_started_at: datetime | None
    duration_seconds: float | None
    status: str
    overall_score: float | None
    reasons: list[str]


class ReviewQueueCounts(BaseModel):
    all: int
    complaint: int
    wrong_answer: int
    critical_risk: int
    low_adherence: int


class ReviewQueueOut(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    page: int
    page_size: int
    counts: ReviewQueueCounts


class BulkRerunOut(BaseModel):
    queued: int


# --- Phase 3: transactions + reconciliation ---------------------------------


class TxnOut(BaseModel):
    id: uuid.UUID
    ext_txn_id: str | None
    trade_date: date
    ordered_at: datetime | None
    executed_at: datetime | None
    broker_code: str | None
    client_account: str | None
    client_name: str | None
    stock_code: str | None
    stock_name: str | None
    side: str
    quantity: float | None
    price: float | None
    amount: float | None
    channel: str | None
    recon_status: str | None = None  # matched | needs_review | unmapped | not_run


class TxnListOut(BaseModel):
    items: list[TxnOut]
    total: int
    page: int
    page_size: int


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(pattern="^(csv|api)$")
    active: bool = True
    config: dict[str, Any]
    # Write-only: encrypted at rest, never returned.
    credential: str | None = Field(default=None, max_length=1000)
    schedule_cron: str | None = Field(default=None, max_length=100)


class SourceOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    active: bool
    config: dict[str, Any]
    has_credential: bool
    schedule_cron: str | None
    last_pulled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceTestOut(BaseModel):
    ok: bool
    detail: str
    sample: list[dict[str, Any]] = Field(default_factory=list)


class ImportOut(BaseModel):
    id: uuid.UUID
    source_config_id: uuid.UUID | None
    kind: str
    trade_date: date
    file_name: str | None
    status: str
    row_count: int
    imported_count: int
    skipped_count: int
    errors: list[Any]
    created_at: datetime
    completed_at: datetime | None


class DryRunOut(BaseModel):
    rows_total: int
    importable: int
    skipped_status: int
    skipped_side: int
    skipped_duplicate: int = 0
    trade_dates: list[str] = []  # distinct per-row dates detected in the file
    preview: list[dict[str, Any]]


class SkippedRowOut(BaseModel):
    reason: str  # duplicate | side | status
    ext_txn_id: str | None = None
    stock_code: str | None = None
    side: str | None = None
    quantity: float | None = None
    raw: dict[str, str]


class ReconTransactionFilters(BaseModel):
    order_statuses: list[str]
    execution_types: list[str]


class ReconRunCreate(BaseModel):
    trade_date: date | None = None
    trade_date_from: date | None = None
    trade_date_to: date | None = None
    transaction_filters: ReconTransactionFilters | None = None


class ReconRunOut(BaseModel):
    id: uuid.UUID
    trade_date: date
    trade_date_from: date
    trade_date_to: date
    status: str
    params_snapshot: dict[str, Any]
    stats: dict[str, Any] | None
    error: str | None
    started_at: datetime
    completed_at: datetime | None


class ReconTxnBrief(BaseModel):
    id: uuid.UUID
    ext_txn_id: str | None
    broker_code: str | None
    client_name: str | None
    client_account: str | None
    stock_code: str | None
    stock_name: str | None
    side: str
    quantity: float | None
    price: float | None
    ordered_at: datetime | None
    executed_at: datetime | None
    channel: str | None


class ReconRecordingBrief(BaseModel):
    id: uuid.UUID
    original_filename: str
    broker_ext: str | None
    broker_name: str | None = None
    call_started_at: datetime | None


class ReconItemOut(BaseModel):
    id: uuid.UUID
    item_type: str
    severity: str
    match_status: str
    score: float | None
    score_breakdown: dict[str, Any]
    review_note: str | None
    reviewed_at: datetime | None
    transaction: ReconTxnBrief | None
    recording: ReconRecordingBrief | None
    instruction: TradeOut | None


class ReconItemListOut(BaseModel):
    items: list[ReconItemOut]
    total: int
    page: int
    page_size: int


class ReviewNoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ManualLinkIn(BaseModel):
    transaction_id: uuid.UUID | None = None
    recording_id: uuid.UUID
    trade_instruction_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


# --- Phase 4: SSO + admin ----------------------------------------------------

_ROLE_PATTERN = "^(admin|compliance_manager|reviewer|broker|auditor)$"


class GroupRoleMapping(BaseModel):
    group_id: str = Field(min_length=1, max_length=200)
    role: str = Field(pattern=_ROLE_PATTERN)


class SsoConfigOut(BaseModel):
    enabled: bool
    tenant_id: str | None
    client_id: str | None
    has_secret: bool
    allowed_email_domains: list[str]
    group_role_mappings: list[GroupRoleMapping]
    auto_provision: bool
    default_role: str
    updated_at: datetime | None


class SsoConfigIn(BaseModel):
    enabled: bool = False
    tenant_id: str | None = Field(default=None, max_length=200)
    client_id: str | None = Field(default=None, max_length=200)
    # Write-only; blank/None keeps the stored secret.
    client_secret: str | None = Field(default=None, max_length=1000)
    allowed_email_domains: list[str] = Field(default_factory=list)
    group_role_mappings: list[GroupRoleMapping] = Field(default_factory=list)
    auto_provision: bool = False
    default_role: str = Field(default="reviewer", pattern=_ROLE_PATTERN)


class SsoTestOut(BaseModel):
    ok: bool
    detail: str
    issuer: str | None = None


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None
    role: str
    is_active: bool
    has_password: bool
    locked: bool
    broker_codes: list[str]
    created_at: datetime


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)
    role: str = Field(pattern=_ROLE_PATTERN)
    # Absent => SSO-only account (no local password).
    password: str | None = Field(default=None, min_length=10, max_length=1024)
    is_active: bool = True
    broker_codes: list[str] = Field(default_factory=list)


class AdminUserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, pattern=_ROLE_PATTERN)
    is_active: bool | None = None
    broker_codes: list[str] | None = None


class AuditEntryOut(BaseModel):
    id: int
    occurred_at: datetime
    actor_email: str | None
    action: str
    object_type: str | None
    object_id: str | None
    details: Any | None
    ip: str | None
    user_agent: str | None


class AuditListOut(BaseModel):
    items: list[AuditEntryOut]
    total: int
    page: int
    page_size: int


class UsageDay(BaseModel):
    day: date
    callsite: str | None = None
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    audio_seconds: int | None = None
    requests: int


class UsageOut(BaseModel):
    llm: list[UsageDay]
    stt: list[UsageDay]
    llm_today_tokens: int
    stt_today_seconds: int
    llm_daily_budget: int
    stt_daily_budget: int


# --- Projects ---------------------------------------------------------------


class ProjectIn(BaseModel):
    slug: str = Field(pattern="^[a-z0-9-]{1,40}$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    modules: dict[str, bool] = Field(default_factory=dict)
    eval_prompt_context: str | None = Field(default=None, max_length=8000)
    branding: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    modules: dict[str, bool] | None = None
    eval_prompt_context: str | None = Field(default=None, max_length=8000)
    branding: dict[str, Any] | None = None
    active: bool | None = None
    is_default: bool | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    modules: dict[str, Any]
    eval_prompt_context: str | None
    branding: dict[str, Any]
    is_default: bool
    active: bool
    recording_count: int | None = None
    created_at: datetime
    updated_at: datetime


# --- Evaluator (LLM-assisted criteria authoring) ----------------------------


class EvaluatorGenerateIn(BaseModel):
    description: str = Field(min_length=10, max_length=4000)


class GeneratedCriterion(BaseModel):
    key: str
    name: str
    description: str
    category: str
    score_type: str
    severity: str
    weight: float


class GeneratedField(BaseModel):
    key: str
    label: str
    description: str | None = None
    field_type: str
    enum_options: list[str] | None = None


class EvaluatorDraft(BaseModel):
    criteria: list[GeneratedCriterion]
    extraction_fields: list[GeneratedField]
