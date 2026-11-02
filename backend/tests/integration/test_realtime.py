"""WebSocket synchronization, replay/recovery, presence and authorization,
against a live uvicorn server using the real Redis pub/sub fan-out."""

import asyncio
import json

import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from tests.conftest import ORIGIN

pytestmark = pytest.mark.asyncio
PORT = 8765
WS_URL = f"ws://127.0.0.1:{PORT}/api/v1/ws"


@pytest.fixture(scope="session")
async def live_server():
    from taskboard.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    yield server
    server.should_exit = True
    await task


async def recv_until(ws, pred, timeout=5.0):
    async def _loop():
        while True:
            msg = json.loads(await ws.recv())
            if pred(msg):
                return msg

    return await asyncio.wait_for(_loop(), timeout)


async def open_ws(token):
    ws = await connect(WS_URL, origin=ORIGIN)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    await recv_until(ws, lambda m: m["kind"] == "ready")
    return ws


async def subscribe(ws, project_id, since=None):
    msg = {"type": "subscribe", "project_id": project_id}
    if since is not None:
        msg["since"] = since
    await ws.send(json.dumps(msg))
    return await recv_until(ws, lambda m: m["kind"] in ("subscribed", "error", "resync_required"))


def is_event(t):
    return lambda m: m.get("kind") == "event" and m.get("type") == t


async def test_requires_authentication(live_server, settings, monkeypatch):
    monkeypatch.setattr(settings, "ws_auth_timeout_seconds", 0.5)
    async with connect(WS_URL, origin=ORIGIN) as ws:
        with pytest.raises(ConnectionClosed) as exc:
            await asyncio.wait_for(ws.recv(), 3)
        assert exc.value.rcvd.code == 4408
    async with connect(WS_URL, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "auth", "token": "not-a-jwt"}))
        msg = json.loads(await ws.recv())
        assert msg["code"] == "unauthorized"
        with pytest.raises(ConnectionClosed) as exc:
            await asyncio.wait_for(ws.recv(), 3)
        assert exc.value.rcvd.code == 4401


async def test_rejects_cross_site_origin(live_server, api):
    u = await api.register()
    try:
        async with connect(WS_URL, origin="https://evil.example") as ws:
            await ws.send(json.dumps({"type": "auth", "token": u.token}))
            with pytest.raises(ConnectionClosed) as exc:
                await asyncio.wait_for(ws.recv(), 3)
            assert exc.value.rcvd.code == 4403
    except InvalidStatus as e:  # closed before the handshake completed
        assert e.response.status_code == 403


async def test_unauthorized_subscription_denied(live_server, api):
    a = await api.register()
    b = await api.register()
    org_a = await api.org(a, "A")
    proj_a = await api.project(a, org_a["id"], "AAA")
    ws = await open_ws(b.token)
    try:
        res = await subscribe(ws, proj_a["id"])
        assert res["kind"] == "error" and res["code"] == "subscription_denied"
        res = await subscribe(ws, "00000000-0000-0000-0000-000000000000")
        assert res["kind"] == "error" and res["code"] == "subscription_denied"
        await ws.send(json.dumps({"type": "subscribe_org", "org_id": org_a["id"]}))
        res = await recv_until(ws, lambda m: m["kind"] in ("subscribed_org", "error"))
        assert res["kind"] == "error"
    finally:
        await ws.close()


async def test_two_sessions_stay_synchronized(live_server, client, api, world):
    pid = world["project"]["id"]
    owner, member = world["owner"], world["member"]
    ws_owner = await open_ws(owner.token)
    ws_member = await open_ws(member.token)
    try:
        assert (await subscribe(ws_owner, pid))["kind"] == "subscribed"
        assert (await subscribe(ws_member, pid))["kind"] == "subscribed"
        t = await api.task(owner, pid, "realtime task")
        ev = await recv_until(ws_member, is_event("task.created"))
        assert ev["payload"]["task"]["id"] == t["id"] and ev["actor"]["id"] == owner.id
        await client.post(f"/api/v1/tasks/{t['id']}/move", json={"version": 1, "column_id": world["columns"][1]["id"]}, headers=owner.h)
        ev = await recv_until(ws_member, is_event("task.moved"))
        assert ev["payload"]["task"]["column_id"] == world["columns"][1]["id"] and ev["payload"]["task"]["version"] == 2
        await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 2, "assignee_ids": [member.id]}, headers=owner.h)
        ev = await recv_until(ws_member, is_event("task.assigned"))
        assert ev["payload"]["changes"]["assignees"]["added"][0]["id"] == member.id
        await client.post(f"/api/v1/tasks/{t['id']}/comments", json={"body": "ping"}, headers=member.h)
        ev = await recv_until(ws_owner, is_event("comment.created"))
        assert ev["payload"]["comment"]["body"] == "ping"
        await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 3, "title": "renamed"}, headers=member.h)
        ev = await recv_until(ws_owner, is_event("task.updated"))
        assert ev["payload"]["task"]["title"] == "renamed"
    finally:
        await ws_owner.close()
        await ws_member.close()


