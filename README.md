# TaskBoard

A self-hosted, multi-tenant project management platform with Kanban boards, task dependencies,
dashboards and real-time collaboration. One command deploys it with Docker Compose.

**Stack:** React 19 + TypeScript + Vite · FastAPI (Python 3.13) · SQLAlchemy 2 + Alembic ·
PostgreSQL 18 · Redis 7.4 · WebSockets · nginx · Docker Compose.
Tests: Pytest · Vitest · Playwright · k6.

## Features

- **Organizations and roles:** Owner, Admin, Member and Viewer roles, email invitations, strict
  per-organization data isolation (enforced server-side).
- **Kanban boards:** customizable columns (rename, reorder, WIP limits, "done" flag) and drag &
  drop with optimistic updates.
- **Pull-based workflow:** new tasks always enter the first column ("To Do") and are moved
  across the board as work progresses. The API enforces this too.
- **Tasks:** priorities, due dates, labels, multiple assignees, comments, attachments, full
  modification history.
- **Dependencies:** cycle prevention with a readable explanation, blocked / ready lists, and a
  valid execution order (topological sort).
- **Real-time:** live updates across sessions, presence ("who's here / viewing this task"),
  automatic reconnection with replay of missed updates.
- **Safe concurrent editing:** if two people edit the same task, one save wins and the other
  sees a conflict with the latest version. Changes are never silently overwritten.
- **Dashboards:** tasks by status, overdue counts, project completion, workload per person,
  created vs completed trend, activity timeline. All computed live from the database.
- **Search and lists:** full-text and key search (`WEB-42`), filters, sorting, cursor
  pagination.
- **Accounts:** Argon2id passwords, rotating refresh tokens with theft detection, session list
  and revocation, password reset, brute-force lockout.
