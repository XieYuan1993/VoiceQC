# Running VoiceQA locally on macOS

A step-by-step guide to get the app running on a fresh Mac from a copy of the
source code. No prior knowledge of the stack is assumed — just follow the steps
in order.

Expect ~20–30 minutes the first time (most of it is downloads).

---

## What you're running

VoiceQA is a small monorepo. Locally it's **three app processes** you start by
hand, plus **three data services** that run in Docker:

```
  ┌─ app processes (you run these in 3 terminals) ──────────────┐
  │  web      Next.js UI          http://localhost:3020         │
  │  api      FastAPI backend     http://localhost:7870         │
  │  worker   Celery (audio →     (no URL — background jobs)     │
  │           transcribe → score)                               │
  └─────────────────────────────────────────────────────────────┘
  ┌─ data services (Docker, started with `make up`) ────────────┐
  │  postgres  database     localhost:55433                     │
  │  redis     job queue    localhost:56380                     │
  │  mailhog   fake email   http://localhost:8026               │
  └─────────────────────────────────────────────────────────────┘
```

> The ports are deliberately unusual (55433, 56380, 3020, 7870…) so nothing
> clashes with other apps. Just make sure they're free.

---

## 0. What you need before you start

1. **The source code folder** (you have it).
2. **Credentials from the person who sent you this** — needed only to actually
   *transcribe and score* a call. You can boot the app, log in, and click
   around the UI **without** them. Ask them for:

   | What | Used for |
   |---|---|
   | A Google Cloud **service-account JSON key** file | Gemini scoring + GCS audio storage |
   | The Google Cloud **project ID** | same |
   | The **GCS bucket name** | where audio is stored |
   | **DashScope (Qwen) API key** + **base URL** | speech-to-text (the default transcriber) |

   > These are secrets — get them over a secure channel (password manager,
   > encrypted message), not plain email/Slack. You'll drop them into a local
   > `.env` file in Step 3.

---

## 1. Install the toolchain (one-time)

