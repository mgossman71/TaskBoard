# Test Results

All numbers below come from runs executed on **2026-11-02**. Raw output:
`tests/results/run-all-2026-11-02.log`, `tests/results/load-2026-11-02.log`,
`tests/deploy/last-run.log`.

**Environment:** macOS 26 (Darwin 25.6, Apple Silicon Mac mini, 12 CPUs), Docker Desktop 29.8.0,
Docker Compose v5.5.1, Docker VM 8 GB RAM. Every suite runs inside containers against isolated
compose projects with throwaway volumes.

## Summary — `./scripts/run-all-tests.sh` (exit 0)

| Suite | Command | Result |
|---|---|---|
| Backend (pytest, real PostgreSQL 18 + Redis + live uvicorn) | `./scripts/test-backend.sh` | **128 passed, 0 failed** (15.4 s) |
| Frontend (tsc typecheck + Vitest) | `./scripts/test-frontend.sh` | **29 passed, 0 failed** (6 files) |
| End-to-end (Playwright/Chromium, full stack + Mailpit) | `./scripts/test-e2e.sh` | **7 passed, 0 failed** (11.4 s) |
| Deployment check (build → health → persistence) | `./scripts/deploy-check.sh` | **25 passed, 0 failed** |
| Load test (k6) | `./scripts/load-test.sh` | thresholds passed; details below |

No tests are skipped or marked xfail.

## Backend coverage by area (128 cases, 91 % line coverage with greenlet-aware `coverage`)

| File | What it proves |
|---|---|
| `unit/test_dag.py` (12 funcs, 2 Hypothesis property tests × 200 examples) | cycle detection incl. long cycles/self/diamond, deterministic topological order, blocked/ready, cycle check ⇔ toposort agreement on random DAGs, 10k nodes / 30k edges under 2 s |
| `unit/test_positions_and_config.py` | fractional positions, production refuses placeholder/short secrets, Argon2id hashes, filename sanitisation |
| `integration/test_auth.py` | register/login/me, case-insensitive uniqueness, 7 invalid-input cases, identical errors for unknown user vs wrong password, forged/`alg=none`/expired JWTs rejected, **refresh rotation + replay ⇒ whole session revoked**, CSRF header/origin enforcement, logout immediate revocation, sessions list/revoke/logout-all, **brute-force lockout (correct password refused while locked)**, IP rate limit, password reset (single use, no enumeration, revokes sessions), change password revokes other sessions |
| `integration/test_orgs_rbac.py` | invitations (email binding, single use, revocation), full role matrix, members/viewers only see assigned projects, owner-only rules, last-owner protection, atomic member removal (assignments + project memberships), archived = read-only |
| `integration/test_isolation.py` | user of org B gets **404 on 19 read endpoints and 25 write endpoints** of org A with no secret strings in responses; cannot link A's columns/labels/users/tasks into B; search never returns foreign tasks |
| `integration/test_tasks.py` | CRUD, numbering never reused, 11 boundary/injection inputs, control-char stripping, malformed ids/bodies/cursors, moves + completion timestamps, 60 inserts at one spot (rebalance), WIP limits, column CRUD/reorder/delete-with-move, labels/assignees, comments permissions, full-text + substring + key search, filters, **keyset pagination without gaps/duplicates**, **constant query count (no N+1)**, compact board cards |
| `integration/test_concurrency.py` | **5 concurrent writers forced past the version check: exactly one 200, four 409 with current state, one history entry**; stale writes rejected without data loss; move vs edit race; 20 concurrent creates get unique numbers; **concurrent A→B / B→A dependency creation cannot form a cycle**; concurrent project edits |
| `integration/test_transactions.py` | project delete removes tasks/deps/comments/attachments/activity and files, keeps org-level audit; **injected crash after DELETE ⇒ full rollback, files untouched**; task delete keeps history; failed task update leaves no partial assignee changes; org delete cascades |
| `integration/test_dependencies.py` | add/remove, blocked ⇄ unblocked on completion, readable cycle path, cross-project rejection, topological order with priority tie-break, ready/blocked lists and filters, **3,000 tasks / 5,988 edges: graph 28 ms, cycle check 17 ms** |
| `integration/test_attachments.py` | upload/download/delete, sandboxed download headers, viewer restrictions, 11 type-validation cases (SVG/HTML/disguised/mismatched/binary rejected), size limit 413, path traversal in filenames |
| `integration/test_realtime.py` (live server) | auth timeout 4408, bad token 4401, cross-site Origin rejected, unauthorized subscriptions denied, **two sessions receive create/move/assign/comment/update events**, **replay of missed events on reconnect**, resync when the gap is too large, presence join/viewing/leave, logout closes sockets, access removal unsubscribes live, reauth must match connection, malformed messages |
| `integration/test_dashboard_activity.py` | totals/overdue/due-today/by-status/per-project completion/workload/trend values match the seeded records; visibility rules apply to dashboards; task history with field-level diffs; activity pagination |
| `integration/test_migrations.py` | fresh install, idempotent re-run, `alembic check` (no model drift), downgrade/upgrade; **4 concurrent migration runners ⇒ exactly one applies, all exit 0** |
| `integration/test_health.py` | liveness/readiness (DB, Redis, schema version), JSON 404 with request id |

## Frontend (Vitest, 29)

