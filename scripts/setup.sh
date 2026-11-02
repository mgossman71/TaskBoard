#!/usr/bin/env bash
# One-step install/upgrade:
#   ./scripts/setup.sh            # configure .env, then docker compose up -d --build
#   ./scripts/setup.sh --no-start # configure only
#
# Safe to re-run. It
#   1. creates .env from .env.example if missing and generates secrets (placeholders only),
#   2. keeps APP_PORT if it is free (or already used by this TaskBoard), otherwise picks the
#      next free port,
#   3. sets PUBLIC_BASE_URL to http://<this host's IP>:<port> unless you set your own URL,
#   4. starts the stack and waits until it is healthy.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=.env
START=1
[ "${1:-}" = "--no-start" ] && START=0

[ -f "$ENV_FILE" ] || { cp .env.example "$ENV_FILE"; echo "Created $ENV_FILE from .env.example"; }
./scripts/generate-secrets.sh "$ENV_FILE" >/dev/null
echo "Secrets: OK"

get() { awk -F= -v k="$1" '$1==k{print substr($0, index($0,"=")+1); exit}' "$ENV_FILE"; }
put() { # put KEY VALUE  (replace or append, portable sed)
  if grep -qE "^$1=" "$ENV_FILE"; then
    local esc; esc=$(printf '%s' "$2" | sed 's/[&|]/\\&/g')
    sed -i.bak -E "s|^$1=.*|$1=${esc}|" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
  else
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
  fi
}

PROJECT="${COMPOSE_PROJECT_NAME:-$(get COMPOSE_PROJECT_NAME)}"
PROJECT="${PROJECT:-taskboard}"
OWN_WEB="${PROJECT}-web-1"

# Is TCP port $1 taken by something other than this TaskBoard's web container?
port_busy() {
  local p="$1" owner
  owner=$(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -E "(0\.0\.0\.0|\[::\]|127\.0\.0\.1|:::?):${p}->" | awk '{print $1}' | head -1 || true)
  if [ -n "$owner" ]; then
    [ "$owner" = "$OWN_WEB" ] && return 1 || return 0
  fi
  if command -v ss >/dev/null 2>&1; then
    [ -n "$(ss -ltnH "sport = :${p}" 2>/dev/null)" ] && return 0
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  (exec 3<>"/dev/tcp/127.0.0.1/${p}") 2>/dev/null && { exec 3>&- 3<&- 2>/dev/null; return 0; }
  return 1
}

PORT="$(get APP_PORT)"; PORT="${PORT:-8080}"
OLD_PORT="$PORT"
if port_busy "$PORT"; then
  for cand in $(seq $((PORT + 1)) $((PORT + 200))); do
    if ! port_busy "$cand"; then PORT="$cand"; break; fi
  done
  [ "$PORT" != "$OLD_PORT" ] || { echo "No free port found near $OLD_PORT; set APP_PORT in .env" >&2; exit 1; }
  echo "Port $OLD_PORT is in use by something else; using $PORT"
fi
put APP_PORT "$PORT"

# Address users will open. Only auto-set when it is still a localhost default.
URL="$(get PUBLIC_BASE_URL)"
case "$URL" in
  ""|http://localhost*|http://127.0.0.1*)
    HOSTADDR=""
    if command -v hostname >/dev/null 2>&1 && hostname -I >/dev/null 2>&1; then
      HOSTADDR=$(hostname -I | awk '{print $1}')
    fi
    [ -n "$HOSTADDR" ] || HOSTADDR=$(ipconfig getifaddr en0 2>/dev/null || true)
    [ -n "$HOSTADDR" ] || HOSTADDR=localhost
    URL="http://${HOSTADDR}:${PORT}"
    put PUBLIC_BASE_URL "$URL"
    ;;
  *)
    case "$URL" in *":$OLD_PORT"*) [ "$PORT" != "$OLD_PORT" ] && echo "NOTE: PUBLIC_BASE_URL ($URL) still mentions port $OLD_PORT; update it if users reach TaskBoard on $PORT." ;; esac
    ;;
esac
chmod 600 "$ENV_FILE"
echo "Port: $PORT   Public URL: $URL"

[ "$START" = 1 ] || exit 0
docker compose up -d --build --wait
docker compose ps
echo
echo "TaskBoard is running: $URL"
