#!/usr/bin/env bash
# First-run setup: copy *.env.example -> *.env (only if absent).
#
# Idempotent. Re-running is safe; existing .env files are not overwritten.
# Generates NEXTAUTH_SECRET / INTERNAL_API_SECRET / APP_ENCRYPTION_KEY on
# first run if the placeholders are still in place.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILES=(
  ".env.example:.env"
  "apps/api/.env.example:apps/api/.env"
  "apps/worker/.env.example:apps/worker/.env"
  "apps/web/.env.example:apps/web/.env.local"
)

for pair in "${ENV_FILES[@]}"; do
  src="${pair%%:*}"
  dst="${pair##*:}"
  if [[ -f "$src" && ! -f "$dst" ]]; then
    cp "$src" "$dst"
    echo "  $src -> $dst"
  else
    [[ -f "$dst" ]] && echo "  $dst already exists (skipped)"
  fi
done

TOP_ENV="$REPO_ROOT/.env"

# Replace a placeholder in .env with a fresh random secret (BSD sed safe).
gen_secret() {
  local placeholder="$1" label="$2"
  if [[ -f "$TOP_ENV" ]] && grep -q "$placeholder" "$TOP_ENV"; then
    local secret
    secret="$(openssl rand -base64 32 2>/dev/null || head -c 32 /dev/urandom | base64)"
    local tmp
    tmp="$(mktemp)"
    sed "s|$placeholder|$secret|g" "$TOP_ENV" > "$tmp"
    mv "$tmp" "$TOP_ENV"
    echo "  generated $label in .env"
  fi
}

# NEXTAUTH_SECRET and APP_ENCRYPTION_KEY share a placeholder string; one
# pass replaces both occurrences with the SAME value, so handle the
# encryption key first with its own placeholder-aware replacement.
if [[ -f "$TOP_ENV" ]]; then
  # APP_ENCRYPTION_KEY line only.
  if grep -q '^APP_ENCRYPTION_KEY=replace-me-with-openssl-rand-base64-32' "$TOP_ENV"; then
    SECRET="$(openssl rand -base64 32 2>/dev/null || head -c 32 /dev/urandom | base64)"
    TMP="$(mktemp)"
    sed "s|^APP_ENCRYPTION_KEY=replace-me-with-openssl-rand-base64-32|APP_ENCRYPTION_KEY=$SECRET|" "$TOP_ENV" > "$TMP"
    mv "$TMP" "$TOP_ENV"
    echo "  generated APP_ENCRYPTION_KEY in .env"
  fi
fi
gen_secret "replace-me-with-openssl-rand-base64-32" "NEXTAUTH_SECRET"
gen_secret "replace-me-internal-secret" "INTERNAL_API_SECRET"

# Mirror shared secrets into apps/web/.env.local (web runs with its own env file).
WEB_ENV="$REPO_ROOT/apps/web/.env.local"
if [[ -f "$WEB_ENV" && -f "$TOP_ENV" ]]; then
  for var in NEXTAUTH_SECRET INTERNAL_API_SECRET APP_ENCRYPTION_KEY; do
    LINE="$(grep "^$var=" "$TOP_ENV" || true)"
    if [[ -n "$LINE" ]] && grep -qE "^$var=replace-me" "$WEB_ENV"; then
      TMP="$(mktemp)"
      grep -v "^$var=" "$WEB_ENV" > "$TMP"
      echo "$LINE" >> "$TMP"
      mv "$TMP" "$WEB_ENV"
      echo "  mirrored $var into $WEB_ENV"
    fi
  done
fi

echo ""
echo "bootstrap: ok"
echo ""
echo "Next steps:"
echo "  uv sync --all-packages"
echo "  pnpm install"
echo "  make up && make migrate && make seed"
