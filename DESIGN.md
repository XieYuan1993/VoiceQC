# VoiceQA — Design Document

Voice call quality & compliance platform for **Quam Securities**. Brokers receive customer calls to place share trades; this system batch-processes the day's call recordings — transcribes them, evaluates each call against configurable criteria, extracts trade details, and reconciles recordings against the day's transactions from Quam's back-office system.

Standalone application (not part of Voicebot-Platform), living in this repo. The stack and several foundation modules are ported from Voicebot-Platform (see Appendix A).

---

## 1. Requirements review

| # | Requirement | Design answer | Open items |
|---|---|---|---|
| 1 | Email/password + configurable Azure AD SSO, RBAC, enterprise-ready | Auth.js v5: Credentials provider (argon2id, lockout, reset flow) + Microsoft Entra ID provider configured **from the database at runtime** (lazy init) so admins enable/configure SSO in the UI without redeploy. 5 roles × permission matrix; append-only audit log. | Need an Entra test tenant from Quam IT for Phase 4 verification |
| 2 | Batch upload of audio files | Multi-file + zip upload → GCS → per-recording Celery pipeline with isolated failure handling and batch progress rollup | Confirm recorder file format, channel layout, filename convention |
| 3 | Google ASR first | Pluggable `BatchASRAdapter`; first impl: Google Speech-to-Text **v2 BatchRecognize, model `chirp_2`, region `asia-southeast1`** | ⚠ No HK STT region exists — processing happens in Singapore (audio at rest stays in HK). Quam must accept this in writing |
| 4 | Gemini first | Pluggable `LLMAdapter`; first impl: Gemini via Vertex AI (`google-genai`, `vertexai=True`), structured output via `response_schema` constrained decoding | Vertex location `asia-southeast1` (not `global`) for residency consistency |
| 5 | Configurable evaluation criteria + extraction fields + per-call summary | `eval_criteria` and `extraction_fields` tables drive the prompt AND the response schema dynamically; every evaluation stores a config snapshot so past results stay auditable after edits; summary always produced | Agree the initial criteria set with Quam compliance (5 seeded defaults provided) |
| 6 | Configurable industry terms | `industry_terms` (canonical + aliases + stock codes) consumed in three places: STT speech-adaptation phrases, LLM prompt glossary, recon alias resolver | — |
| 7 | Transaction reconciliation, 3 scenarios | Dual connectors (CSV/Excel import + REST API pull) behind a `TransactionSource` interface; two-stage matching (metadata shortlists, LLM-extracted content confirms); 3 buckets with severity, manual review, decision carry-forward | Need Quam's txn export schema; need a `channel` field (phone vs online) to make scenario (b) a true breach signal |

**Key risks surfaced during design (raise with Quam early):**

1. **Data residency**: audio at rest can live in `asia-east2` (Hong Kong) GCS, but Google STT has no HK region — transcription runs in `asia-southeast1` (Singapore). If strict HK-only *processing* is mandated, Google ASR is off the table entirely.
2. **Scenario (b) "transaction without recording" is only meaningful for phone-channel trades.** If Quam's export can't tag order channel, every online order becomes a false breach. The recon engine has a `phone_only` filter — it needs that field.
3. **Cantonese/English/Mandarin code-switching**: `chirp_2` handles it via language-agnostic auto-detection, but the v2 "multiple languages" explicit-list feature does NOT support chirp models. Language mode defaults to `auto` with per-batch override; a Phase 1 spike on real Quam recordings settles the default before schema freeze.
4. **Speaker separation**: chirp_2 has no diarization. Primary mechanism is **stereo channel split** (telephony recorders typically write broker/customer to separate channels) — deterministic and more reliable than diarization anyway. Mono files degrade gracefully to a `mixed` channel with role attribution left to the LLM.

---

## 2. Architecture

Same proven shape as Voicebot-Platform — uv + pnpm monorepo, three deployable units:

