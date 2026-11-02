# CHECKPOINT

_Last updated: 2026-11-02 — all milestones complete; final regression run green._

## Completed functionality
Everything in IMPLEMENTATION_PLAN.md (milestones 1–16): Docker Compose deployment (web/api/
migrate/db/redis), auth (Argon2id, rotating refresh with replay detection, sessions, reset,
lockout, CSRF), orgs/invitations/RBAC/isolation, projects/columns/labels/members, tasks
(OCC, moves, search, keyset pagination), comments, attachments, DAG dependency engine, activity
history, realtime (fan-out, replay, presence, revocation), dashboard, complete React frontend,
test suites, load test, documentation.

## Test status (last run 2026-11-02, see TEST_RESULTS.md)
- Backend 141/141 · Frontend 29/29 · E2E 7/7 · Deploy check 31/31 · Load test thresholds met.
- Failing tests: none. Blockers: none.

## Important decisions
See ARCHITECTURE.md §13. Notably: one board per project; Redis for fan-out; separate migrate
job + advisory lock; access token in memory + HttpOnly refresh cookie; production refuses
placeholder secrets; `EMAIL_BACKEND=console` default; board uses compact card schema.

## Key files
- Deployment: `compose.yaml`, `.env.example`, `backend/Dockerfile`, `frontend/Dockerfile`,
  `frontend/nginx/*`, `scripts/generate-secrets.sh`
- Backend core: `backend/taskboard/{authz.py,services/,realtime/,domain/dag.py}`
- Migration: `backend/alembic/versions/20261102_0001_initial_schema.py`
- Frontend core: `frontend/src/lib/{api.ts,realtime.ts,queries.ts,board.ts}`,
  `frontend/src/pages/project/{BoardPage,TaskDialog}.tsx`
- Tests: `backend/tests/`, `frontend/src/**/*.test.ts(x)`, `tests/e2e/specs/`, `tests/load/k6.js`,
  `scripts/deploy-check.sh`

## Resume / verify
```bash
cd taskboard
cp .env.example .env && ./scripts/generate-secrets.sh   # first time only
docker compose up -d --build
./scripts/run-all-tests.sh            # add --with-load for the k6 run
```
Local note: on the development machine port 8080 is occupied by an unrelated container, so the
local `.env` uses `APP_PORT=8088`.

## Next steps (optional improvements)
See KNOWN_ISSUES.md — first candidate: per-column pagination for very large boards; then
running the acceptance procedure on a physical Ubuntu 24.04/amd64 host.
