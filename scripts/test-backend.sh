#!/usr/bin/env bash
# Runs the backend test suite (pytest) against real PostgreSQL + Redis in an
# isolated compose project. Extra args are passed to pytest.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=taskboard-test
cleanup() { docker compose -p "$PROJECT" -f compose.test.yaml down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose -p "$PROJECT" -f compose.test.yaml build -q api-test
docker compose -p "$PROJECT" -f compose.test.yaml run --rm api-test pytest "$@"