- **UI:** light and dark themes, responsive/mobile layout, accessible forms and dialogs.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design, [TEST_RESULTS.md](TEST_RESULTS.md) for
measured results (including a 100-user load test) and [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for
limitations.

---

## Deploy (clean Ubuntu 24.04 with Docker Engine + Compose plugin)

```bash
git clone https://github.com/mgossman71/TaskBoard.git
cd TaskBoard
./scripts/setup.sh
```

`setup.sh` creates `.env`, generates secrets, keeps port 8080 if it is free (otherwise
picks the next free port), sets `PUBLIC_BASE_URL` to this host's IP, then runs
`docker compose up -d --build` and prints the URL to open. Re-running it is safe; use it after
`git pull` to upgrade. `./scripts/setup.sh --no-start` only writes the configuration.

Manual alternative (the classic steps):

```bash
cp .env.example .env
./scripts/generate-secrets.sh        # replaces placeholder POSTGRES_PASSWORD and JWT_SECRET
docker compose up -d --build
docker compose ps                     # db, redis, api, web -> healthy; migrate -> exited (0)
```

Open the printed URL (default **http://<server>:8080**). Any address that reaches the
server works (IP or hostname); `PUBLIC_BASE_URL` is only used for links in emails. Click *Create an account*,
create an organization, a project, and tasks.

Nothing else is required on the host: images are built from source, migrations run
automatically, and the API waits for the database. The API **refuses to start in production**
while `.env` still contains placeholder secrets — it exits with
`TaskBoard configuration error: … Run ./scripts/generate-secrets.sh`.

> `generate-secrets.sh` uses `openssl` if present, otherwise a throwaway `python` container.
> Edit `.env` before the first start if you need a different port or public URL.

### Updating / restarting

```bash
git pull
./scripts/setup.sh               # or: docker compose up -d --build (data is kept in named volumes)
```

`docker compose down -v` **deletes all data** (volumes) — only use it to reset an installation.

### Behind HTTPS (TLS terminated by an external reverse proxy)

Point your proxy (Caddy, Traefik, nginx, a load balancer) at `APP_PORT`, forward WebSocket
upgrades for `/api/v1/ws`, and set in `.env`:

```env
PUBLIC_BASE_URL=https://board.example.com   # cookies become Secure automatically for https
HSTS_ENABLED=true                           # send Strict-Transport-Security
TRUSTED_PROXY_CIDRS=10.0.0.5/32        # address(es) of your proxy, so client IPs are preserved
APP_BIND_ADDRESS=127.0.0.1             # if the proxy runs on the same host
```

### Email

`EMAIL_BACKEND=console` (default) writes password-reset and invitation emails to the API log
(`docker compose logs api | grep email_console_delivery`); invitation links are also shown in
the UI. For real delivery set `EMAIL_BACKEND=smtp` and the `SMTP_*` variables.

### Backups

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > taskboard.dump
docker run --rm -v taskboard_attachments:/data -v "$PWD":/backup alpine tar czf /backup/attachments.tgz -C /data .
# restore: pg_restore --clean --if-exists -U taskboard -d taskboard < taskboard.dump (inside the db container)
```

### Logs and health

```bash
docker compose logs -f api            # structured JSON, one line per request (with request_id)
curl http://localhost:8080/api/health/ready   # {"status":"ok","checks":{"database":"ok","schema_version":"0001","redis":"ok"}}
```

---

## Configuration

Every variable is listed (with comments) in [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `TaskBoard` | Name used in emails |
| `APP_ENV` | `production` | `production` enforces strong secrets and hides `/api/docs` |
| `APP_PORT` / `APP_BIND_ADDRESS` | `8080` / `0.0.0.0` | Published host port / interface of the web container |
| `PUBLIC_BASE_URL` | `http://localhost:8080` (setup.sh: host IP) | External URL used in emailed links. Browsers may use any address that reaches the server (same-origin requests are always allowed) |
| `ALLOWED_ORIGINS` | *(empty)* | Extra comma-separated origins for WebSocket/cookie endpoints |
| `LOG_LEVEL` | `INFO` | API log level |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `taskboard` / `taskboard` / **required** | Database credentials (password must not be a placeholder) |
| `POSTGRES_MAX_CONNECTIONS` / `POSTGRES_SHARED_BUFFERS` | `200` / `256MB` | PostgreSQL tuning |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | SQLAlchemy pool per API worker |
| `WEB_CONCURRENCY` | `2` | uvicorn worker processes |
| `JWT_SECRET` | **required** (≥32 chars) | HMAC key for access tokens |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `14` | Session (refresh family) lifetime |
| `PASSWORD_RESET_EXPIRE_MINUTES` / `INVITATION_EXPIRE_DAYS` | `60` / `7` | Token lifetimes |
| `COOKIE_SECURE` | *(empty = automatic)* | Secure cookies; automatic = `true` when `PUBLIC_BASE_URL` is `https://` |
| `HSTS_ENABLED` | `false` | Send `Strict-Transport-Security` (only when served over HTTPS) |
| `API_TRUSTED_FORWARDERS` | *(empty = Docker private ranges)* | CIDRs the API accepts `X-Forwarded-For` from (nginx on the internal network); loopback and public addresses are never trusted by default |
| `LOGIN_MAX_FAILURES` / `LOGIN_FAILURE_WINDOW_SECONDS` / `LOGIN_LOCKOUT_SECONDS` | `5` / `900` / `900` | Brute-force lockout |
| `IP_AUTH_RATE_PER_MINUTE` / `REGISTER_RATE_PER_MINUTE` / `PASSWORD_RESET_RATE_PER_MINUTE` | `30` / `10` / `5` | Per-IP API rate limits |
| `NGINX_API_RATE` / `NGINX_AUTH_RATE` | `50r/s` / `10r/s` | nginx per-IP request rates |
| `TRUSTED_PROXY_CIDRS` | `127.0.0.1/32` | Proxies whose `X-Forwarded-For` is trusted |
| `MAX_UPLOAD_MB` | `10` | Attachment size limit (nginx + API) |
| `EMAIL_BACKEND` | `console` | `console` or `smtp` |
| `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_USE_TLS` | | SMTP delivery |

Generate secrets manually if you prefer: `openssl rand -base64 48`.

---

## Running the tests

All suites run in containers with isolated compose projects and throwaway volumes — they never
touch your deployment's data. Host requirements: Docker, bash, curl.

```bash
./scripts/run-all-tests.sh            # backend + frontend + e2e + deployment check (summary at the end)
./scripts/test-backend.sh             # pytest: unit + integration on real PostgreSQL/Redis (+ live WebSocket server)
./scripts/test-backend.sh -k realtime # any pytest args
./scripts/test-frontend.sh            # TypeScript typecheck + Vitest
./scripts/test-e2e.sh                 # Playwright against a full fresh stack (+ Mailpit for SMTP)
./scripts/deploy-check.sh             # build, health, migrations, assets, WS via nginx, down/up persistence
./scripts/load-test.sh                # seeds 100 users / 10,000 tasks, runs k6 (100 API VUs + 100 WS clients)
VUS=50 DURATION=1m ./scripts/load-test.sh
```

Last full run: backend 151 passed · frontend 29 passed · end-to-end 7 passed · deployment
check 33 passed · load test thresholds met. Details in [TEST_RESULTS.md](TEST_RESULTS.md).

## Development notes

- Backend lint: `docker run --rm -v "$PWD/backend":/app -w /app taskboard-test-api-test ruff check taskboard`
- New migration: change models, then
  `docker compose run --rm migrate alembic revision --autogenerate -m "describe change"` and
  review the file in `backend/alembic/versions/`. CI-style drift check: `test_migrations.py`
  runs `alembic check`.
- API docs (Swagger) are served at `/api/docs` when `APP_ENV=development`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Bind for 0.0.0.0:8080 failed: port is already allocated` | Run `./scripts/setup.sh` (picks a free port), or set `APP_PORT` in `.env` yourself |
| `service "migrate" didn't complete successfully` | `docker compose logs migrate` — usually placeholder secrets or DB credentials changed after first init |
| `password authentication failed` / changed `POSTGRES_PASSWORD` after first start (e.g. re-ran `cp .env.example .env`) | PostgreSQL keeps the original password in the volume; run `./scripts/sync-db-password.sh` (sets the DB password to the one in `.env`, keeps data) |
| Can't log in through an HTTPS proxy | Set `PUBLIC_BASE_URL=https://…` (cookies then become Secure automatically) |
| `Pool overlaps with other one on this address space` | An older checkout pinned a fixed subnet; `git pull` (subnets are now assigned automatically), then `docker compose up -d --build` |
| `network taskboard_backend … needs to be recreated` after upgrading | `docker compose down` (keeps data) then `docker compose up -d --build` |
| WebSocket status shows "Reconnecting…" behind a proxy | Ensure the proxy forwards `Upgrade`/`Connection` headers for `/api/v1/ws` and the origin matches `PUBLIC_BASE_URL` |

## License

[MIT](LICENSE) © 2026 Mark Gossman
