"""WebSocket endpoint: authentication, authorized subscriptions, replay, presence."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from forgeboard.authz import load_project, require_org_role
from forgeboard.config import get_settings
from forgeboard.db import get_sessionmaker
from forgeboard.deps import authenticate_token
from forgeboard.errors import AppError
from forgeboard.logging import get_logger
from forgeboard.models import ActivityEvent
from forgeboard.realtime.hub import Connection, hub, presence_leave, presence_list, presence_touch
from forgeboard.security.csrf import origin_allowed
from forgeboard.security.tokens import decode_access_token
from forgeboard.services.activity import serialize
from forgeboard.services.serializers import user_brief

log = get_logger(__name__)
router = APIRouter()

IDLE_TIMEOUT = 75.0  # client pings every ~20s
MAX_SUBSCRIPTIONS = 50
MAX_MESSAGE_BYTES = 8192


async def _authorize_project(c: Connection, project_id: str) -> bool:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        return False
    async with get_sessionmaker()() as session:
        try:
            await load_project(session, c.user_id, pid)
            return True
        except AppError:
            return False


async def _authorize_org(c: Connection, org_id: str) -> bool:
    try:
        oid = uuid.UUID(org_id)
    except ValueError:
        return False
    async with get_sessionmaker()() as session:
        try:
            await require_org_role(session, oid, c.user_id)
            return True
        except AppError:
            return False


async def _revalidate(c: Connection) -> None:
    for pid in list(c.projects):
        if not await _authorize_project(c, pid):
            hub.unsubscribe(c, pid)
            c.send({"kind": "unsubscribed", "project_id": pid, "reason": "access_revoked"})
    for oid in list(c.orgs):
        if not await _authorize_org(c, oid):
            hub.unsubscribe_org(c, oid)
            c.send({"kind": "unsubscribed", "org_id": oid, "reason": "access_revoked"})


hub.revalidate = _revalidate


async def _replay(c: Connection, project_id: str, since: int) -> int:
    s = get_settings()
    async with get_sessionmaker()() as session:
        events = (
            await session.scalars(
                select(ActivityEvent)
                .options(selectinload(ActivityEvent.actor))
                .where(ActivityEvent.project_id == uuid.UUID(project_id), ActivityEvent.id > since)
                .order_by(ActivityEvent.id)
                .limit(s.ws_replay_limit + 1)
            )
        ).all()
        if len(events) > s.ws_replay_limit:
            c.send({"kind": "resync_required", "project_id": project_id})
            return 0
        for ev in events:
            c.send(serialize(ev, user_brief(ev.actor)))
        return len(events)


async def _handle(c: Connection, msg: dict) -> None:
    t = msg.get("type")
    if t == "ping":
        c.send({"kind": "pong", "ts": time.time()})
        for pid in list(c.projects):
            await presence_touch(c, pid, c.viewing.get(pid))
    elif t == "subscribe":
        pid = str(msg.get("project_id", ""))
        if len(c.projects) >= MAX_SUBSCRIPTIONS and pid not in c.projects:
            c.send({"kind": "error", "code": "too_many_subscriptions", "message": "Subscription limit reached"})
            return
        if not await _authorize_project(c, pid):
            # Same response for nonexistent and forbidden projects.
            c.send({"kind": "error", "code": "subscription_denied", "project_id": pid, "message": "Not allowed"})
            return
        hub.subscribe(c, pid)
        replayed = 0
        since = msg.get("since")
        if isinstance(since, int) and since >= 0:
            replayed = await _replay(c, pid, since)
        await presence_touch(c, pid, None, announce=True)
        c.send({"kind": "subscribed", "project_id": pid, "replayed": replayed, "presence": await presence_list(pid)})
    elif t == "unsubscribe":
        pid = str(msg.get("project_id", ""))
        if pid in c.projects:
            hub.unsubscribe(c, pid)
        c.send({"kind": "unsubscribed", "project_id": pid, "reason": "client"})
    elif t == "subscribe_org":
        oid = str(msg.get("org_id", ""))
        if not await _authorize_org(c, oid):
            c.send({"kind": "error", "code": "subscription_denied", "org_id": oid, "message": "Not allowed"})
            return
        hub.subscribe_org(c, oid)
        c.send({"kind": "subscribed_org", "org_id": oid})
    elif t == "presence":
        pid = str(msg.get("project_id", ""))
        if pid not in c.projects:
            return
        viewing = msg.get("viewing_task_id")
        viewing = str(viewing)[:64] if viewing else None
        c.viewing[pid] = viewing
        await presence_touch(c, pid, viewing, announce=True)
    elif t == "reauth":
        token = msg.get("token")
        try:
            claims = decode_access_token(str(token))
        except AppError:
            c.send({"kind": "error", "code": "unauthorized", "message": "Invalid token"})
            c.close(4401)
            return
        if claims.user_id != c.user_id or claims.session_id != c.session_id:
            c.send({"kind": "error", "code": "unauthorized", "message": "Token does not match connection"})
            c.close(4401)
            return
        async with get_sessionmaker()() as session:
            try:
                await authenticate_token(session, str(token))
            except AppError:
                c.close(4401)
                return
        c.token_expires_at = claims.expires_at.timestamp()
        c.send({"kind": "reauthed", "expires_at": c.token_expires_at})
    else:
        c.send({"kind": "error", "code": "bad_message", "message": "Unknown message type"})


async def _expiry_watchdog(c: Connection) -> None:
    while not c.closed:
        await asyncio.sleep(5)
        if time.time() > c.token_expires_at + 5:
            c.send({"kind": "error", "code": "token_expired", "message": "Access token expired"})
            c.close(4401)
            return


@router.websocket("/api/v1/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    s = get_settings()
    origin = ws.headers.get("origin")
    if origin is not None and not origin_allowed(origin):
        # Cross-site WebSocket hijacking protection.
        await ws.close(code=4403)
        return
    await ws.accept()
    # 1) authenticate with the first message (keeps tokens out of URLs/logs)
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=s.ws_auth_timeout_seconds)
        first = json.loads(raw)
        if first.get("type") != "auth" or not isinstance(first.get("token"), str):
            raise ValueError
        async with get_sessionmaker()() as session:
            ctx = await authenticate_token(session, first["token"])
        claims = decode_access_token(first["token"])
    except TimeoutError:
        await ws.close(code=4408)
        return
    except (ValueError, AppError, WebSocketDisconnect, json.JSONDecodeError):
        with contextlib.suppress(Exception):
            await ws.send_text(
                json.dumps({"kind": "error", "code": "unauthorized", "message": "Authentication failed"})
            )
            await ws.close(code=4401)
        return

    c = Connection(
        ws=ws,
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        token_expires_at=claims.expires_at.timestamp(),
        display_name=ctx.user.display_name,
    )
    hub.register(c)
    writer = asyncio.create_task(c.writer())
    watchdog = asyncio.create_task(_expiry_watchdog(c))
    c.send({"kind": "ready", "user_id": str(c.user_id), "connection_id": c.id})
    try:
        while not c.closed:
            receive = asyncio.create_task(ws.receive_text())
            done, _ = await asyncio.wait({receive, writer}, timeout=IDLE_TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
            if receive not in done:
                receive.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await receive
                if not done:
                    c.close(4000)  # idle timeout
                break
            raw = receive.result()
            if len(raw) > MAX_MESSAGE_BYTES:
                c.close(1009)
                break
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError
            except ValueError:
                c.send({"kind": "error", "code": "bad_message", "message": "Invalid JSON"})
                continue
            await _handle(c, msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws_handler_error", conn=c.id)
        c.close(1011)
    finally:
        c.close(c.close_code or 1000)
        projects = hub.unregister(c)
        watchdog.cancel()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(writer, timeout=2)
        for pid in projects:
            await presence_leave(c, pid)