```
Call QA/
├── Makefile                      # dev targets; ports shifted vs Voicebot-Platform
├── pyproject.toml                # uv workspace: shared, apps/api, apps/worker
├── pnpm-workspace.yaml           # apps/web, packages/shared-types
├── scripts/{bootstrap.sh, codegen.sh, spike_stt.py}
├── infra/
│   ├── docker-compose.yml        # postgres:16, redis:7, mailhog  (NO MinIO — see §3)
│   ├── migrations/               # Alembic, hand-written
│   └── seed/seed.py              # admin user, default settings, sample criteria/terms
├── shared/voiceqa_shared/        # settings, db_models, llm_usage, gcs, crypto
├── apps/api/app/                 # FastAPI :7870 — auth (JWE bridge), deps (RBAC), routers/
├── apps/worker/worker/           # Celery — tasks/, asr/, llm/, txn_sources/
├── apps/web/                     # Next.js 15 :3020 — Auth.js v5 (lazy config)
└── packages/shared-types/        # openapi-typescript output (generated)
```

**Dev ports** (shifted to coexist with Voicebot-Platform): web 3020, api 7870, postgres 55433, redis 56380, mailhog 8026/1026.

| Concern | Choice | Why |
|---|---|---|
| API | FastAPI, async SQLAlchemy 2, Alembic, Postgres 16 | Mirrors platform; no pgvector needed here |
| Jobs | Celery + Redis; queues `default`/`audio`/`stt`/`llm` | `acks_late`, idempotent tasks, per-recording chains |
| Frontend | Next.js 15 App Router, Tailwind + shadcn-style components | Mirrors platform |
| Auth bridge | Auth.js v5 JWE cookie decrypted in Python | Port of `apps/api/app/auth.py` — verified working pattern |
| Types | OpenAPI → openapi-typescript codegen | Port of codegen flow |
| Audio storage | **GCS, bucket in `asia-east2` (HK)** | STT v2 batch *requires* GCS URIs; Google creds already mandatory; lifecycle rules give retention for free. MinIO dropped — it would mean dual storage + copy step for zero benefit |
| Tenancy | **Single-tenant** | Bespoke deployment for one client. No `org_id` tax on every table/query. If it ever becomes a product: one mechanical add-tenant-id migration |

**GCS layout**: `raw/{batch_id}/{recording_id}/{original_name}` · `normalized/{recording_id}/{broker,customer,mono}.flac` · `txn-imports/{import_id}/{filename}`. Only audio (and raw txn files) live in the bucket — STT results return inline and all transcripts/evaluations are stored in Postgres.

---

## 3. Processing pipeline

Recording status machine: `uploaded → converting → transcribing → evaluating → completed | failed(stage)` with `failed_stage ∈ {convert, stt, eval, budget}`.

```
upload (multi-file/zip, streamed to GCS)
  └─ voiceqa.ingest.expand_batch        unzip, sha256 dedupe, filename-regex metadata,
                                        one Celery chain per recording
       chain per recording:
       ├─ voiceqa.pipeline.normalize_audio   [audio]  ffprobe → ffmpeg: stereo? split L/R
       │                                              → mono FLACs (native sample rate)
       ├─ voiceqa.pipeline.transcribe        [stt]    STT v2 BatchRecognize (chirp_2,
       │                                              asia-southeast1, adaptation phrases
       │                                              from industry_terms, GCS output);
       │                                              start LRO → poll via task retry
       └─ voiceqa.pipeline.evaluate          [llm]    budget guard → Gemini structured call
                                                      → evaluation + results + trade_instructions
       .on_error(voiceqa.pipeline.mark_failed)
  └─ voiceqa.batch.update_progress      aggregate-query rollup → batch completed /
                                        completed_with_errors (no chord — fragile at 100s of files)
  └─ voiceqa.batch.sweep_stuck          beat 5m: zombie recovery for stale non-terminal rows
```

Key decisions:

