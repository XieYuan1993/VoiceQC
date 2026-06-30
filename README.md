# VoiceQA

Call quality & compliance platform for Quam Securities: batch-upload broker call recordings → transcribe (Google STT v2, Cantonese/English/Mandarin) → evaluate against configurable criteria with Gemini → reconcile against the day's trades.

- **Design**: [DESIGN.md](DESIGN.md) — architecture, data model, matching algorithm, phased plan
- **Mock integrations**: [mocks/README.md](mocks/README.md) — fake back-office API, EOD files, synthetic recordings (Quam's real integration details pending)

## Stack

uv + pnpm monorepo. FastAPI (`apps/api`, :7870) · Celery worker (`apps/worker`) · Next.js 15 (`apps/web`, :3020) · Postgres 16 (:55433) · Redis (:56380) · MailHog (:8026). Auth.js v5 with email/password (Azure AD SSO in Phase 4); FastAPI validates the Auth.js session cookie via a ported JWE bridge.

## Quickstart

```bash
make bootstrap           # copy .env files, generate secrets
uv sync --all-packages   # python deps
pnpm install             # js deps
make up                  # postgres, redis, mailhog (docker)
make migrate             # alembic upgrade head
make seed                # admin user + default settings + brokers

# three terminals:
make api.dev             # FastAPI  http://localhost:7870  (docs at /api/docs)
make worker.dev          # Celery worker
make web.dev             # Next.js  http://localhost:3020

# sign in: admin@local.test / voiceqa-admin-1  (from .env SEED_ADMIN_*)
```

Ports are shifted so this stack coexists with Voicebot-Platform on the same machine.

## Phase status

- **Phase 0 — foundations** ✅: monorepo, compose data plane, Auth.js credentials login + JWE bridge, RBAC permission matrix, audit log, seed, codegen
- **Phase 1 — batch upload + ASR pipeline** ✅: GCS, ffmpeg channel split, Google STT v2 batch (Cantonese/Mandarin/English)
- **Phase 2 — configurable evaluation** ✅: criteria, extraction fields, industry terms, Gemini structured scoring + trade extraction
- **Phase 3 — transactions + reconciliation** ✅: CSV/Excel + REST connectors, matching engine, the three buckets
- **Phase 4 — Azure AD SSO + enterprise hardening** ✅: runtime-configurable Entra SSO, admin (users/audit/usage), rate limiting, data retention

## Deployment

See [DEPLOY.md](DEPLOY.md) — docker-compose-on-VM first (TLS, managed Postgres/Redis, GCS lifecycle, backups, secret rotation), with the same images moving to Cloud Run / GKE. Read the **Security & data residency** section before any production deploy (Google STT processes audio in Singapore — there is no Hong Kong STT region).
