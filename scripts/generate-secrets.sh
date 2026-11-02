#!/usr/bin/env bash
# Generates strong random secrets in .env (creating it from .env.example if needed).
# Only placeholder values are replaced, so it is safe to re-run.
# Usage: ./scripts/generate-secrets.sh [path-to-env-file]
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${1:-.env}"
[ -f "$ENV_FILE" ] || cp .env.example "$ENV_FILE"

rand() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-"$1"
  else
    # Fallback that needs only Docker.
    docker run --rm python:3.13-slim python -c "import secrets;print(secrets.token_urlsafe(64)[:$1])"
  fi
}

set_if_placeholder() {
  local key="$1" len="$2" current
  current="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  case "$current" in
    ""|change-me|changeme|replace-with-secure-random-value)
      local value; value="$(rand "$len")"
      if grep -qE "^${key}=" "$ENV_FILE"; then
        # portable in-place edit (GNU and BSD sed)
        sed -i.bak -E "s|^${key}=.*|${key}=${value}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
      else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
      fi
      echo "Generated ${key}"
      ;;
    *) echo "Kept existing ${key}" ;;
  esac
}

set_if_placeholder POSTGRES_PASSWORD 40
set_if_placeholder JWT_SECRET 64
chmod 600 "$ENV_FILE"
echo "Secrets written to ${ENV_FILE} (mode 600)."
