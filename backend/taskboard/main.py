"""TaskBoard API application factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from taskboard.api.v1 import auth, health, orgs, projects, tasks
from taskboard.cache import close_redis
from taskboard.config import get_settings
from taskboard.db import dispose_engine, get_engine, get_sessionmaker
from taskboard.errors import AppError
from taskboard.logging import configure_logging, get_logger
from taskboard.realtime import ws
from taskboard.realtime.hub import hub

log = get_logger("taskboard")

JSON_BODY_LIMIT = 1024 * 1024  # non-multipart requests (JSON) are small by design


class BodySizeLimitMiddleware:
    """Defense in depth (nginx also limits bodies): reject oversized request bodies even
    if the API is reached directly. Checks Content-Length up front and counts streamed
    (chunked) bytes; once over the limit the app sees a disconnect and the client gets 413."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _limit(scope) -> int:
        headers = dict(scope.get("headers") or [])
        ctype = headers.get(b"content-type", b"").decode("latin-1").lower()
        if ctype.startswith("multipart/form-data"):
            return get_settings().max_upload_bytes + 1024 * 1024
        return JSON_BODY_LIMIT

    async def _reject(self, send) -> None:
        body = b'{"error":{"code":"payload_too_large","message":"Request body too large"}}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self._limit(scope)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    return await self._reject(send)
            except ValueError:
                return await self._reject(send)
        state = {"received": 0, "exceeded": False, "started": False}

        async def limited_receive():
            if state["exceeded"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > limit:
                    state["exceeded"] = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if state["exceeded"]:
                if message["type"] == "http.response.start" and not state["started"]:
                    state["started"] = True
                    await self._reject(send)
                return  # swallow whatever the app tried to send
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if state["exceeded"]:
                if not state["started"]:
                    await self._reject(send)
                return
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level, json=s.app_env != "development")
    get_engine()
    hub.start()
    if s.app_env == "production" and s.public_base_url.lower().startswith("https://") and not s.secure_cookies:
        log.warning(
            "cookie_secure_disabled",
            message="PUBLIC_BASE_URL is https but COOKIE_SECURE=false: session cookies may be sent over plain HTTP.",
        )
    if s.app_env == "production" and s.email_backend == "console":
        log.warning(
            "email_backend_console",
            message="EMAIL_BACKEND=console: password-reset and invitation emails are written to the log only. "
            "Configure SMTP_* for real delivery.",
        )
    try:
        from sqlalchemy import text

        from taskboard.services.attachments import sweep_orphans

        async with get_sessionmaker()() as session, session.begin():
            # Every uvicorn worker runs this lifespan; only the lock holder sweeps.
            got = await session.scalar(text("SELECT pg_try_advisory_xact_lock(0x54425357)"))  # "TBSW"
            removed = await sweep_orphans(session) if got else 0
        if removed:
            log.info("attachment_orphans_removed", count=removed)
    except Exception:
        log.exception("attachment_sweep_failed")
    log.info("startup_complete", env=s.app_env)
    yield
    log.info("shutdown_started")
    await hub.stop()
    await close_redis()
    await dispose_engine()
    log.info("shutdown_complete")


def _error(status: int, code: str, message: str, details=None, headers=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status, headers=headers)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=f"{s.app_name} API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if s.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if s.app_env != "production" else None,
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = []
        for e in exc.errors():
            details.append(
                {
                    "loc": [str(p) for p in e.get("loc", ())],
                    "msg": str(e.get("msg", "")).removeprefix("Value error, "),
                    "type": e.get("type"),
                }
            )
        return _error(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled_error", path=request.url.path)
        return _error(500, "internal_error", "An unexpected error occurred")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request_id = request_id[:64]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed", method=request.method, path=request.url.path)
            response = _error(500, "internal_error", "An unexpected error occurred")
        duration = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        if request.url.path not in ("/api/health", "/api/health/ready"):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round(duration, 1),
                client=request.client.host if request.client else None,
                user_id=getattr(request.state, "user_id", None),
            )
        return response

    app.add_middleware(BodySizeLimitMiddleware)  # outermost: enforced before any parsing
    app.include_router(health.router)
    for r in (auth.router, orgs.router, projects.router, tasks.router):
        app.include_router(r, prefix="/api/v1")
    app.include_router(ws.router)
    return app


app = create_app()
