from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from taskboard.cache import get_redis
from taskboard.db import get_engine
from taskboard.realtime.hub import hub

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def liveness() -> dict:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok"}


@router.get("/api/health/ready")
async def readiness() -> JSONResponse:
    """Readiness: dependencies reachable and schema migrated."""
    checks: dict[str, str] = {}
    ok = True
    try:
        async with get_engine().connect() as conn:
            version = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        checks["database"] = "ok"
        checks["schema_version"] = version or "missing"
        if not version:
            ok = False
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        ok = False
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
        ok = False
    body = {"status": "ok" if ok else "unavailable", "checks": checks, "realtime": hub.stats()}
    return JSONResponse(body, status_code=200 if ok else 503)