async def test_reconnect_replays_missed_events(live_server, client, api, world):
    pid, owner, member = world["project"]["id"], world["owner"], world["member"]
    ws = await open_ws(member.token)
    await subscribe(ws, pid)
    t = await api.task(owner, pid, "before disconnect")
    ev = await recv_until(ws, is_event("task.created"))
    last_seen = ev["id"]
    await ws.close()
    # changes while the client is offline
    await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 1, "title": "offline edit"}, headers=owner.h)
    await api.task(owner, pid, "created offline")
    ws = await open_ws(member.token)
    try:
        await ws.send(json.dumps({"type": "subscribe", "project_id": pid, "since": last_seen}))
        replayed = []
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if msg["kind"] == "event":
                replayed.append(msg)
            if msg["kind"] == "subscribed":
                break
        assert msg["replayed"] == 2
        assert [m["type"] for m in replayed] == ["task.updated", "task.created"]
        assert replayed[0]["payload"]["task"]["title"] == "offline edit"
        assert all(m["id"] > last_seen for m in replayed)
    finally:
        await ws.close()


async def test_too_many_missed_events_requests_resync(live_server, api, world, settings, monkeypatch):
    monkeypatch.setattr(settings, "ws_replay_limit", 2)
    pid, owner = world["project"]["id"], world["owner"]
    for i in range(4):
        await api.task(owner, pid, f"t{i}")
    ws = await open_ws(world["member"].token)
    try:
        res = await subscribe(ws, pid, since=0)
        assert res["kind"] == "resync_required"
    finally:
        await ws.close()


async def test_presence_join_and_leave(live_server, api, world):
    pid = world["project"]["id"]
    ws_a = await open_ws(world["owner"].token)
    ws_b = await open_ws(world["member"].token)
    try:
        await subscribe(ws_a, pid)
        sub_b = await subscribe(ws_b, pid)
        assert {u["user_id"] for u in sub_b["presence"]} == {world["owner"].id, world["member"].id}
        await ws_b.send(json.dumps({"type": "presence", "project_id": pid, "viewing_task_id": "task-123"}))
        msg = await recv_until(
            ws_a,
            lambda m: m["kind"] == "presence"
            and any(u["user_id"] == world["member"].id and "task-123" in u["viewing_task_ids"] for u in m["users"]),
        )
        assert msg["project_id"] == pid
        await ws_b.close()
        msg = await recv_until(ws_a, lambda m: m["kind"] == "presence" and len(m["users"]) == 1)
        assert msg["users"][0]["user_id"] == world["owner"].id
    finally:
        await ws_a.close()


async def test_logout_closes_websocket(live_server, client, api):
    u = await api.register()
    ws = await open_ws(u.token)
    try:
        assert (await client.post("/api/v1/auth/logout-all", headers=u.h)).status_code == 204
        with pytest.raises(ConnectionClosed) as exc:
            await recv_until(ws, lambda m: False, timeout=5)
        assert exc.value.rcvd.code == 4401
    finally:
        await ws.close()


async def test_removed_member_loses_subscription(live_server, client, api, world):
    pid = world["project"]["id"]
    member = world["member"]
    ws = await open_ws(member.token)
    try:
        await subscribe(ws, pid)
        r = await client.delete(f"/api/v1/projects/{pid}/members/{member.id}", headers=world["admin"].h)
        assert r.status_code == 204
        msg = await recv_until(ws, lambda m: m["kind"] == "unsubscribed")
        assert msg["project_id"] == pid and msg["reason"] == "access_revoked"
        await api.task(world["owner"], pid, "secret after removal")
        with pytest.raises(asyncio.TimeoutError):
            await recv_until(ws, is_event("task.created"), timeout=1.0)
    finally:
        await ws.close()


async def test_reauth_must_match_connection(live_server, api):
    a = await api.register()
    b = await api.register()
    ws = await open_ws(a.token)
    try:
        await ws.send(json.dumps({"type": "reauth", "token": a.token}))
        assert (await recv_until(ws, lambda m: m["kind"] in ("reauthed", "error")))["kind"] == "reauthed"
        await ws.send(json.dumps({"type": "reauth", "token": b.token}))
        with pytest.raises(ConnectionClosed) as exc:
            await recv_until(ws, lambda m: False, timeout=5)
        assert exc.value.rcvd.code == 4401
    finally:
        await ws.close()


async def test_bad_messages_are_handled(live_server, api):
    u = await api.register()
    ws = await open_ws(u.token)
    try:
        await ws.send("not json")
        assert (await recv_until(ws, lambda m: m["kind"] == "error"))["code"] == "bad_message"
        await ws.send(json.dumps({"type": "nope"}))
        assert (await recv_until(ws, lambda m: m["kind"] == "error"))["code"] == "bad_message"
        await ws.send(json.dumps({"type": "ping"}))
        assert (await recv_until(ws, lambda m: m["kind"] == "pong"))["kind"] == "pong"
    finally:
        await ws.close()
