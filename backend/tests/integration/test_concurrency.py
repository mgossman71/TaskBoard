"""Optimistic concurrency control and race conditions, exercised with truly
concurrent requests (separate DB transactions interleaved on one event loop)."""

import asyncio

import pytest

import forgeboard.services.dependencies as dep_module
import forgeboard.services.tasks as task_module

pytestmark = pytest.mark.asyncio


def _barrier_after(monkeypatch, module, name, parties):
    """Make `parties` concurrent requests all pass `module.name` before any proceeds."""
    barrier = asyncio.Barrier(parties)
    original = getattr(module, name)
    calls = {"n": 0}

    async def wrapped(*args, **kwargs):
        result = await original(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] <= parties:  # only the initial read of each request synchronizes
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return result

    monkeypatch.setattr(module, name, wrapped)


async def test_concurrent_edits_exactly_one_wins(client, api, world, monkeypatch):
    pid = world["project"]["id"]
    t = await api.task(world["member"], pid, "original")
    writers = [world["member"], world["owner"], world["admin"], world["member"], world["owner"]]
    # All writers read version 1 and pass the version check before anyone writes.
    _barrier_after(monkeypatch, task_module, "load_task_full", len(writers))
    results = await asyncio.gather(
        *[
            client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 1, "title": f"edit-{i}"}, headers=u.h)
            for i, u in enumerate(writers)
        ]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409, 409, 409], [r.text for r in results]
    winner = next(r.json() for r in results if r.status_code == 200)
    loser = next(r.json() for r in results if r.status_code == 409)
    assert loser["error"]["code"] == "version_conflict"
    # The conflict response carries the current server state so the client can merge.
    assert loser["error"]["details"]["current"]["title"] == winner["title"]
    assert loser["error"]["details"]["current"]["version"] == 2
    final = (await client.get(f"/api/v1/tasks/{t['id']}", headers=world["member"].h)).json()
    assert final["title"] == winner["title"] and final["version"] == 2
    # exactly one history entry for the winning update
    hist = (await client.get(f"/api/v1/tasks/{t['id']}/history", headers=world["member"].h)).json()
    assert [h["type"] for h in hist].count("task.updated") == 1


async def test_stale_version_rejected_without_data_loss(client, api, world):
    pid, m, o = world["project"]["id"], world["member"], world["owner"]
    t = await api.task(m, pid, "doc", description="v1")
    r1 = await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 1, "description": "member's edit"}, headers=m.h)
    assert r1.status_code == 200
    r2 = await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 1, "title": "owner's edit"}, headers=o.h)
    assert r2.status_code == 409
    final = (await client.get(f"/api/v1/tasks/{t['id']}", headers=m.h)).json()
    assert final["description"] == "member's edit" and final["title"] == "doc"
    # retry with the fresh version succeeds and keeps both changes
    r3 = await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": final["version"], "title": "owner's edit"}, headers=o.h)
    assert r3.status_code == 200
    assert r3.json()["description"] == "member's edit" and r3.json()["title"] == "owner's edit"


async def test_concurrent_move_and_edit_conflict(client, api, world, monkeypatch):
    pid = world["project"]["id"]
    t = await api.task(world["member"], pid, "racing")
    _barrier_after(monkeypatch, task_module, "load_task_access", 2)
    move, edit = await asyncio.gather(
        client.post(f"/api/v1/tasks/{t['id']}/move", json={"version": 1, "column_id": world["columns"][2]["id"]}, headers=world["member"].h),
        client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 1, "title": "renamed"}, headers=world["owner"].h),
    )
    assert sorted([move.status_code, edit.status_code]) == [200, 409]


async def test_concurrent_task_creation_numbers_unique(client, world):
    pid = world["project"]["id"]
    rs = await asyncio.gather(
        *[client.post(f"/api/v1/projects/{pid}/tasks", json={"title": f"t{i}"}, headers=world["member"].h) for i in range(20)]
    )
    assert all(r.status_code == 201 for r in rs)
    assert sorted(r.json()["number"] for r in rs) == list(range(1, 21))


async def test_concurrent_dependency_creation_cannot_form_cycle(client, api, world, monkeypatch):
    pid, m = world["project"]["id"], world["member"]
    a = await api.task(m, pid, "A")
    b = await api.task(m, pid, "B")
    # Both requests are authorized before either takes the per-project lock.
    _barrier_after(monkeypatch, dep_module, "load_task_access", 2)
    r1, r2 = await asyncio.gather(
        client.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]}, headers=m.h),
        client.post(f"/api/v1/tasks/{b['id']}/dependencies", json={"depends_on_id": a["id"]}, headers=m.h),
    )
    assert sorted([r1.status_code, r2.status_code]) == [201, 422], (r1.text, r2.text)
    graph = (await client.get(f"/api/v1/projects/{pid}/dependency-graph", headers=m.h)).json()
    assert len(graph["edges"]) == 1


async def test_concurrent_project_edits(client, world):
    pid = world["project"]["id"]
    rs = await asyncio.gather(
        client.patch(f"/api/v1/projects/{pid}", json={"version": 1, "name": "A"}, headers=world["owner"].h),
        client.patch(f"/api/v1/projects/{pid}", json={"version": 1, "name": "B"}, headers=world["admin"].h),
    )
    assert sorted(r.status_code for r in rs) == [200, 409]