- **ffmpeg channel split** instead of diarization (§1 risk 4). Which channel is the broker is recorder-dependent → setting `audio.broker_channel`. Both channel FLACs go in **one** BatchRecognize request (2 ≤ 15-file limit) → one LRO per recording.
- **STT LRO resume**: `transcribe` stores `stt_operation_name` on start, then polls by raising `self.retry(countdown=20, max_retries=90)`. Worker dies mid-poll → redelivered task re-attaches to the same operation and retrieves the inline results from it — restart-safe without writing result files to the bucket.
- **Idempotency everywhere**: each task re-reads DB state and no-ops if its output already exists (normalized objects present / operation already started / evaluation already completed). Safe under `acks_late` redelivery.
- **Failure isolation**: one corrupt file fails its own chain only; batch ends `completed_with_errors` with per-file retry (`POST /api/batches/{id}/retry-failed`, `POST /api/recordings/{id}/reprocess?from_stage=…`).
- **Verified STT v2 limits**: max 15 files/request, 150 batch requests/min/region, 8h/file. Hundreds of recordings/day ≈ nowhere near quota. ~300 × 5-min calls ≈ US$18–24/day STT + cents of Gemini Flash.
- **Cost guards**: `stt_usage` (audio-seconds/day) and `llm_usage` (tokens/day, ported from platform's `gemini_usage` minus org) with daily budgets in settings; `evaluate` fails soft with `failed_stage=budget` when exceeded (retryable next day).

---

## 4. ASR design (Google first, pluggable)

`apps/worker/worker/asr/base.py` — `BatchASRAdapter` protocol with a start/poll split so Celery can resume:

```python
start_batch(files, *, language_mode, adaptation_phrases, model) -> operation_ref
fetch_result(operation_ref) -> list[TranscriptResult] | None   # None = still running
```

First implementation `google_batch.py` (speech_v2):

- **Model/region**: `chirp_2` @ `asia-southeast1` (GA, supports yue-Hant-HK / cmn-Hans-CN / en-US). `chirp_3` exists only in `us`/`eu` multi-regions — kept in the catalog as an explicitly-labeled "processes audio outside Asia" option, never default.
- **Language**: `auto` (chirp language-agnostic mode) by default; explicit `yue-Hant-HK` as per-batch override. The v2 explicit multi-language list is unsupported on chirp — do not use.
- **Adaptation**: inline `AdaptationPhraseSet` built per request from active `industry_terms` (canonical + aliases + code variants), stock names first, capped ~300 phrases. Same pattern as platform's `google_stt_with_adaptation.py`, applied to batch config. Managed PhraseSet resources only if request size ever becomes a problem.
- **Output**: **inline** (`InlineOutputConfig`) — call transcripts are KBs, far under inline limits, and this keeps results out of the bucket entirely (also avoids granting the Speech service agent write access to it). Parsed into `transcripts` + `transcript_segments` (channel-tagged, time-interleaved `full_text`), stored in Postgres. `GcsOutputConfig` remains available behind a flag for multi-hour files.
- **Phase 1 spike before schema freeze** (`scripts/spike_stt.py` on 3 real Quam recordings): auto vs explicit language quality; whether adaptation composes with auto mode in batch (only fact not verifiable from docs — fallback: explicit `yue-Hant-HK` + adaptation); actual channel layout; filename convention.

---

## 5. Evaluation design (Gemini first, pluggable)

`apps/worker/worker/llm/base.py` — `generate_structured(prompt, response_schema, *, model) -> (parsed, in_tokens, out_tokens)`. First impl `gemini.py`: `google-genai` SDK, `vertexai=True`, location `asia-southeast1`, `response_mime_type="application/json"` + **`response_schema` constrained decoding** (upgrade over the platform's prompt-enforced JSON; fence-stripping kept as defensive fallback). Default model `gemini-3.1-flash` (flash-lite is too weak for multi-criterion rubric scoring; remains a cost option).

One Gemini call per recording. The prompt assembles:

1. Channel-labeled transcript (broker/customer, timestamps)
2. **Active evaluation criteria** — name, description (rubric text fed verbatim), score type (`pass_fail` | `scale_1_5`), severity
3. **Active extraction fields** — call-scope (custom) + trade-scope (system-seeded, locked: `stock_code, stock_name, side, quantity, price, price_type, client_name, client_account`)
4. **Industry-terms glossary** (canonical names, aliases, codes) — so 騰訊/Tencent/700 resolve consistently
5. Call metadata (time, broker ext, direction)

The `response_schema` is **built dynamically** from criteria + fields, so admin config changes the contract, not just the prose. Response per call:

- Per-criterion: score / pass, rationale, **evidence quotes** (`{quote, channel, approx_ms}`) that the UI highlights in the transcript
- `trade_instructions[]` — a call may contain **multiple** orders: stock (raw + normalized code), side (`buy|sell|amend|cancel`), quantity, price, price type, client identity, position in call, confidence
- `extracted_call_fields` (custom fields), `summary`, `risk_flags[]`

**Config versioning — snapshots, not version tables**: every evaluation stores `criteria_snapshot` + `fields_snapshot` JSONB; result rows copy `criterion_key + name`. Edits affect only future runs; history stays self-describing; "Re-evaluate" reruns under current config as a new `run_seq`. Reviewers can approve/override per criterion or whole evaluation, with notes — all audited.

---

## 6. Transactions & reconciliation

### Sources (pluggable `TransactionSource`)

- `csv_file.py` — CSV/XLSX with saved column-mapping templates (`ext_txn_id, executed_at, broker_code, client_account, client_name, stock_code, side, quantity, price, channel`; date format, timezone, **encoding** incl. Big5-HKSCS, side-value synonyms incl. 買入/賣出, **status filter** so cancelled orders don't become false breaches). Import wizard: upload → parsed preview → mapping → dry-run validation → import. Raw file retained in GCS as evidence.
- `rest_api.py` — configurable base URL, auth (none/basic/bearer/api-key-header, creds encrypted at rest), path template (`/trades?date={date}`), pagination, field mapping, `test` endpoint, optional cron-scheduled daily pull.
- **Re-import policy**: a new completed import for the same (source, trade_date) supersedes — delete + insert in one transaction.

### Matching engine (`voiceqa.recon.run`)

Inputs: the date's `transactions` (filtered to `channel='phone'` when available — `recon.phone_only` setting) × latest `trade_instructions` from completed recordings.

1. **Normalize** — stock codes strip leading zeros (`0700`→`700`); names/aliases resolve via `industry_terms`; client names NFKC-folded (CJK + Latin); accounts stripped of punctuation.
2. **Shortlist (metadata narrows)** — candidate pairs where the recording's `broker_ext` maps to the txn's `broker_code` (via `brokers.phone_extensions`; missing ext ⇒ all candidates with penalty) AND `call_started_at ∈ [executed_at − 6h, executed_at + 15m]` (configurable — limit orders are instructed well before execution).
3. **Score (content confirms)** — `score = Σ wₖ·sₖ`, weights/tolerances in `app_settings.recon.*`:

   | Component | Weight | Scoring |
   |---|---|---|
   | stock | 0.35 | code exact/alias-resolved 1.0; name trigram ≥0.6 → 0.6; **both codes known & different → hard disqualify** |
   | side | 0.15 | equal 1.0; mismatch → hard disqualify (configurable) |
   | quantity | 0.20 | `1 − clamp(|Δq| / (q·10%), 0, 1)`; missing → 0.3 neutral |
   | price | 0.10 | within 2% → 1.0, decaying to 0 at 4%; market order/missing → 0.5 neutral |
   | client | 0.15 | account exact 1.0; last-4 match 0.8; folded-name fuzzy ≥0.75 → 0.7; missing → 0.3 |
   | time | 0.05 | linear decay 1.0 → 0.2 across the window |

4. **Assign** — greedy by score desc; each **transaction** consumes ≤1 instruction; an **instruction** may serve multiple transactions (split fills); a **recording** may serve many transactions (multi-trade calls). Thresholds: `≥0.75` auto-match, `0.45–0.75` needs-review, below → unlinked.
5. **Bucketize** — the three required scenarios, plus severity that makes scenario (c) actionable:
   - `matched` (auto / needs-review)
   - `txn_no_recording` → severity **breach** (phone-channel order with no recorded call)
   - `recording_no_txn` → **suspicious** if the call contains ≥1 unmatched trade instruction (trade discussed but never booked — or booked off-channel); **info** if zero trade instructions (service/inquiry call — benign)

Each item stores `score_breakdown` JSONB for the review drawer (side-by-side txn vs extracted instruction, evidence quote, per-component bars). Reviewers confirm / reject / manual-link with notes; **decisions carry forward** to re-runs by `(transaction_id, recording_id)` identity so work is never redone. Export per run as CSV.

Golden-fixture pytest in Phase 3: synthetic day (12 txns, 8 recordings; known truth incl. one multi-trade call, one split fill, one breach, one suspicious, one benign) asserted exactly.

### Mock-first integration (`mocks/`)

Quam has not shared integration details yet, so both external surfaces are mocked with explicit assumed contracts — see [mocks/README.md](mocks/README.md). One fixture (`mocks/data/golden_day.json`) drives everything: an EOD CSV/XLSX generator, a mock back-office REST API (`:7880`, X-API-Key auth, pagination, serves any date), and a synthetic-recording generator (macOS `say`, Cantonese/Mandarin, stereo L=broker/R=customer, recorder filename convention, ground-truth `manifest.json`). The golden day embeds the exact expected recon outcome per item, so it doubles as the Phase 3 golden-fixture test data; scripted criteria failures (R2 no read-back, R8 no identity check) double as Phase 2 demo data. Synthetic audio proves pipeline mechanics only — the Phase 1 ASR-accuracy spike still requires real recordings. When Quam's real details arrive, only config changes (mapping template, connector config, filename regex); the swap-in checklist is in the README.

---

## 7. Auth, RBAC, SSO

### Roles & permissions

Permission matrix (`apps/api/app/permissions.py`), enforced by a `require(perm)` FastAPI dependency; verbs: `recordings:read_all|read_own, transcripts:read, evals:review, config:read|write, terms:write, txns:read|import, recon:run|review, users:manage, sso:manage, audit:read, usage:read`.

| Role | Scope |
|---|---|
| `admin` | everything incl. users, SSO, settings |
| `compliance_manager` | all data + config (criteria/fields/terms/recon), run recon, review |
| `reviewer` | read recordings/transcripts/evals, review & override; no config |
| `broker` | **own calls only** — `user_broker_codes → brokers.phone_extensions → recordings.broker_ext` filter at query layer; reduced "My calls" UI |
| `auditor` | read-everything incl. audit log; zero writes |

### Email/password (Credentials provider)

`authorize()` calls FastAPI `POST /api/auth/verify-credentials` (internal, shared-secret header) so argon2id verification, lockout (5 fails → 15 min), and audit events live in Python. Password reset via emailed token (MailHog in dev). JWT claims carry `role` + `session_version`; FastAPI re-validates per request via the ported JWE bridge — bumping `session_version` on deactivate/role-change gives **instant revocation** (pattern already proven in `deps.py`).

### Azure AD / Microsoft Entra ID — admin-configurable, no redeploy

Verified feasible: Auth.js v5 **lazy initialization** — `NextAuth(async () => config)` — builds the provider list per request:

- `sso_config` singleton row: enabled, tenant_id, client_id, **client_secret encrypted (AES-256-GCM under `APP_ENCRYPTION_KEY`)**, allowed email domains, `group_role_mappings` (Entra group ID → role, first match wins), auto-provision + default role. 60s in-process cache.
- Provider: `MicrosoftEntraID` with `issuer = https://login.microsoftonline.com/{tenant_id}/v2.0` (exact match — known Auth.js gotcha). Stable provider id so `accounts` rows survive secret rotation.
- **Middleware stays on the static edge-safe `auth.config.ts`** (`providers: []`) — same split the platform already uses; session JWE uses static `AUTH_SECRET`, so the FastAPI bridge is unaffected by dynamic providers.
- Login page renders "Sign in with Microsoft" from public `GET /api/auth/sso-status`.
- `signIn` callback: domain allowlist → link-or-provision → map `groups` claim to role (note Entra's 200-group overage limit; fallback = locally managed roles).
- **Fallback if a Next.js upgrade ever breaks lazy init**: same schema/UI, read config at boot + "restart to apply" banner. Zero schema change.
- Admin UI: SSO form + "Test connection" (OIDC discovery fetch on the issuer).

The same AES-256-GCM cipher is implemented in `voiceqa_shared/crypto.py` (Python — txn API creds) and `apps/web/src/lib/crypto.ts` (Node — SSO secret) with one shared cross-language test vector.

---

## 8. Data model (Postgres 16)

UUID PKs (`gen_random_uuid()`), `created_at/updated_at timestamptz`; Auth.js adapter tables keep camelCase columns (platform migration `0001` ported verbatim).

**Auth/admin** — `users` (+ `password_hash`, `role`, `is_active`, `failed_login_attempts`, `locked_until`, `session_version`), `accounts`, `sessions`, `verification_token`, `password_reset_tokens`, `user_broker_codes (user_id, broker_code)`, `brokers (code PK, name, phone_extensions[], active)`, `sso_config` (singleton), `app_settings (key PK, value jsonb)` — holds `recon.weights/thresholds/time_window`, `audio.broker_channel`, `asr.language_mode/model`, `llm.model`, `filename.parse_regex` (named groups `broker_ext|ts|caller|direction`), `retention.days`, `budget.*` — and `audit_log` (bigserial, append-only: action, object, details jsonb, ip, UA; covers mutations AND sensitive reads).

**Pipeline** — `upload_batches (trade_date, status, total_files, finalized_at)`; `recordings` (batch FK, original_filename, sha256 — `UNIQUE(batch_id, sha256)`, gcs_uris raw/broker/customer/mono, duration/sample_rate/channels/format, `call_started_at`, `broker_ext`, `caller_number`, `direction`, `language_mode`, `status`, `failed_stage`, `error`, `attempts`, `stt_operation_name`); `transcripts` (recording UNIQUE FK, stt_model, language_detected, full_text — `pg_trgm` GIN index since Postgres FTS tokenizes Chinese poorly, billed_seconds); `transcript_segments` (channel_role broker|customer|mixed, start/end_ms, text, language, confidence).

**Evaluation** — `eval_criteria (key UNIQUE, name, description→prompt, category, score_type, severity, weight, active, sort_order)`; `extraction_fields (key, label, description, field_type, enum_options, scope call|trade, is_system, active)`; `evaluations (recording FK, run_seq — UNIQUE(recording_id, run_seq), status, llm_model, criteria_snapshot, fields_snapshot, summary, overall_score, risk_flags, extracted_call_fields, review_status, reviewed_by/at/note, tokens)`; `evaluation_results (criterion_key/name copies, score, passed, rationale, evidence jsonb, override_* fields)`; `trade_instructions (evaluation FK, recording FK denorm, seq, stock_code normalized, stock_name_raw, side, quantity, price, price_type, client_name_raw, client_account_raw, time_in_call_ms, confidence, evidence_quote)` — first-class table because recon joins on it.

**Transactions/recon** — `txn_source_configs (kind csv|api, config jsonb, credentials_enc, schedule_cron)`; `txn_imports (source FK, kind, trade_date, gcs_uri, status, counts, errors)`; `transactions (import FK, ext_txn_id, trade_date, executed_at, broker_code, client_account/name, stock_code normalized, side, quantity, price, channel, raw jsonb)` — partial unique `(ext_txn_id, trade_date)`; `recon_runs (trade_date, status, params_snapshot, stats)`; `recon_items (run FK, item_type matched|txn_no_recording|recording_no_txn, severity info|suspicious|breach, txn/recording/instruction FKs, score, score_breakdown, match_status auto_matched|needs_review|unmatched|confirmed|rejected|manual_linked, review_note, reviewed_by/at)`.

**Usage** — `llm_usage (day, callsite, model, tokens, requests — UNIQUE(day, callsite, model))`, `stt_usage (day, provider, model, audio_seconds, requests)`.

---

## 9. API surface (FastAPI `/api`, cookie session via JWE bridge)

- **auth**: `POST /auth/verify-credentials` (internal) · `POST /auth/password-reset/{request,confirm}` · `GET /auth/sso-status` (public) — Next.js owns `/api/auth/[...nextauth]`
- **batches**: `POST /batches` · `GET /batches[/{id}]` · `POST /batches/{id}/files` (multipart, audio or zip, streamed to GCS) · `POST /batches/{id}/finalize` · `POST /batches/{id}/retry-failed`
- **recordings**: `GET /recordings` (filters: batch, date, status, broker, q) · `GET /recordings/{id}` · `GET /recordings/{id}/audio` (302 → ≤10-min signed URL, audited) · `GET /recordings/{id}/transcript` · `POST /recordings/{id}/reprocess?from_stage=`
- **evaluations**: `GET|POST /recordings/{id}/evaluations` · `POST /evaluations/{id}/review` · `POST /evaluations/{id}/results/{criterion_key}/override`
- **config**: CRUD `/criteria`, `/extraction-fields`, `/terms` (+ `/terms/import-csv`) · `GET|PUT /settings/{key}` (pydantic-validated per key)
- **transactions**: `GET /transactions` · `POST /txn-imports/csv` (`?dry_run=1` preview) · `GET /txn-imports` · `/txn-sources` CRUD + `/{id}/test` + `/{id}/pull`
- **recon**: `POST|GET /recon/runs[/{id}]` · `GET /recon/runs/{id}/items?bucket=&status=` · `POST /recon/items/{id}/{confirm,reject,manual-link}` · `GET /recon/runs/{id}/export.csv`
- **admin**: `/admin/users` CRUD (role, broker codes, activate, force-reset) · `GET|PUT /admin/sso` + `POST /admin/sso/test` · `GET /admin/audit` · `GET /admin/usage`
- `GET /healthz`, `GET /me`

## 10. Frontend pages

- `(auth)`: login (password + conditional Microsoft button), forgot/reset password
- Dashboard: today's batch progress, risk-flag feed, per-date recon status, breach counter
- Batches: upload dropzone (multi-file/zip, concurrency 4, per-file progress, resume failed — evolved from platform's `kb/upload-panel.tsx`), status grid with per-stage chips + retry
- Recording detail: audio player ↔ click-to-seek transcript (channel-colored, language badges) ↔ evaluation scorecard (criterion scores, rationale, evidence quotes highlighting transcript) ↔ extracted trades ↔ recon links
- Recon run: three bucket tabs with severity badges; review drawer (txn vs instruction side-by-side, score-breakdown bars, confirm/reject/manual-link); export
- Transactions: table, import wizard, sources management
- Settings: criteria / fields / terms (CSV import) / recon weights (+ "test against date" dry-run)
- Admin: users, SSO (form + test + enable toggle), audit explorer, usage charts
- Nav is permission-aware; `broker` role lands on a reduced "My calls" view

---

## 11. Enterprise readiness

- **Secrets**: SSO client secret + txn API creds AES-256-GCM in DB; `APP_ENCRYPTION_KEY` / `AUTH_SECRET` / `INTERNAL_API_SECRET` via env or secret manager; ported placeholder-secret guard refuses production boot with default values
- **PII**: client names/accounts appear in transcripts → RBAC scoping, audited reads (transcript view, audio playback, txn list), signed URLs ≤10 min, uniform bucket-level access, optional account-masking flag for broker role
- **Residency**: bucket `asia-east2` (HK); STT `asia-southeast1`; Vertex `asia-southeast1`; the Singapore-processing caveat documented for client sign-off
- **Retention**: `retention.days` → daily task deletes aged GCS audio + transcript text (configurable depth), keeps evaluations/recon/audit; GCS lifecycle rules as backstop
- **Audit**: append-only, indexed, exportable; no delete endpoint even for admins
- **Abuse/limits**: slowapi (5/min auth, 60/min default), upload size caps, zip-bomb guard (entry count + decompressed-size ceiling)
- **Ops**: healthchecks, structured logs with request IDs, daily LLM/STT usage dashboards + budget guards, `sweep_stuck` zombie recovery, nightly `pg_dump` → GCS + object versioning
- **Deploy path**: docker-compose on a VM (Caddy/nginx TLS, real SMTP, optionally Cloud SQL) first; same images move to Cloud Run/GKE with env changes only

---

## 12. Phased implementation

**Phase 0 — Scaffold.** Monorepo skeleton ported from Voicebot-Platform (Appendix A): compose (pg/redis/mailhog), settings, Alembic `0001` auth tables + role/password columns, `0002` audit/app_settings/brokers/reset-tokens, JWE bridge + deps + `require(perm)`, Credentials login, seed (admin + defaults), codegen, Celery ping.
*Verify*: `make up && make migrate && make seed` → login as seeded admin → `GET /api/me` 200 → `celery call voiceqa.ping` → codegen produces types → placeholder guard blocks prod boot.

**Phase 1 — Upload + ASR pipeline.** **First: `scripts/spike_stt.py` on 3 real Quam recordings** (settles language mode, adaptation×auto, channel layout, filename regex — before schema freeze). Then: ingest/normalize/transcribe tasks, batches/recordings routers + UI, transcript viewer, industry_terms (needed for adaptation already), rollup + sweep.
*Verify*: 20-file day incl. one zip → all `completed` or isolated `failed`; bilingual channel-tagged transcript renders; add a stock term → reprocess → term transcribed; kill worker mid-batch → restart → batch finishes.

**Phase 2 — Configurable evaluation.** Criteria/fields CRUD + UI, LLM adapter with dynamic `response_schema`, evaluate task, scorecard + trades UI, review/override, usage + budget guard, re-run.
*Verify*: 5 seeded HK-brokerage criteria (identity verification, order read-back, no unauthorized advice, risk disclosure, professional conduct); real call → scores with evidence quotes that exist in the transcript; multi-trade call → N `trade_instructions`; edit criterion → old eval unchanged, re-run uses new rubric; tiny budget → `failed_stage=budget`, retryable.

**Phase 3 — Transactions + reconciliation.** Import wizard + REST connector + scheduled pulls, brokers admin, recon engine, three-bucket UI + review drawer + manual-link + export, carry-forward, golden-fixture pytest.
*Verify*: synthetic golden day reconciles to known truth exactly; confirm/override → audit rows; re-run carries decisions forward; connector `test` against a mock server.

**Phase 4 — SSO + hardening.** sso_config + admin UI + lazy NextAuth + Entra provider + group→role mapping + cross-language crypto; audit sweep; rate limiting; retention task; deployment docs; 300-file load test.
*Verify*: configure a real Entra test tenant **entirely through the UI** (no env change, no redeploy) → SSO login → group maps to role; disable SSO → button disappears; auditor reads audit but cannot mutate; broker sees only own-extension recordings; lockout after 5 bad passwords; prod boot refuses placeholder secrets.

---

## 13. To confirm with Quam

*(Items 1 and 3 are mocked in `mocks/` with explicit assumed contracts — development is unblocked; these now mean "confirm or correct the assumptions". See [mocks/README.md](mocks/README.md).)*

1. Transaction export schema — and whether a **channel** field (phone/online) exists (drives breach detection)
2. Acceptance of Singapore STT/LLM **processing** (HK-only at rest is guaranteed; HK-only processing is impossible with Google ASR)
3. Recorder details: file format, stereo channel layout, filename convention, typical daily volume
4. Initial evaluation criteria set + retention period (regulatory minimum for call records)
5. Entra test tenant + app registration for Phase 4
6. Sample recordings (3–5) for the Phase 1 STT spike

---

## Appendix A — Assets ported from Voicebot-Platform

| Source (worktree `…/Voicebot-Platform/.claude/worktrees/eager-poincare-41d873`) | Becomes | Notes |
|---|---|---|
| `apps/api/app/auth.py` | same | Auth.js v5 JWE decryption — verbatim (verified) |
| `apps/api/app/deps.py` | `deps.py` | strip org, keep `session_version` revocation, add `require(perm)` (verified) |
| `shared/voicebot_shared/settings.py` | `voiceqa_shared/settings.py` | + GCS/encryption/internal-secret fields, keep placeholder guard |
| `shared/voicebot_shared/gemini_usage.py` | `llm_usage.py` | drop `org_id`; add `stt_usage` sibling |
| `apps/worker/worker/tasks/analysis.py` | `llm/gemini.py` | upgrade prompt-JSON → `response_schema` constrained decoding |
| `apps/api/app/voice/google_stt_with_adaptation.py`, `asr_factory.py` | `asr/google_batch.py`, `asr/factory.py` | adaptation pattern reused; streaming → BatchRecognize |
| `apps/web/src/auth.ts`, `auth.config.ts` | same | `auth.ts` → lazy init + Credentials + conditional Entra |
| `apps/web/src/app/(dashboard)/kb/upload-panel.tsx` | `upload-dropzone.tsx` | multi-file/zip + progress + resume |
| `Makefile`, `infra/docker-compose.yml`, `scripts/codegen.sh`, migration `0001` | same | rename, shift ports, drop MinIO |

**Sources verified during design**: Google STT v2 batch-recognize docs & quotas (15 files/req, GCS-only input), Chirp 2/Chirp 3 model & region matrices, STT v2 multiple-languages restrictions, Auth.js v5 lazy initialization & Microsoft Entra ID provider docs.
