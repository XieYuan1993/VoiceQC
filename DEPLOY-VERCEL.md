# Deploying VoiceQA — Vercel (web) + Render (api + worker)

VoiceQA is more than a Next.js app, so it can't all live on Vercel:

| Piece | Host |
|---|---|
| `apps/web` (Next.js) | **Vercel** |
| `apps/api` (FastAPI) + `apps/worker` (Celery + beat) | **Render** (one Docker image, two services) |
| Postgres 16, Redis | **Render** managed (Postgres + Key Value) |
| GCS bucket + Vertex/Gemini (+ optional Google STT) | **Google Cloud** |

The Celery worker runs the audio pipeline (ffmpeg → ASR → Gemini, polling for
minutes) — a persistent background process Vercel's serverless model can't run.
This guide covers the hosting; for security, retention, SSO, and backups see
[`DEPLOY.md`](DEPLOY.md) (all of it applies — only the *hosting* differs here).

The artifacts are in the repo: [`infra/docker/Dockerfile`](infra/docker/Dockerfile)
(build-verified), [`render.yaml`](render.yaml) (Render Blueprint), and a Next.js
`/api/*` proxy so the browser stays same-origin.

---

## 0. What you need first

- This repo on **GitHub** (Render + Vercel deploy from it).
- A **Render** account and a **Vercel** account.
- **Google Cloud**: a project with **Vertex AI** enabled (and **Speech-to-Text v2**
  only if you switch ASR off the default); a **service-account JSON key** with
  `roles/aiplatform.user` + `roles/storage.objectAdmin` (scoped to the bucket);
  and a **GCS bucket** (the app uses `asia-east2`).
- A **Qwen / DashScope** API key + base URL (the default ASR provider).

---

## 1. Backend on Render (Blueprint)

1. Render → **New → Blueprint** → connect the repo. It reads `render.yaml` and
   creates four resources: `voiceqa-api` (web), `voiceqa-worker` (background),
   `voiceqa-db` (Postgres 16), `voiceqa-redis` (Key Value). Click **Apply**.
2. Three secrets auto-generate in the **`voiceqa-secrets`** env group:
   `NEXTAUTH_SECRET`, `INTERNAL_API_SECRET`, `APP_ENCRYPTION_KEY`. **Copy their
   values** (you'll paste the same ones into Vercel — they must match byte-for-byte).
3. Add the GCP key as a **Secret File** on **both** `voiceqa-api` and
   `voiceqa-worker`: name it **`gcp-sa.json`** (it mounts at
   `/etc/secrets/gcp-sa.json`, which `GOOGLE_APPLICATION_CREDENTIALS` already points at).
4. Fill the `sync: false` vars on **both** services:
   `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET_AUDIO`, `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`.
   (`NEXTAUTH_URL` + `ALLOWED_ORIGINS` on the api come in step 4.)
5. Deploy. The api runs `alembic upgrade head` automatically before going live.
   Note the api URL, e.g. `https://voiceqa-api-xxxx.onrender.com`.

## 2. Seed once

On `voiceqa-api` → **Shell**:

```bash
python infra/seed/seed.py
```

Creates the admin (`admin@local.test` / `SEED_ADMIN_PASSWORD`, default
`voiceqa-admin-1`), a default project, and starter settings. Set
`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` on the api first if you want custom
ones, and change the admin password after first login.

## 3. Web on Vercel

1. Vercel → **New Project** → import the repo → **Root Directory = `apps/web`**
   (it auto-detects Next.js + the pnpm monorepo).
2. Environment variables:

   | Var | Value |
   |---|---|
   | `BACKEND_API_URL` | the Render api URL (`https://voiceqa-api-xxxx.onrender.com`) — server fetches + the `/api/*` proxy |
   | `DATABASE_URL` | the Render Postgres **External** connection string (voiceqa-db → *External Database URL*). Vercel is outside Render's network, so use the external one. |
   | `NEXTAUTH_SECRET` | paste from Render's `voiceqa-secrets` |
   | `INTERNAL_API_SECRET` | paste from Render's `voiceqa-secrets` |
   | `APP_ENCRYPTION_KEY` | paste from Render's `voiceqa-secrets` |
   | `NEXTAUTH_URL` | your Vercel URL, `https://<project>.vercel.app` (set after the first deploy reveals it, then redeploy — or use a custom domain) |

   Leave `NEXT_PUBLIC_API_URL` **unset** — the browser uses the same-origin proxy.
3. Deploy.

## 4. Wire web ↔ api

1. On Render `voiceqa-api`, set and save (it redeploys):
   - `NEXTAUTH_URL = https://<your-vercel-domain>`
   - `ALLOWED_ORIGINS = ["https://<your-vercel-domain>"]`
2. Make sure Vercel's `NEXTAUTH_URL` is that same domain; redeploy the web if changed.

## 5. Verify

- Open `https://<vercel-domain>` → sign in.
- Add criteria in the **Evaluator** (or **Generate**), create a **batch**, upload a
  short call → it should transcribe and evaluate. Watch `voiceqa-worker` logs on Render.

---

## How requests flow (why the proxy)

The browser only ever talks to your **Vercel origin**. `next.config.mjs` rewrites
`/api/*` to `BACKEND_API_URL` (the Render api), so the session cookie stays
**first-party** — no cross-site `SameSite`/CORS breakage on client-side actions
(re-evaluate, generate, save, upload). Server components call the api directly;
`/api/auth/*` stays on Vercel (NextAuth). The `DATABASE_URL` handling accepts a
plain `postgresql://` from any managed Postgres.

## Notes

- **Costs (rough):** Render api + worker + Postgres + Key Value (~US$7/mo each on
  *starter*; free tiers exist but the api spins down on idle and free Postgres
  expires after 30 days). Vercel Hobby is free. GCP is pay-per-use (Gemini cents
  per call + GCS storage); Qwen/DashScope is per-use.
- **Custom domain (recommended for production):** put web + api on subdomains of
  one domain (`qa.example.com` + `api.example.com`). Then the cookie is same-site
  and you can drop the proxy and call the api directly. Ask and I'll wire the
  Auth.js cookie-domain config.
- **Region:** `render.yaml` uses Singapore (near the `asia-east2` bucket +
  `asia-southeast1` Vertex). Adjust for your data-residency needs.
- **Scaling / beat:** keep exactly one worker instance while it runs embedded beat
  (`-B`). To scale workers, drop `-B` and add a separate 1-instance beat service.
- **Seed content:** the seed also creates the Quam demo data (brokers, HK stock
  glossary). For a clean generic install, delete those after seeding (or ask me to
  split the seed into generic vs demo).