`board.test.ts` (grouping, stale-snapshot rejection, blocked recomputation, drop positions),
`api.test.ts` (bearer header, **single refresh for concurrent 401s**, session-expiry signal,
structured/conflict/field errors, network errors), `realtime.test.ts` (first-message auth,
subscribe with replay cursor, de-duplication, backoff reconnect resuming from last id,
presence/resync/revocation, heartbeat, reauth on token rotation), `queries.test.tsx`
(**optimistic move rolled back on server rejection**, snapshot applied on success, edit rolled
back on 409, realtime events applied to cache), `validation.test.ts`, `components.test.tsx`
(accessible validation errors, password policy, task card states, user content is escaped).

## End-to-end (Playwright, 7)

1. **Scenario 1** — register, log out/in, create org, project, task; real pointer drag to
   "In Progress" (server confirms 200), reload ⇒ persisted; move via Status select to Done,
   reload ⇒ persisted; deep-link refresh works.
2. **Scenario 2** — two users; invite via UI link; accept; add to project; assign; second
   session sees the assignment, presence shows both users; edits/new tasks/comments propagate
   live without reload; **conflict**: a tab with realtime cut keeps a stale copy, Alice saves,
   Bob's save gets **409**, conflict banner shows Alice's value, Bob overwrites deliberately ⇒
   200 and Alice sees it live.
3. **Reconnect** — socket cut by a proxy, status shows "Reconnecting…", a task created meanwhile
   is absent, link restored ⇒ "Live" and the missed task appears via replay (no reload).
4. **Scenario 3** — two orgs; 18 cross-org API attempts (reads and writes) all **404** with no
   secret strings in bodies; unauthenticated 401; data unchanged; UI shows "Not found".
5. Viewer is read-only in UI and API.
6. Password reset end-to-end through **real SMTP delivery to Mailpit**.
7. UI smoke: dashboard charts, list filtering, task dialog, dark theme, mobile layout and
   navigation drawer, theme persistence — **zero console/page errors**.

## Deployment check (`scripts/deploy-check.sh`, 25/25)

Images build; db/redis/api/web healthy; migrate exited 0; DB/Redis/API not published on the
host; `/healthz`, liveness, readiness (`schema_version 0001`), `alembic_version` at head; SPA
index, immutable hashed assets, deep-link fallback, CSP header; register/org/project/tasks/
dependency/comment/attachment created via nginx; **WebSocket auth + subscribe through nginx**;
`docker compose down` → `docker compose up -d --build` → all healthy again; **login works, task,
comment, dependency, activity and the attachment (byte-identical) all survived**; migrations
re-ran idempotently.

### Clean-clone acceptance (manual run of the README procedure)

From a fresh `git clone` into an empty directory: `cp .env.example .env`,
`./scripts/generate-secrets.sh`, `docker compose up -d --build` → db, redis, api healthy, web
healthy; registered, created org/project/task via the public port; `docker compose down` +
`docker compose up -d --build` → the project and task were still present. (APP_PORT was set to
18200 only because port 8080 is used by another container on this machine.)
Negative checks: with placeholder secrets the stack refuses to start
(`ForgeBoard configuration error: Insecure production configuration: …`); without `.env`,
compose stops with `POSTGRES_PASSWORD must be set - run ./scripts/generate-secrets.sh`.

### Other verified properties

- `linux/amd64` builds of both images succeed (`docker buildx --platform linux/amd64`); the API
  image imports all native deps on x86-64 (`amd64 import OK x86_64`).
- Graceful shutdown: `docker compose stop api` ⇒ `shutdown_complete` logged by every worker.
- Containers: api runs as `app` (uid 10001), web as `nginx` (101), redis as 999; read-only root
  filesystems; `cap_drop: [ALL]`; `json-file` logs with `max-size 10m / max-file 5`.
- API JSON responses are gzip-compressed by nginx.

## Load test (`scripts/load-test.sh`)

Setup: fresh stack, `WEB_CONCURRENCY=4`, seeded **1 org, 100 users, 5 projects, 10,000 tasks**
(+ ~4,000 dependencies, assignees). k6 1.3.0: **100 API virtual users** (paginated lists,
org-wide search with filters, task edits with optimistic locking, moves, dashboard every 5th
iteration, full board + dependency graph every 10th) **plus 100 concurrent WebSocket clients**
subscribed to the projects, for 2 minutes. k6 ran on the same machine as the stack.

| Metric (run 2, after the compact-board change) | avg | median | p95 | p99 |
|---|---|---|---|---|
| All API requests (38,259, **0.00 % failed**, ~304 req/s) | 40 ms | 14 ms | **143 ms** | 358 ms |
| List tasks (keyset page of 50) | 27 ms | 9 ms | 110 ms | 254 ms |
| Search + filter (org-wide, with total) | 33 ms | 20 ms | 112 ms | 237 ms |
| Update task (200 or 409) | 30 ms | 11 ms | 124 ms | 275 ms |
| Move task | 31 ms | 12 ms | 126 ms | 289 ms |
| Dashboard | 86 ms | 34 ms | 398 ms | 693 ms |
| Dependency graph (2,000-task project) | 123 ms | 35 ms | 519 ms | 1.51 s |
| Full board (2,000-task project) | 368 ms | 133 ms | **2.39 s** | 2.88 s |
| WebSocket connect | 32 ms | 24 ms | 79 ms | 93 ms |

WebSocket clients received **234,495 events** (~1,860/s) with all 200 sessions completing.
All checks succeeded (logins, lists, search, updates 200/409, dashboard, board, graph, WS 101).

Run 1 (before removing descriptions from board payloads) for comparison: overall p95 146 ms,
board p95 3.86 s.

**Interpretation:** the target of 100 concurrent active users on an org with 10,000 tasks is met
on this hardware for all interactive operations (p95 well under 200 ms, zero errors). Loading
the *entire* board of a 2,000-task project is the slow outlier (see KNOWN_ISSUES #4).
