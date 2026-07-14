# Deploying VoiceQA

This is an enterprise compliance system handling client PII (call recordings,
transcripts, account numbers). Read the [Security & residency](#security--data-residency)
section before the first production deploy.

The recommended first production target is **docker-compose on a single hardened
VM** with TLS in front; the same images move to Cloud Run / GKE later with only
env changes. There is no application change between the two — the app is
twelve-factor (all config via env, no local state beyond Postgres/Redis/GCS).

---

## 1. Topology

| Component | Process | Scales | Notes |
|---|---|---|---|
| `apps/web` | Next.js (standalone) | horizontally | stateless; sessions are JWE cookies |
| `apps/api` | FastAPI (uvicorn/gunicorn) | horizontally | stateless; rate limiter + Celery use Redis |
| `apps/worker` | Celery worker(s) + 1 beat | horizontally (workers); **beat is a singleton** | run exactly one `--beat` (or a separate `celery beat`) process |
| Postgres 16 | managed (Cloud SQL) or container | — | the system of record |
| Redis 7 | managed or container | — | Celery broker/result + rate-limit store |
| GCS bucket | `asia-east2` | — | audio + raw txn files only (transcripts live in Postgres) |
| SMTP relay | external | — | password-reset emails |

TLS terminates at a reverse proxy (Caddy or nginx) in front of `web` (:3020)
and `api` (:7870). The browser talks to both origins, so CORS
(`ALLOWED_ORIGINS`) must list the public web origin and Auth.js cookies must be
`__Secure-` over HTTPS (Auth.js does this automatically when `NEXTAUTH_URL` is
`https://`).

### Reverse proxy (Caddy example)

```
qa.quam.example {                      # web
    reverse_proxy web:3020
}
api.qa.quam.example {                  # api
    reverse_proxy api:7870
}
```

Set `NEXTAUTH_URL=https://qa.quam.example`, `NEXT_PUBLIC_API_URL=https://api.qa.quam.example`,
`ALLOWED_ORIGINS=["https://qa.quam.example"]`.

---

## 2. Prerequisites

- A GCP project with **Speech-to-Text v2** and **Vertex AI** APIs enabled.
- A service account with: `roles/speech.client`, `roles/aiplatform.user`,
  `roles/storage.objectAdmin` (scoped to the audio bucket). Download a JSON key
  or use Workload Identity on GKE.
- A GCS bucket in `asia-east2` (Hong Kong) with **uniform bucket-level access**
  and no public access. See [§5](#5-gcs-lifecycle--retention).
- Managed Postgres 16 (Cloud SQL recommended) and Redis 7.
- An SMTP relay (SES, SendGrid, or the corporate relay) for reset emails.
- For SSO: an Entra ID app registration (see [§6](#6-azure-ad--entra-sso)).

---

## 3. Environment & secret checklist

Set `ENV=production`. The shared settings **placeholder-secret guard refuses to
boot** if any of `NEXTAUTH_SECRET`, `INTERNAL_API_SECRET`, or
`APP_ENCRYPTION_KEY` still hold a placeholder value — so generate real ones.

| Var | Where | Notes |
|---|---|---|
| `ENV` | api, worker | `production` |
| `DATABASE_URL` | api, worker, seed | `postgresql+asyncpg://…` (managed PG) |
| `DATABASE_URL` (sync) | web | `postgresql://…` (Auth.js adapter + SSO config read) |
| `REDIS_URL` | api, worker | broker + rate-limit store |
| `NEXTAUTH_SECRET` | api **and** web | MUST be identical — the api decrypts the web's session cookie. `openssl rand -base64 32` |
| `NEXTAUTH_URL` | api, web | public https web origin |
| `INTERNAL_API_SECRET` | api **and** web | MUST be identical — guards `verify-credentials`. `openssl rand -base64 32` |
| `APP_ENCRYPTION_KEY` | api **and** web | MUST be identical — AES-256-GCM for the SSO secret + txn API creds. `openssl rand -base64 32` |
| `NEXT_PUBLIC_API_URL` | web (build + runtime) | public https api origin |
| `ALLOWED_ORIGINS` | api | JSON list incl. the web origin |
| `GOOGLE_APPLICATION_CREDENTIALS` | api, worker | SA key path (or use Workload Identity) |
| `GOOGLE_CLOUD_PROJECT` | api, worker | |
| `GOOGLE_STT_LOCATION` | worker | `asia-southeast1` |
| `VERTEX_LLM_LOCATION` | worker | `asia-southeast1` (3.x flash may force `global` — adapter falls back with a logged warning) |
| `GCS_BUCKET_AUDIO` | api, worker | the `asia-east2` bucket |
| `GOOGLE_STT_MODEL` / `LLM_PROVIDER` / `DASHSCOPE_LLM_MODEL` | worker | `chirp_2` / `dashscope` / `qwen3.7-max` (also editable at runtime via Settings) |
| `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` | worker | required when `asr.provider=tencent`; use `asr.model=16k_zh_en` for Tencent's "普方英大模型" |
| `TENCENT_ASR_REGION` | worker | `ap-guangzhou` by default |
| `ASR_AUDIO_PROXY_BASE_URL` | worker | recommended for Tencent ASR; set to the public API base URL so Tencent downloads audio through VoiceQA instead of Google Storage directly |
| `RECORDING_CONVERT_TIMEOUT_SECONDS` / `RECORDING_STT_TIMEOUT_SECONDS` / `RECORDING_EVAL_TIMEOUT_SECONDS` | worker | optional pipeline timeout thresholds; defaults are 1800 / 1800 / 3600 seconds |
| `RECORDING_RESUME_STALE_SECONDS` / `RECORDING_RESUME_MAX_ATTEMPTS` | worker | optional stale-task recovery controls; defaults are 300 seconds and 1 re-enqueue before failing |
| `FEISHU_WEBHOOK_URL` / `FEISHU_WEBHOOK_SECRET` | singleton beat worker | optional Feishu custom-bot notifications for stuck `evaluating` recordings; set the secret only when the bot has signature verification enabled |
| `EVALUATING_MONITOR_STALE_SECONDS` / `EVALUATING_MONITOR_NOTIFY_OK` | singleton beat worker | evaluation monitor warning threshold and whether to send OK heartbeats; defaults are 1200 seconds and `false` |
| `WORKER_MAX_TASKS_PER_CHILD` / `WORKER_MAX_MEMORY_PER_CHILD` | worker | optional Celery child recycling controls; useful for STT memory pressure (`max-memory` is in KiB) |
| `SMTP_HOST/PORT/USER/PASS`, `MAIL_FROM` | api | real relay |

The three "MUST be identical across api+web" secrets are the cross-tier trust
anchors — keep them in one secret-manager entry each and inject into both tiers.

---

## 4. Database & migrations

```bash
# from the repo (or a migration job/sidecar):
make migrate           # alembic upgrade head — idempotent, safe to re-run
make seed              # first deploy only: admin user + default settings + brokers
```

Change the seeded admin password immediately (`SEED_ADMIN_PASSWORD`, or rotate
via the admin UI). On Cloud SQL, run migrations from a one-shot job or a bastion
with the Cloud SQL Auth Proxy.

---

## 5. GCS lifecycle & retention

Two layers protect retention:

1. **App retention task** (`voiceqa.maintenance.apply_retention`, daily via beat)
   purges audio objects + verbatim transcripts older than the `retention.days`
   setting, keeping the compliance record (evaluations, trade instructions,
   reconciliation, audit log). Preview/trigger from the admin Usage page.
2. **GCS lifecycle rule** as a backstop, in case the worker is down for a long
   stretch:

```json
{
  "rule": [
    { "action": {"type": "Delete"},
      "condition": {"age": 400} }
  ]
}
```

Set the lifecycle `age` somewhat ABOVE `retention.days` so the app task (which
also clears the DB references) runs first; the lifecycle rule only sweeps
stragglers. Enable **object versioning** so an accidental early delete is
recoverable within a short window.

Agree the actual retention period with Quam compliance (HK regulatory minimum
for order records is typically years — confirm before setting `retention.days`).

---

## 6. Azure AD / Entra SSO

SSO is configured **at runtime through the admin UI** (Admin → SSO), not via
env — admins can enable/rotate it without a redeploy. In Entra:

1. Register an app; add the redirect URI
   `https://qa.quam.example/api/auth/callback/microsoft-entra-id`.
2. Create a client secret.
3. (For group→role mapping) add the `groups` claim to the token configuration,
   or use group IDs in the mapping. Note Entra's 200-group token overage limit;
   for users in many groups, fall back to locally-managed roles.
4. In the VoiceQA admin UI: enter tenant id, client id, client secret, allowed
   email domains, group→role mappings, auto-provision + default role. Click
   **Test connection** (does an OIDC discovery fetch) before enabling.

The client secret is stored AES-256-GCM-encrypted (`APP_ENCRYPTION_KEY`); the
web tier decrypts it in its lazy NextAuth init. The login middleware stays on
the static edge config, so enabling SSO never disturbs the session bridge.

---

## 7. Backups

- **Postgres**: managed automated backups + PITR (Cloud SQL), OR a nightly
  `pg_dump` to a separate GCS bucket:
  ```bash
  pg_dump "$DATABASE_URL_SYNC" | gzip | gsutil cp - gs://quam-voiceqa-backups/pg/$(date +%F).sql.gz
  ```
  Keep backups in a DIFFERENT bucket/project from the audio, with its own
  lifecycle (e.g. 35 days) and restricted access.
- **GCS audio**: object versioning + the lifecycle rule above. Audio is
  regenerable only from the source recorder, so treat the bucket as primary.
- Test a restore quarterly.

---

## 8. Secret rotation runbook

| Secret | Procedure | Impact |
|---|---|---|
| `NEXTAUTH_SECRET` | rotate in api+web together, redeploy both | all sessions invalidated (everyone re-logs-in) |
| `INTERNAL_API_SECRET` | rotate in api+web together, redeploy both | brief window where in-flight logins fail; no data impact |
| `APP_ENCRYPTION_KEY` | **two-step**: decrypt-then-reencrypt existing rows under the new key BEFORE swapping. Affected rows: `sso_config.client_secret_enc`, `txn_source_configs.credentials_enc`. Write a one-off script using `voiceqa_shared.crypto` with old+new keys. | if swapped without re-encrypt, SSO + txn API pulls break until secrets are re-entered |
| Entra client secret | rotate in Entra, paste new value in Admin → SSO | none if done before the old one expires |
| txn API credential | rotate at source, update via Sources → Edit | next pull uses the new credential |
| DB password | rotate in PG + `DATABASE_URL` in api/worker/web | rolling restart |
| Seeded admin password | Admin → Users → set-password | that admin re-logs-in |

Account lockout (5 failed logins → 15 min) and the per-IP rate limit on
password-reset are always on; no config needed.

---

## 9. Scaling & ops

- **API**: run under gunicorn with several uvicorn workers behind the proxy.
  The rate limiter and Celery dispatch are Redis-backed, so limits and the queue
  hold correctly across workers.
- **Worker**: scale horizontally by queue (`-Q audio`, `-Q stt`, `-Q llm`,
  `-Q default`) to size each stage independently. Run **exactly one beat**
  process (the `--beat` flag or a dedicated `celery beat`) — duplicate beats =
  duplicate scheduled retention/pull sweeps.
- **Health**: api `GET /api/healthz` (liveness) and `/api/readyz` (DB+Redis).
  Worker liveness via `celery -A worker.celery_app inspect ping`.
- **Budgets**: `budget.llm_daily_tokens` / `budget.stt_daily_seconds` settings
  cap daily spend; the evaluate stage soft-fails (`failed_stage=budget`,
  retryable next day) when the LLM budget is hit. Watch the Usage dashboard.
- **Throughput**: ~300 5-min calls/day ≈ 25 audio-hours ≈ US$18–24/day STT +
  cents of Gemini. STT v2 batch quota (150 req/min/region) is far above this.
- **Zombie recovery**: `voiceqa.batch.sweep_stuck` re-dispatches recordings
  stuck in a non-terminal stage; no operator action needed.

---

## Security & data residency

- **At rest**: audio in `asia-east2` (Hong Kong). Transcripts/evaluations in
  Postgres — place the DB in an HK region too.
- **Processing**: Google STT has **no HK region** — transcription runs in
  `asia-southeast1` (Singapore) and Gemini in the configured Vertex location.
  **This must be accepted by Quam in writing.** If strict HK-only *processing*
  is mandated, Google ASR cannot be used and an alternative provider is needed
  (the ASR/LLM adapters are pluggable for exactly this reason).
- **PII**: client names/accounts appear in transcripts → RBAC scoping (the
  `broker` role sees only its own extensions), audited reads (transcript view,
  audio playback, txn list), signed audio URLs ≤10 min, uniform bucket-level
  access, no public ACLs.
- **Audit**: every mutation and sensitive read is in `audit_log` (append-only;
  no delete path even for admins). Export from Admin → Audit.
- **Network**: keep Postgres/Redis on a private network; expose only the proxy.
