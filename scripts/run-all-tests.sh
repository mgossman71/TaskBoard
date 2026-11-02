#!/usr/bin/env bash
# Runs every automated suite in isolated environments and prints a summary.
# Usage: ./scripts/run-all-tests.sh [--with-load]
set -uo pipefail
cd "$(dirname "$0")/.."
declare -A RESULT
run() {
  local name="$1"; shift
  echo; echo "################ $name ################"
  if "$@"; then RESULT[$name]=PASS; else RESULT[$name]=FAIL; fi
}
run backend   ./scripts/test-backend.sh -q
run frontend  ./scripts/test-frontend.sh
run e2e       ./scripts/test-e2e.sh
run deploy    ./scripts/deploy-check.sh
[ "${1:-}" = "--with-load" ] && run load ./scripts/load-test.sh
echo; echo "================ SUMMARY ================"
rc=0
for k in backend frontend e2e deploy load; do
  [ -n "${RESULT[$k]:-}" ] && { printf '%-10s %s\n' "$k" "${RESULT[$k]}"; [ "${RESULT[$k]}" = PASS ] || rc=1; }
done
exit $rc
