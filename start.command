#!/bin/bash
# CallQA — Step 3 of 3: start the app. Double-click to run.
# Leaves three background services running and opens your browser.

DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

# --- macOS location guard ----------------------------------------------------
case "$DIR" in
  "$HOME"/Downloads/*|"$HOME"/Desktop/*|"$HOME"/Documents/*|*/AppTranslocation/*|/private/var/folders/*)
    clear 2>/dev/null
    echo "  CallQA can't run from Downloads/Desktop/Documents."
    echo "  Move the 'CallQA-Handoff' folder to your Home folder"
    echo "  (Finder ▸ Cmd+Shift+H), then double-click this file again."
    read -r -p "  Press Return to close."
    exit 1
    ;;
esac
cd "$DIR"

[ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
[ -x /usr/local/bin/brew ]   && eval "$(/usr/local/bin/brew shellenv)"
export PATH="$HOME/.local/bin:$PATH"
corepack enable 2>/dev/null || true
mkdir -p logs

# preflight: tools must be on PATH (clear message instead of a silent failure)
for t in docker uv pnpm; do
  command -v "$t" >/dev/null 2>&1 || {
    echo "⚠  '$t' isn't installed or on PATH. Run 1-install-tools.command first."
    read -r -p "Press Return to close."; exit 1; }
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop isn't running — open it first, then re-run this."
  read -r -p "Press Return to close."; exit 1
fi

echo "Starting data services (Postgres, Redis)…"
make up >/dev/null 2>&1

echo "Starting API, worker, and web…  (the first start compiles for ~30–60s)"
( cd apps/api    && nohup uv run uvicorn app.main:app --port 7870 --host 0.0.0.0 >../../logs/api.log    2>&1 & )
( cd apps/worker && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES nohup uv run celery -A worker.celery_app worker --loglevel=info -Q default,audio,stt,llm -B >../../logs/worker.log 2>&1 & )
( cd apps/web    && nohup pnpm dev >../../logs/web.log 2>&1 & )

wait_up () { # $1=url  $2=tries (×2s)
  local n=0
  while [ "$n" -lt "$2" ]; do
    curl -s -o /dev/null "$1" && return 0
    sleep 2; n=$((n + 1))
  done
  return 1
}

echo "Waiting for the web app (port 3020)…"
WEB_OK=0; wait_up http://localhost:3020 60 && WEB_OK=1
echo "Waiting for the API (port 7870)…"
API_OK=0; wait_up http://localhost:7870/api/healthz 30 && API_OK=1
echo "Checking the demo data…"
DATA_OK=0
docker exec voiceqa-postgres psql -U voiceqa -d voiceqa -t -A -c \
  "select 1 from users where lower(email)='admin@local.test' limit 1" 2>/dev/null | grep -q 1 && DATA_OK=1

echo
echo "============================================================"
if [ "$WEB_OK" = "1" ] && [ "$API_OK" = "1" ] && [ "$DATA_OK" = "1" ]; then
  open http://localhost:3020 2>/dev/null
  echo "  CallQA is running.  ✅"
  echo "    App   :  http://localhost:3020"
  echo "    Login :  admin@local.test  /  voiceqa-admin-1"
  echo
  echo "  • First load of each page compiles for a few seconds, then it's instant."
  echo "  • If THIS window says running but your browser still can't connect,"
  echo "    your browser/VPN may be routing localhost through a proxy — try"
  echo "    http://127.0.0.1:3020 or a different browser."
  echo "  • To stop everything later, double-click  stop.command"
elif [ "$WEB_OK" = "1" ] && [ "$API_OK" = "1" ] && [ "$DATA_OK" = "0" ]; then
  echo "  ⚠  The app is up, but the demo DATABASE IS EMPTY."
  echo
  echo "  No login and no data yet — sign-in will say \"Invalid email or"
  echo "  password\" and pages will error. The data-load step hasn't run."
  echo
  echo "  Fix:  double-click  2-setup.command  to load the 40 demo calls and the"
  echo "        admin login. Keep the CallQA-Handoff folder in your HOME folder."
else
  echo "  ⚠  CallQA did not fully start."
  if [ "$WEB_OK" = "0" ]; then
    echo
    echo "  Web app (port 3020) did not come up — last lines of logs/web.log:"
    echo "  ------------------------------------------------------------"
    tail -20 logs/web.log 2>/dev/null | sed 's/^/    /'
  fi
  if [ "$API_OK" = "0" ]; then
    echo
    echo "  API (port 7870) did not come up — last lines of logs/api.log:"
    echo "  ------------------------------------------------------------"
    tail -20 logs/api.log 2>/dev/null | sed 's/^/    /'
  fi
  echo
  echo "  Wait a minute and double-click start.command again. If it still"
  echo "  fails, send the lines above (and the logs/ folder) to your contact."
fi
echo "============================================================"
read -r -p "Press Return to close this window (the app keeps running)."
