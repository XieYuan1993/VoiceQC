#!/bin/bash
# CallQA — reset the demo login. Double-click to run.
# Use this if sign-in says "Invalid email or password" even though the password
# is correct — the account locks after several wrong tries. This unlocks it and
# restores the admin password.

DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
case "$DIR" in
  "$HOME"/Downloads/*|"$HOME"/Desktop/*|"$HOME"/Documents/*|*/AppTranslocation/*|/private/var/folders/*)
    echo "  Move the 'CallQA-Handoff' folder to your Home folder first"
    echo "  (Finder ▸ Cmd+Shift+H), then double-click this file again."
    read -r -p "  Press Return to close."; exit 1 ;;
esac
cd "$DIR"
[ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
[ -x /usr/local/bin/brew ]   && eval "$(/usr/local/bin/brew shellenv)"
export PATH="$HOME/.local/bin:$PATH"

if ! docker exec voiceqa-postgres pg_isready -U voiceqa -d voiceqa >/dev/null 2>&1; then
  echo "The database isn't running. Open Docker Desktop and run start.command first."
  read -r -p "Press Return to close."; exit 1
fi

echo "Resetting the demo login (admin@local.test)…"
uv run python - <<'PY'
import asyncio, os
from dotenv import load_dotenv
load_dotenv(".env")
from voiceqa_shared.passwords import hash_password
import asyncpg

async def main():
    h = hash_password("voiceqa-admin-1")
    dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    r = await conn.execute(
        "UPDATE users SET password_hash=$1, locked_until=NULL, failed_login_attempts=0, "
        "is_active=true WHERE lower(email)='admin@local.test'", h)
    await conn.close()
    print("  database:", r)

asyncio.run(main())
PY

echo
echo "============================================================"
echo "  Login reset.  Sign in (TYPE it — don't paste):"
echo "    email     :  admin@local.test"
echo "    password  :  voiceqa-admin-1"
echo "                 (all lowercase, two hyphens, ends in the DIGIT 1)"
echo "============================================================"
read -r -p "Press Return to close."
