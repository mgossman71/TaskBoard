#!/usr/bin/env bash
# Reproducible load test: fresh isolated stack, seeded with 100 users and 10,000
# tasks, then k6 runs 100 API VUs + 100 WebSocket clients. Results are written to
# tests/load/results/ (summary.json + console output).
#   VUS=100 DURATION=2m ./scripts/load-test.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=forgeboard-load
export APP_PORT="${LOAD_APP_PORT:-18100}"
export APP_BIND_ADDRESS=127.0.0.1
export PUBLIC_BASE_URL=http://web:8080
export POSTGRES_PASSWORD="load-$(date +%s)-password"
export JWT_SECRET="load-jwt-secret-$(date +%s)-0123456789abcdefghijklmnop"
COMPOSE=(docker compose -f compose.yaml -f compose.load.yaml --env-file /dev/null)
cleanup() { [ "${KEEP:-0}" = 1 ] || "${COMPOSE[@]}" --profile load down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
mkdir -p tests/load/results
"${COMPOSE[@]}" up -d --build --wait
"${COMPOSE[@]}" exec -T api python -m forgeboard.cli seed-load --users 100 --tasks 10000 --projects 5 --out /tmp/seed.json
"${COMPOSE[@]}" exec -T api cat /tmp/seed.json > tests/load/results/seed.json
"${COMPOSE[@]}" --profile load run --rm k6 2>&1 | tee tests/load/results/k6-output.txt
"${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) as tasks from tasks"' | tee -a tests/load/results/k6-output.txt
