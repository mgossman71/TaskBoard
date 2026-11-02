#!/usr/bin/env bash
# Typecheck + Vitest unit/component tests inside the frontend image's `test` stage.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -q --target test -t taskboard-web-test ./frontend >/dev/null
docker run --rm taskboard-web-test
