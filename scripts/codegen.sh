#!/usr/bin/env bash
# Regenerate packages/shared-types/src/api.ts from FastAPI's OpenAPI doc.
#
# Steps:
# 1. Boot apps/api headless and dump its OpenAPI schema to openapi.json.
# 2. Run openapi-typescript over it.
# 3. Delete openapi.json.
#
# CI runs `make codegen` then `git diff --exit-code packages/shared-types/src/api.ts`
# to fail loudly on drift between the FastAPI schemas and the committed types.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

OPENAPI_JSON="$REPO_ROOT/openapi.json"
TARGET="$REPO_ROOT/packages/shared-types/src/api.ts"

# 1. Dump the OpenAPI schema. Run from apps/api so the local pyproject + .env
# are picked up; the schema is emitted to stdout as JSON.
(cd apps/api && uv run python -c "
import json, sys
from app.main import app
json.dump(app.openapi(), sys.stdout, indent=2)
") > "$OPENAPI_JSON"

# 2. Generate TS.
(cd packages/shared-types && pnpm exec openapi-typescript "$OPENAPI_JSON" -o ./src/api.ts)

# 3. Cleanup.
rm -f "$OPENAPI_JSON"

echo "codegen: ok -> $TARGET"
