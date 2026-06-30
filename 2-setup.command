#!/bin/bash
# CallQA — Step 2 of 3: one-time project setup.
# Run 1-install-tools.command first, and make sure Docker Desktop is running.

DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

# --- macOS location guard (see 1-install-tools.command for why) --------------
case "$DIR" in
  "$HOME"/Downloads/*|"$HOME"/Desktop/*|"$HOME"/Documents/*|*/AppTranslocation/*|/private/var/folders/*)
    clear 2>/dev/null
    echo "============================================================"
    echo "  CallQA — please move this folder first"
    echo "============================================================"
    echo
    echo "  macOS won't let setup run from Downloads, Desktop or Documents"
    echo "  (that's the 'Operation not permitted' error). Move it to Home:"
    echo
    echo "    1. In Finder press   Cmd + Shift + H   to open your Home folder."
    echo "    2. Drag the whole 'CallQA-Handoff' folder into it."
    echo "    3. Open  CallQA-Handoff ▸ callqa  and double-click this file again."
    echo
    read -r -p "  Press Return to close."
    exit 1
    ;;
esac
set -e
cd "$DIR"
REPO="$DIR"

# Put the tools on PATH (Finder launches with a minimal PATH)
[ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
[ -x /usr/local/bin/brew ]   && eval "$(/usr/local/bin/brew shellenv)"
export PATH="$HOME/.local/bin:$PATH"
corepack enable 2>/dev/null || true

echo "============================================================"
echo "  CallQA — first-time setup"
echo "============================================================"

# 1) Point the bundled service-account key at THIS folder ------------------
echo ">> Configuring credentials path…"
if ! sed -i '' "s|__REPO__|$REPO|g" .env 2>/dev/null; then
  echo
  echo "  !! Could not edit .env (\"Operation not permitted\")."
  echo "     This folder is still in a location macOS protects. Move the"
  echo "     CallQA-Handoff folder to your Home folder (Cmd+Shift+H in Finder)"
  echo "     and run this script again."
  read -r -p "  Press Return to close."; exit 1
fi

# 2) Docker must be running -------------------------------------------------
if ! docker info >/dev/null 2>&1; then
  echo
  echo "  !! Docker Desktop is not running."
  echo "     Open it (Applications → Docker), wait for the whale icon in the"
  echo "     menu bar to go steady, then double-click this file again."
  read -r -p "Press Return to close."; exit 1
fi

# 3) Install dependencies ---------------------------------------------------
echo ">> Installing Python dependencies (uv)…  [a few minutes the first time]"
uv sync --all-packages
echo ">> Installing web dependencies (pnpm)…"
pnpm install

# 4) Start the data services (Postgres, Redis, MailHog) ---------------------
echo ">> Starting Postgres + Redis…"
make up
echo ">> Waiting for the database to be ready…"
until docker exec voiceqa-postgres pg_isready -U voiceqa -d voiceqa >/dev/null 2>&1; do sleep 1; done

# 5) Load the demo database (40 calls, evaluations, knowledge base, login) --
echo ">> Loading the demo data…"
docker exec -i voiceqa-postgres psql -q -U voiceqa -d voiceqa < data/voiceqa.sql > logs-restore.txt 2>&1
RECS=$(docker exec voiceqa-postgres psql -U voiceqa -d voiceqa -t -A -c "select count(*) from recordings;" 2>/dev/null | tr -d '[:space:]')
if [ -z "$RECS" ] || [ "$RECS" = "0" ]; then
  echo
  echo "  !! The demo data did NOT load (found 0 recordings)."
  echo "     Without it there is no login and no data. Last lines of the restore log:"
  tail -15 logs-restore.txt | sed 's/^/       /'
  echo
  echo "     Check Docker Desktop is running and that this folder is in your HOME"
  echo "     folder (not Downloads/Desktop/Documents), then run this script again."
  read -r -p "  Press Return to close."; exit 1
fi
echo "   loaded $RECS recordings, login restored."

echo
echo "============================================================"
echo "  Setup complete  ✅   ($RECS demo calls loaded)"
echo
echo "  NEXT:  double-click  start.command  to launch the app."
echo "         Login:  admin@local.test  /  voiceqa-admin-1"
echo "============================================================"
read -r -p "Press Return to close."
