#!/usr/bin/env bash
# Runs the Playwright end-to-end suite against a fresh, isolated deployment
# (compose project "forgeboard-e2e", throwaway volumes and secrets).
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=forgeboard-e2e
export APP_PORT="${E2E_APP_PORT:-18080}"
export APP_BIND_ADDRESS=127.0.0.1
export BACKEND_SUBNET=172.30.251.0/24   # distinct from the main stack so both can run
export POSTGRES_PASSWORD="e2e-$(date +%s)-db-password"
export JWT_SECRET="e2e-jwt-secret-$(date +%s)-0123456789abcdef0123456789"
export PUBLIC_BASE_URL=http://web:8080
COMPOSE=(docker compose -f compose.yaml -f compose.e2e.yaml --env-file /dev/null)
cleanup() { "${COMPOSE[@]}" --profile e2e down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
"${COMPOSE[@]}" up -d --build --wait db redis api web mailpit
"${COMPOSE[@]}" --profile e2e run --rm e2e sh -c "npm ci --no-audit --no-fund >/dev/null && npx playwright test $*"
