# CHECKPOINT

_Last updated: 2026-11-02 — Milestones 1–2 complete, backend services implemented (untested)._

## State
- Repo: `forgeboard/` (git, local only). Stack boots with `docker compose up -d --build`; all services healthy.
- Backend (FastAPI) implements auth, orgs/invitations/RBAC, projects/columns/labels, tasks (OCC, moves,
  search/keyset pagination), comments, attachments, dependencies (DAG), activity, dashboard, WebSocket hub.
- Initial Alembic migration `0001` generated + verified (upgrade → `alembic check` → downgrade → upgrade).
- Frontend: only scaffold/placeholder page.

## Next steps
1. Backend test suite (`backend/tests`, `compose.test.yaml`, `scripts/test-backend.sh`).
2. Frontend implementation.
3. E2E, deploy-check, load test, docs.

## Resume
```bash
cd forgeboard
docker compose up -d --build          # local dev here uses APP_PORT=8088 (8080 busy on this host)
```
