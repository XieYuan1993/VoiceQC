#!/bin/bash
# CallQA — Step 1 of 3: install the tools the app needs (one time).
# Double-click this file in Finder. It is safe to re-run.

DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

# --- macOS location guard ----------------------------------------------------
# macOS blocks scripts that live in Downloads/Desktop/Documents (and quarantined
# downloads run from a read-only copy) from reading/writing files — you'd see
# "Operation not permitted" or "current working directory must be readable".
case "$DIR" in
  "$HOME"/Downloads/*|"$HOME"/Desktop/*|"$HOME"/Documents/*|*/AppTranslocation/*|/private/var/folders/*)
    clear 2>/dev/null
    echo "============================================================"
    echo "  CallQA — please move this folder first"
    echo "============================================================"
    echo
    echo "  macOS won't let setup run from Downloads, Desktop or Documents"
    echo "  (privacy protection). Move the folder to your Home folder:"
    echo
    echo "    1. In Finder press   Cmd + Shift + H   to open your Home folder."
    echo "    2. Drag the whole 'CallQA-Handoff' folder into it."
    echo "    3. Open  CallQA-Handoff ▸ callqa  and right-click this file"
    echo "       ▸ Open  (just this first time), then Open again."
    echo
    read -r -p "  Press Return to close."
    exit 1
    ;;
esac
set -e
cd "$DIR"

echo "============================================================"
echo "  CallQA — installing prerequisites"
echo "  (Homebrew, uv, Node.js, pnpm, ffmpeg, Docker Desktop)"
echo "============================================================"
echo

# --- Homebrew ---------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
  echo ">> Installing Homebrew (it may ask for your Mac login password)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
[ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
[ -x /usr/local/bin/brew ]   && eval "$(/usr/local/bin/brew shellenv)"

# --- CLI tools --------------------------------------------------------------
echo ">> Installing uv, Node.js, ffmpeg…"
brew install uv node ffmpeg

# --- pnpm (via Node's bundled corepack) -------------------------------------
echo ">> Enabling pnpm…"
corepack enable 2>/dev/null || true
corepack prepare pnpm@latest --activate 2>/dev/null || npm install -g pnpm

# --- Docker Desktop ---------------------------------------------------------
if [ ! -d "/Applications/Docker.app" ]; then
  echo ">> Installing Docker Desktop…"
  brew install --cask docker
fi

echo
echo "============================================================"
echo "  Done."
echo
echo "  NEXT:"
echo "   1. Open **Docker Desktop** (Applications → Docker). Wait until"
echo "      the whale icon in the menu bar stops animating."
echo "   2. Then double-click  2-setup.command"
echo "============================================================"
read -r -p "Press Return to close this window."
