"""Per-worker WebSocket connection hub.

Every API worker holds one Redis pattern subscription (`fb:*`). Messages are
forwarded *as the already-serialized JSON string* to the local connections
subscribed to the relevant project/org, so broadcasting costs one Redis
message per event and zero re-serialization per recipient.
Each connection has a bounded outbound queue drained by its own writer task;
a slow consumer whose queue overflows is disconnected (it will reconnect and
replay missed events) instead of stalling everyone else.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from starlette.websockets import WebSocket, WebSocketState

from forgeboard.cache import get_redis
from forgeboard.config import get_settings
from forgeboard.logging import get_logger
from forgeboard.realtime import bus

log = get_logger(__name__)

QUEUE_SIZE = 1000


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    user_id: uuid.UUID
    session_id: uuid.UUID
    token_expires_at: float
    display_name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    projects: set[str] = field(default_factory=set)
    orgs: set[str] = field(default_factory=set)
    viewing: dict[str, str | None] = field(default_factory=dict)
    queue: asyncio.Queue[str | None] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    closed: bool = False
    close_code: int | None = None

    def send_raw(self, data: str) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            log.warning("ws_slow_consumer_disconnected", conn=self.id, user=str(self.user_id))
            self.close(1013)

    def send(self, msg: dict[str, Any]) -> None:
        self.send_raw(json.dumps(msg, default=str))

    def close(self, code: int = 1000) -> None:
        if not self.closed:
            self.closed = True
            self.close_code = code
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait(None)

    async def writer(self) -> None:
        try:
            while True:
                item = await self.queue.get()
                if item is None:
                    break
                await self.ws.send_text(item)
        except Exception:  # connection dropped
            self.closed = True
        finally:
            if self.ws.application_state == WebSocketState.CONNECTED:
                with contextlib.suppress(Exception):
                    await self.ws.close(code=self.close_code or 1000)


class Hub:
    def __init__(self) -> None:
        self.by_project: dict[str, set[Connection]] = defaultdict(set)
        self.by_org: dict[str, set[Connection]] = defaultdict(set)
        self.by_user: dict[str, set[Connection]] = defaultdict(set)
        self._task: asyncio.Task | None = None
        self._stopping = False
        # Callback installed by the ws module to re-authorize a connection.
        self.revalidate = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._listen(), name="realtime-listener")

    async def stop(self) -> None:
        self._stopping = True
        for conns in list(self.by_user.values()):
            for c in list(conns):
                c.send({"kind": "server_restart"})
                c.close(1012)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _listen(self) -> None:
        backoff = 0.5
        while not self._stopping:
            pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
            try:
                await pubsub.psubscribe(f"{bus.PREFIX}*")
                backoff = 0.5
                async for message in pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue
                    try:
                        await self._dispatch(message["channel"], message["data"])
                    except Exception:
                        log.exception("realtime_dispatch_failed", channel=message.get("channel"))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("realtime_listener_reconnecting", backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()

    async def _dispatch(self, channel: str, data: str) -> None:
        kind, _, ident = channel.removeprefix(bus.PREFIX).partition(":")
        if kind == "project":
            for c in list(self.by_project.get(ident, ())):
                c.send_raw(data)
            msg = None
            if '"project_deleted"' in data:
                msg = json.loads(data)
                if msg.get("kind") == "project_deleted":
                    for c in list(self.by_project.get(ident, ())):
                        self.unsubscribe(c, ident)
        elif kind == "org":
            for c in list(self.by_org.get(ident, ())):
                c.send_raw(data)
        elif kind == "user":
            msg = json.loads(data)
            conns = list(self.by_user.get(ident, ()))
            if msg.get("kind") == "session_revoked":
                for c in conns:
                    if str(c.session_id) == msg.get("session_id"):
                        c.send({"kind": "error", "code": "session_revoked", "message": "Session revoked"})
                        c.close(4401)
            elif msg.get("kind") == "sessions_revoked":
                for c in conns:
                    if str(c.session_id) != msg.get("except"):
                        c.send({"kind": "error", "code": "session_revoked", "message": "Session revoked"})
                        c.close(4401)
            elif msg.get("kind") == "access_changed" and self.revalidate is not None:
                for c in conns:
                    await self.revalidate(c)
                    c.send({"kind": "access_changed"})

    # ------------------------------------------------------------ registry
    def register(self, c: Connection) -> None:
        self.by_user[str(c.user_id)].add(c)

    def unregister(self, c: Connection) -> list[str]:
        projects = list(c.projects)
        for p in projects:
            self.by_project[p].discard(c)
            if not self.by_project[p]:
                self.by_project.pop(p, None)
        for o in list(c.orgs):
            self.by_org[o].discard(c)
            if not self.by_org[o]:
                self.by_org.pop(o, None)
        self.by_user[str(c.user_id)].discard(c)
        if not self.by_user[str(c.user_id)]:
            self.by_user.pop(str(c.user_id), None)
        return projects

    def subscribe(self, c: Connection, project_id: str) -> None:
        c.projects.add(project_id)
        self.by_project[project_id].add(c)

    def unsubscribe(self, c: Connection, project_id: str) -> None:
        c.projects.discard(project_id)
        c.viewing.pop(project_id, None)
        s = self.by_project.get(project_id)
        if s is not None:
            s.discard(c)
            if not s:
                self.by_project.pop(project_id, None)
        asyncio.get_running_loop().create_task(presence_leave(c, project_id))

    def subscribe_org(self, c: Connection, org_id: str) -> None:
        c.orgs.add(org_id)
        self.by_org[org_id].add(c)

    def unsubscribe_org(self, c: Connection, org_id: str) -> None:
        c.orgs.discard(org_id)
        s = self.by_org.get(org_id)
        if s is not None:
            s.discard(c)

    def stats(self) -> dict[str, int]:
        return {
            "connections": sum(len(v) for v in self.by_user.values()),
            "projects": len(self.by_project),
        }


hub = Hub()


# ---------------------------------------------------------------- presence (Redis)


def _presence_key(project_id: str) -> str:
    return f"presence:{project_id}"


async def presence_touch(c: Connection, project_id: str, viewing: str | None = None, announce: bool = False) -> None:
    s = get_settings()
    entry = json.dumps(
        {"user_id": str(c.user_id), "display_name": c.display_name, "viewing_task_id": viewing, "ts": time.time()}
    )
    r = get_redis()
    async with r.pipeline(transaction=False) as p:
        p.hset(_presence_key(project_id), c.id, entry)
        p.expire(_presence_key(project_id), s.presence_ttl_seconds * 4)
        await p.execute()
    if announce:
        await publish_presence(project_id)


async def presence_leave(c: Connection, project_id: str) -> None:
    try:
        await get_redis().hdel(_presence_key(project_id), c.id)
        await publish_presence(project_id)
    except Exception:
        log.warning("presence_leave_failed", project=project_id)


async def presence_list(project_id: str) -> list[dict[str, Any]]:
    s = get_settings()
    r = get_redis()
    raw = await r.hgetall(_presence_key(project_id))
    now = time.time()
    users: dict[str, dict[str, Any]] = {}
    stale = []
    for conn_id, val in raw.items():
        try:
            e = json.loads(val)
        except ValueError:
            stale.append(conn_id)
            continue
        if now - e.get("ts", 0) > s.presence_ttl_seconds:
            stale.append(conn_id)
            continue
        u = users.setdefault(
            e["user_id"], {"user_id": e["user_id"], "display_name": e["display_name"], "viewing_task_ids": []}
        )
        if e.get("viewing_task_id") and e["viewing_task_id"] not in u["viewing_task_ids"]:
            u["viewing_task_ids"].append(e["viewing_task_id"])
    if stale:
        await r.hdel(_presence_key(project_id), *stale)
    return sorted(users.values(), key=lambda u: u["display_name"].lower())


async def publish_presence(project_id: str) -> None:
    users = await presence_list(project_id)
    await bus.publish(bus.project_channel(project_id), {"kind": "presence", "project_id": project_id, "users": users})
