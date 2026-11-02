# Implementation Plan & Progress

Status legend: ✅ done and verified by automated tests · 🟡 done, partially verified · ⬜ not done

| # | Milestone | Status | Verification |
|---|---|---|---|
| 1 | Workspace inspection, architecture, compose design, repo skeleton | ✅ | `docker compose up -d --build` → all healthy |
| 2 | Infrastructure: compose, multi-stage Dockerfiles, nginx (SPA + API + WS proxy), health checks, auto-migrations with advisory lock | ✅ | `deploy-check.sh` (25 checks), `test_migrations.py` |
| 3 | Data model + initial migration (`0001`), drift check | ✅ | upgrade → `alembic check` → downgrade → upgrade; 4 concurrent runners |
| 4 | Authentication: register/login, Argon2id, JWT + rotating refresh, replay detection, sessions, logout(-all), password reset, change password, brute-force protection, CSRF | ✅ | `test_auth.py` (14 test functions / 20 cases), E2E password-reset via SMTP/Mailpit |
| 5 | Organizations, invitations, RBAC, tenant isolation | ✅ | `test_orgs_rbac.py`, `test_isolation.py` (every endpoint), E2E scenario 3 |
| 6 | Projects, customizable columns, labels, project members, archive/delete | ✅ | `test_tasks.py`, `test_orgs_rbac.py`, `test_transactions.py` |
| 7 | Tasks: CRUD, moves/ordering, WIP limits, assignees, labels, comments, attachments, search/filter/sort/keyset pagination | ✅ | `test_tasks.py`, `test_attachments.py`, N+1 query-count test |
| 8 | Optimistic concurrency + transactional integrity + retention policy | ✅ | `test_concurrency.py` (forced interleavings), `test_transactions.py` (failure injection) |
| 9 | Dependency engine (DAG): cycle prevention, blocked/ready, topological order, scale | ✅ | `unit/test_dag.py` (property tests, 10k nodes), `test_dependencies.py` (3k-task graph) |
| 10 | Activity history + task modification history | ✅ | `test_dashboard_activity.py`, history assertions in several suites |
| 11 | Realtime: Redis fan-out, authorized subscriptions, replay/resync, presence, revocation | ✅ | `test_realtime.py` (live uvicorn), E2E sync + reconnect tests, `deploy-check` WS via nginx |
| 12 | Dashboard/reporting from live data | ✅ | `test_dashboard_activity.py`, E2E UI smoke |
| 13 | Frontend: auth screens, shell/nav, orgs, projects, Kanban (dnd-kit), task dialog, list view, dependencies, activity, settings, dashboard (Recharts), account/sessions, themes, toasts, confirmations, optimistic updates w/ rollback, conflict UI, mobile layout | ✅ | Vitest (29), Playwright (7) incl. screenshots in light/dark/mobile |
| 14 | E2E scenarios 1–3 (+ reconnect, viewer, password reset, UI smoke) | ✅ | `tests/e2e/specs/*` |
| 15 | Load testing procedure + measurements | ✅ | `scripts/load-test.sh`, results in TEST_RESULTS.md |
| 16 | Clean-clone deployment, amd64 build, docs, final report | ✅ | fresh `git clone` acceptance run; `buildx --platform linux/amd64` |

## Design notes kept from planning

- One Kanban board per project (customizable columns) — see ARCHITECTURE.md §13.
- Web service is named `web` (nginx serving the SPA and acting as reverse proxy).
- Load-test fixture data is created only by the explicit `taskboard.cli seed-load` command; the
  application never seeds demo data.

## Possible next steps (not required by the brief)

- Per-column pagination / virtualization for boards with thousands of cards (see KNOWN_ISSUES).
- Email verification on sign-up; Markdown + @mentions in comments; notification inbox.
- Object storage (S3-compatible) backend for attachments when running multiple hosts.
- CI pipeline wiring the `scripts/*` suites.
