#!/usr/bin/env bash
# Fixes "password authentication failed" after POSTGRES_PASSWORD in .env was changed
# for an already-initialised database volume: sets the DB user's password to the
# value in .env (no data is touched). Requires the db container to be running.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${1:-.env}"
get() { awk -F= -v k="$1" '$1==k{print substr($0, index($0,"=")+1); exit}' "$ENV_FILE"; }
PW="$(get POSTGRES_PASSWORD)"; USER_="$(get POSTGRES_USER)"; DB="$(get POSTGRES_DB)"
USER_="${USER_:-taskboard}"; DB="${DB:-taskboard}"
[ -n "$PW" ] || { echo "POSTGRES_PASSWORD is empty in $ENV_FILE" >&2; exit 1; }
docker compose up -d db >/dev/null
printf 'ALTER USER %s WITH PASSWORD :%s;\n' "\"$USER_\"" "'pw'" \
  | docker compose exec -T db psql -U "$USER_" -d "$DB" -v ON_ERROR_STOP=1 -v pw="$PW"
echo "Database password updated. Now run: docker compose up -d"
