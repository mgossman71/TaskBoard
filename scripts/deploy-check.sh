#!/usr/bin/env bash
# Deployment acceptance check, run against an isolated compose project with its
# own volumes (never touches your real data):
#   images build -> containers healthy -> migrations at head -> API + assets ->
#   WebSocket through nginx -> create data + attachment -> `down` -> `up --build`
#   -> data and files still present.
# Requires only bash, curl and Docker on the host.
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=taskboard-deploycheck
export APP_PORT="${CHECK_APP_PORT:-18090}"
export APP_BIND_ADDRESS=127.0.0.1
export BACKEND_SUBNET=172.30.252.0/24   # distinct from the main stack so both can run
BASE="http://127.0.0.1:${APP_PORT}"
export PUBLIC_BASE_URL="$BASE"
export POSTGRES_PASSWORD="dc-$(openssl rand -hex 16 2>/dev/null || date +%s%N)"
export JWT_SECRET="dc-$(openssl rand -hex 32 2>/dev/null || date +%s%N)-jwt-secret-padding"
COMPOSE=(docker compose -f compose.yaml --env-file /dev/null)
PASS=0; FAIL=0
ok() { echo "  PASS  $*"; PASS=$((PASS+1)); }
bad() { echo "  FAIL  $*"; FAIL=$((FAIL+1)); }
check() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
json() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null || docker run --rm -i python:3.13-slim python -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
cleanup() { [ "${KEEP:-0}" = 1 ] || "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

all_healthy() {
  for s in db redis api web; do
    st=$("${COMPOSE[@]}" ps --format '{{.Health}}' "$s" 2>/dev/null)
    [ "$st" = "healthy" ] || return 1
  done
}
wait_healthy() { for _ in $(seq 1 90); do all_healthy && return 0; sleep 2; done; return 1; }

echo "== 1. Build images and start stack"
check "docker compose up -d --build" "${COMPOSE[@]}" up -d --build
check "all services healthy" wait_healthy
"${COMPOSE[@]}" ps
check "migrate job exited 0" test "$("${COMPOSE[@]}" ps -a --format '{{.ExitCode}}' migrate)" = "0"
check "postgres/redis/api not published on host" test -z "$(for s in db redis api; do docker port "$("${COMPOSE[@]}" ps -q "$s")"; done)"

echo "== 2. Endpoints"
check "nginx /healthz" curl -fsS "$BASE/healthz"
check "API liveness" curl -fsS "$BASE/api/health"
READY=$(curl -fsS "$BASE/api/health/ready" || true)
check "API readiness reports schema head 0001" grep -q '"schema_version":"0001"' <<<"$READY"
VER=$("${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version"' | tr -d '[:space:]')
check "alembic_version table at head" test "$VER" = "0001"
INDEX=$(curl -fsS "$BASE/")
check "frontend index served" grep -q '<div id="root">' <<<"$INDEX"
ASSET=$(grep -oE '/assets/[^"]+\.js' <<<"$INDEX" | head -1)
check "hashed JS asset served with immutable caching" sh -c "curl -fsSI '$BASE$ASSET' | grep -qi 'immutable'"
check "SPA deep link returns index (refresh-safe)" sh -c "curl -fsS '$BASE/o/x/p/y/board' | grep -q 'id=\"root\"'"
check "security headers present" sh -c "curl -fsSI '$BASE/' | grep -qi 'content-security-policy'"

echo "== 3. Create data through the public endpoint"
EMAIL="deploy-$(date +%s)@example.com"
TOKEN=$(curl -fsS -X POST "$BASE/api/v1/auth/register" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"Deploy-Check-Passw0rd!\",\"display_name\":\"Deploy Check\"}" | json 'd["access_token"]')
check "register user" test -n "$TOKEN"
AUTH=(-H "authorization: Bearer $TOKEN" -H 'content-type: application/json')
ORG=$(curl -fsS -X POST "$BASE/api/v1/orgs" "${AUTH[@]}" -d '{"name":"Persistence Org"}' | json 'd["id"]')
PROJ=$(curl -fsS -X POST "$BASE/api/v1/orgs/$ORG/projects" "${AUTH[@]}" -d '{"name":"Persistence","key":"PER"}' | json 'd["id"]')
T1=$(curl -fsS -X POST "$BASE/api/v1/projects/$PROJ/tasks" "${AUTH[@]}" -d '{"title":"Survive restarts"}' | json 'd["id"]')
T2=$(curl -fsS -X POST "$BASE/api/v1/projects/$PROJ/tasks" "${AUTH[@]}" -d '{"title":"Second"}' | json 'd["id"]')
curl -fsS -X POST "$BASE/api/v1/tasks/$T2/dependencies" "${AUTH[@]}" -d "{\"depends_on_id\":\"$T1\"}" >/dev/null
curl -fsS -X POST "$BASE/api/v1/tasks/$T1/comments" "${AUTH[@]}" -d '{"body":"persist me"}' >/dev/null
printf 'attachment payload %s\n' "$(date)" > /tmp/fb-deploycheck.txt
ATT=$(curl -fsS -X POST "$BASE/api/v1/tasks/$T1/attachments" -H "authorization: Bearer $TOKEN" -F "file=@/tmp/fb-deploycheck.txt;type=text/plain" | json 'd["id"]')
check "created org/project/tasks/dependency/comment/attachment" test -n "$ATT"

echo "== 4. WebSocket through nginx"
WS=$(python3 tests/deploy/ws_check.py "$BASE" "$TOKEN" "$PROJ" 2>&1 || docker run --rm --network host -v "$PWD/tests/deploy:/t" python:3.13-slim python /t/ws_check.py "$BASE" "$TOKEN" "$PROJ" 2>&1 || true)
check "WebSocket auth + subscribe via nginx" grep -q WS_OK <<<"$WS"

echo "== 4b. Hardening"
check "no .env file tracked by git (only .env.example)" sh -c "! git ls-files | grep -E '(^|/)\.env' | grep -vx '.env.example'"
TRUSTED=$("${COMPOSE[@]}" exec -T api printenv FORWARDED_ALLOW_IPS | tr -d '\r')
NETSUB=$(docker network inspect "${COMPOSE_PROJECT_NAME}_backend" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
check "API trusts X-Forwarded-For only from the pinned backend subnet ($TRUSTED)" test "$TRUSTED" = "$NETSUB" -a "$TRUSTED" = "$BACKEND_SUBNET"
check "no HSTS header by default (plain HTTP)" sh -c "! curl -fsSI '$BASE/' | grep -qi strict-transport-security"
# Forged X-Forwarded-For from an untrusted peer (127.0.0.1 inside the api container) must not
# give each attempt a fresh client IP: the 6th wrong password is locked out (429).
SPOOF=$("${COMPOSE[@]}" exec -T api python - <<'PY'
import json, urllib.request, urllib.error
codes = []
for i in range(6):
    req = urllib.request.Request("http://127.0.0.1:8000/api/v1/auth/login", method="POST",
        data=json.dumps({"email": "spoof-target@example.com", "password": "Wrong-Passw0rd!"}).encode(),
        headers={"content-type": "application/json", "x-forwarded-for": f"203.0.113.{i + 1}"})
    try:
        codes.append(urllib.request.urlopen(req, timeout=10).status)
    except urllib.error.HTTPError as e:
        codes.append(e.code)
print(",".join(map(str, codes)))
PY
)
check "forged X-Forwarded-For is ignored from untrusted peers (codes: $SPOOF)" test "$SPOOF" = "401,401,401,401,401,429"
# Through nginx: a client-supplied X-Forwarded-For is overwritten, so it cannot dodge lockout either.
NG=""
for i in 1 2 3 4 5 6; do
  NG="$NG$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/v1/auth/login" -H 'content-type: application/json' -H "X-Forwarded-For: 198.51.100.$i" -d '{"email":"spoof-nginx@example.com","password":"Wrong-Passw0rd!"}'),"
done
check "forged X-Forwarded-For via nginx cannot evade lockout (codes: ${NG%,})" test "${NG%,}" = "401,401,401,401,401,429"
BIG=$(head -c 1200000 /dev/zero | tr '\0' 'x' | curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/v1/auth/login" -H 'content-type: application/json' --data-binary @-)
check "oversized JSON body rejected (HTTP $BIG)" test "$BIG" = "413"

echo "== 5. Recreate containers (down + up --build) and verify persistence"
check "docker compose down" "${COMPOSE[@]}" down
check "docker compose up -d --build (again)" "${COMPOSE[@]}" up -d --build
check "all services healthy after recreation" wait_healthy
TOKEN2=$(curl -fsS -X POST "$BASE/api/v1/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"Deploy-Check-Passw0rd!\"}" | json 'd["access_token"]')
check "user account survived (login works)" test -n "$TOKEN2"
DETAIL=$(curl -fsS "$BASE/api/v1/tasks/$T1" -H "authorization: Bearer $TOKEN2")
check "task survived" grep -q 'Survive restarts' <<<"$DETAIL"
check "comment survived" grep -q 'persist me' <<<"$DETAIL"
DEP=$(curl -fsS "$BASE/api/v1/tasks/$T2/dependencies" -H "authorization: Bearer $TOKEN2")
check "dependency survived" grep -q "$T1" <<<"$DEP"
ACT=$(curl -fsS "$BASE/api/v1/projects/$PROJ/activity" -H "authorization: Bearer $TOKEN2")
check "activity history survived" grep -q 'task.created' <<<"$ACT"
DL=$(curl -fsS "$BASE/api/v1/attachments/$ATT/download" -H "authorization: Bearer $TOKEN2")
check "attachment file survived (byte-identical)" test "$DL" = "$(cat /tmp/fb-deploycheck.txt)"
check "migrations re-ran idempotently (exit 0)" test "$("${COMPOSE[@]}" ps -a --format '{{.ExitCode}}' migrate)" = "0"
rm -f /tmp/fb-deploycheck.txt

echo "== Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
