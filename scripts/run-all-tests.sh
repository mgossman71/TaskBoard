#!/usr/bin/env bash
# Runs every automated suite in isolated environments and prints a summary.
# Usage: ./scripts/run-all-tests.sh [--with-load]
set -uo pipefail
cd "$(dirname "$0")/.."
SUMMARY=""
RC=0
run() {
  local name="$1"; shift
  echo; echo "################ $name ################"
  if "$@"; then SUMMARY="${SUMMARY}$(printf '%-10s PASS' "$name")\n"; else SUMMARY="${SUMMARY}$(printf '%-10s FAIL' "$name")\n"; RC=1; fi
}
run backend   ./scripts/test-backend.sh -q
run frontend  ./scripts/test-frontend.sh
run e2e       ./scripts/test-e2e.sh
run deploy    ./scripts/deploy-check.sh
if [ "${1:-}" = "--with-load" ]; then run load ./scripts/load-test.sh; fi
echo; echo "================ SUMMARY ================"
printf "%b" "$SUMMARY"
exit $RC
