# ForgeBoard

A multi-tenant project management platform: organizations, role-based access, projects with
customizable Kanban boards, tasks with priorities/due dates/labels/assignees, comments,
attachments, a task dependency engine (cycle prevention, blocked/ready, topological order),
activity history, dashboards, and real-time collaboration (live updates, presence,
reconnect-and-replay).

**Stack:** React 19 + TypeScript + Vite · FastAPI (Python 3.13) · SQLAlchemy 2 + Alembic ·
PostgreSQL 18 · Redis 7.4 · WebSockets · nginx · Docker Compose.
Tests: Pytest · Vitest · Playwright · k6.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design, [TEST_RESULTS.md](TEST_RESULTS.md) for
measured results and [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for limitations.

---

## Deploy (clean Ubuntu 24.04 with Docker Engine + Compose plugin)

```bash
git clone <repository-url>
cd forgeboard
cp .env.example .env
./scripts/generate-secrets.sh        # replaces placeholder POSTGRES_PASSWORD and JWT_SECRET
docker compose up -d --build
docker compose ps                     # db, redis, api, web -> healthy; migrate -> exited (0)
```

Open **http://localhost:8080** (or `http://<server>:${APP_PORT}`), click *Create an account*,
create an organization, a project, and tasks.

Nothing else is required on the host: images are built from source, migrations run
automatically, and the API waits for the database. The API **refuses to start in production**
while `.env` still contains placeholder secrets — it exits with
`ForgeBoard configuration error: … Run ./scripts/generate-secrets.sh`.

> `generate-secrets.sh` uses `openssl` if present, otherwise a throwaway `python` container.
> Edit `.env` before the first start if you need a different port or public URL.

### Updating / restarting

```bash
docker compose down              # data is kept in named volumes (pgdata, attachments)
docker compose up -d --build     # rebuilds images; pending migrations apply automatically
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
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > forgeboard.dump
docker run --rm -v forgeboard_attachments:/data -v "$PWD":/backup alpine tar czf /backup/attachments.tgz -C /data .
# restore: pg_restore --clean --if-exists -U forgeboard -d forgeboard < forgeboard.dump (inside the db container)
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
| `APP_NAME` | `ForgeBoard` | Name used in emails |
| `APP_ENV` | `production` | `production` enforces strong secrets and hides `/api/docs` |
| `APP_PORT` / `APP_BIND_ADDRESS` | `8080` / `0.0.0.0` | Published host port / interface of the web container |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | External URL: emailed links and the allowed browser `Origin` |
| `ALLOWED_ORIGINS` | *(empty)* | Extra comma-separated origins for WebSocket/cookie endpoints |
| `LOG_LEVEL` | `INFO` | API log level |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `forgeboard` / `forgeboard` / **required** | Database credentials (password must not be a placeholder) |
| `POSTGRES_MAX_CONNECTIONS` / `POSTGRES_SHARED_BUFFERS` | `200` / `256MB` | PostgreSQL tuning |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | SQLAlchemy pool per API worker |
| `WEB_CONCURRENCY` | `2` | uvicorn worker processes |
| `JWT_SECRET` | **required** (≥32 chars) | HMAC key for access tokens |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `14` | Session (refresh family) lifetime |
| `PASSWORD_RESET_EXPIRE_MINUTES` / `INVITATION_EXPIRE_DAYS` | `60` / `7` | Token lifetimes |
| `COOKIE_SECURE` | *(empty = automatic)* | Secure cookies; automatic = `true` when `PUBLIC_BASE_URL` is `https://` |
| `HSTS_ENABLED` | `false` | Send `Strict-Transport-Security` (only when served over HTTPS) |
| `BACKEND_SUBNET` | `172.30.250.0/24` | Pinned subnet of the internal network; the API trusts `X-Forwarded-For` only from it. Change on collision; use a distinct subnet per installation on one host |
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

Results of the last full run are recorded in [TEST_RESULTS.md](TEST_RESULTS.md).

## Development notes

- Backend lint: `docker run --rm -v "$PWD/backend":/app -w /app forgeboard-test-api-test ruff check forgeboard`
- New migration: change models, then
  `docker compose run --rm migrate alembic revision --autogenerate -m "describe change"` and
  review the file in `backend/alembic/versions/`. CI-style drift check: `test_migrations.py`
  runs `alembic check`.
- API docs (Swagger) are served at `/api/docs` when `APP_ENV=development`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Bind for 0.0.0.0:8080 failed: port is already allocated` | Set `APP_PORT` in `.env` to a free port (and `PUBLIC_BASE_URL` accordingly) |
| `service "migrate" didn't complete successfully` | `docker compose logs migrate` — usually placeholder secrets or DB credentials changed after first init |
| `password authentication failed` / changed `POSTGRES_PASSWORD` after first start (e.g. re-ran `cp .env.example .env`) | PostgreSQL keeps the original password in the volume; run `./scripts/sync-db-password.sh` (sets the DB password to the one in `.env`, keeps data) |
| Can't log in through an HTTPS proxy | Set `PUBLIC_BASE_URL=https://…` (cookies then become Secure automatically) |
| `Pool overlaps with other one on this address space` / `invalid pool request` | `BACKEND_SUBNET` collides with an existing Docker or host network; pick another private /24 in `.env` |
| `network forgeboard_backend … needs to be recreated` after upgrading | `docker compose down` (keeps data) then `docker compose up -d --build` |
| WebSocket status shows "Reconnecting…" behind a proxy | Ensure the proxy forwards `Upgrade`/`Connection` headers for `/api/v1/ws` and the origin matches `PUBLIC_BASE_URL` |