Open **Terminal** and install [Homebrew](https://brew.sh) if you don't have it:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install everything else:

```bash
# Docker Desktop — the database/redis/mailhog containers
brew install --cask docker

# uv — Python package manager (also fetches Python 3.12 automatically)
brew install uv

# Node.js 20 + pnpm (the JS package manager)
brew install node@20
corepack enable && corepack prepare pnpm@latest --activate

# ffmpeg — the worker uses it to split call audio into channels
brew install ffmpeg
```

**Launch Docker Desktop once** (open it from Applications / Spotlight) and wait
for the whale icon in the menu bar to go steady — it must be running before
Step 2's `make up`. You don't need a Docker account; skip any sign-in prompt.

> You do **not** need to install Python or Postgres yourself — `uv` brings its
> own Python, and Postgres runs inside Docker.

---

## 2. First-time project setup

`cd` into the source folder (adjust the path to wherever you put it):

```bash
cd ~/Documents/CallQA          # <- wherever the folder lives
```

Then run these once, in order:

```bash
make bootstrap            # creates local .env files + generates secret keys
uv sync --all-packages    # installs Python deps  (the --all-packages flag matters)
pnpm install              # installs JavaScript deps
make up                   # starts postgres + redis + mailhog in Docker
make migrate              # creates the database tables
make seed                 # creates the admin login + starter data
```

What these do:
- **`make bootstrap`** copies `*.env.example` → real `.env` files and auto-generates
  the local security keys. Safe to re-run; it never overwrites existing files.
- **`make up`** must be run *after* Docker Desktop is up. Re-run it any time you
  restart your Mac. Check it's healthy with `make ps`.
- **`make seed`** creates the login: **`admin@local.test` / `voiceqa-admin-1`**.

---

## 3. Add the credentials (for transcription + scoring)

Skip this if you only want to explore the UI. To process real calls, open the
**`.env`** file in the project root in any text editor and fill in these lines
(use the values handed to you in Step 0):

```ini
# point this at the Google service-account key file you were given
# (uncomment the line — remove the leading "#")
GOOGLE_APPLICATION_CREDENTIALS=/Users/you/Documents/keys/gcp-sa.json
GOOGLE_CLOUD_PROJECT=the-project-id
GCS_BUCKET_AUDIO=the-bucket-name

# Qwen / DashScope — the default speech-to-text provider
DASHSCOPE_API_KEY=the-key
DASHSCOPE_BASE_URL=https://<your-host>.ap-southeast-1.maas.aliyuncs.com
```

Save the file. If the worker is already running, **restart it** (Ctrl-C, then
`make worker.dev` again) so it picks up the new values.

> Put the `.json` key file anywhere on your Mac and use its **full path** above.
> Don't move it into the project folder.

---

## 4. Run the app (three terminal tabs)

Open **three Terminal tabs**, `cd` into the project folder in each, and run one
command per tab:

| Tab | Command | What it is |
|---|---|---|
| 1 | `make api.dev` | FastAPI backend → http://localhost:7870/api/docs |
| 2 | `make worker.dev` | Celery worker (background jobs) |
| 3 | `make web.dev` | Next.js UI → http://localhost:3020 |

Leave all three running. Then open **http://localhost:3020** in your browser
and sign in:

```
email:    admin@local.test
password: voiceqa-admin-1
```

---

## 5. Check everything works

- **UI**: http://localhost:3020 loads and you can log in. ✅
- **API**: http://localhost:7870/api/docs shows the interactive API docs;
  http://localhost:7870/api/healthz returns `{"status":"ok"}`. ✅
- **Worker**: tab 2 prints a startup banner ending in `celery@… ready.` and
  lists the queues `default, audio, stt, llm`. ✅
- **Email**: http://localhost:8026 (MailHog) is where any app emails
  (e.g. password resets) show up — nothing actually leaves your machine. ✅
- **Full pipeline** (needs Step 3 creds): in the UI, open the **Evaluator**, add
  or generate some criteria, create a **batch**, and upload a short call
  recording. Watch tab 2 — you'll see it transcribe then score. ✅

---

## Day-to-day (after the first setup)

You only do Step 2 once. On a normal day:

```bash
make up          # if Docker was restarted (no-op if already running)
# then the three tabs:
make api.dev
make worker.dev
make web.dev
```

To stop the Docker services at the end of the day: `make down`
(your data is kept). The three app tabs stop with Ctrl-C.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make up` errors / "Cannot connect to the Docker daemon" | Docker Desktop isn't running — open it, wait for the menu-bar whale, retry. |
| `make: command not found` | Install Xcode command-line tools: `xcode-select --install`. |
| `uv: command not found` / `pnpm: command not found` | Close and reopen Terminal (so PATH refreshes). For pnpm: re-run `corepack enable`. |
| `make migrate` fails to connect | Postgres isn't ready yet. Run `make ps` — wait until `postgres` is `healthy`, then retry. |
| Port already in use (3020 / 7870 / 55433 …) | Something else is using it. Find it: `lsof -i :3020`, then quit that app (or stop the conflicting service). |
| Upload never finishes / "transcription failed" | Credentials missing or wrong in `.env` (Step 3), or you forgot to restart the worker after editing. Also confirm `ffmpeg` is installed: `ffmpeg -version`. |
| Want a totally clean slate | `make down-clean` wipes the database, then re-run `make up && make migrate && make seed`. (Destroys all local data.) |
| See all available shortcuts | `make help` |

---

## Command reference

| Command | Does |
|---|---|
| `make bootstrap` | Create `.env` files + generate secret keys (first run) |
| `make up` / `make down` | Start / stop the Docker data services |
| `make ps` / `make logs` | Status / live logs of the Docker services |
| `make migrate` | Apply database schema |
| `make seed` | Create admin user + starter data |
| `make api.dev` | Run the FastAPI backend (port 7870) |
| `make worker.dev` | Run the Celery worker |
| `make web.dev` | Run the Next.js UI (port 3020) |
| `make down-clean` | Stop Docker **and wipe all local data** |
| `make help` | List every available command |

Login after seeding: **`admin@local.test` / `voiceqa-admin-1`**.
