import time
import uuid

import pytest
from sqlalchemy import insert, select, update

from taskboard.db import get_sessionmaker
from taskboard.models import BoardColumn, Project, Task, TaskDependency

pytestmark = pytest.mark.asyncio


async def _dep(client, user, task, on):
    return await client.post(f"/api/v1/tasks/{task['id']}/dependencies", json={"depends_on_id": on["id"]}, headers=user.h)


async def test_add_remove_and_blocked_state(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    done_col = world["columns"][3]["id"]
    a = await api.task(m, pid, "A")
    b = await api.task(m, pid, "B")
    r = await _dep(client, m, b, a)
    assert r.status_code == 201
    assert r.json()["blocked"] is True and r.json()["dependency_ids"] == [a["id"]]
    assert (await _dep(client, m, b, a)).status_code == 409  # duplicate
    deps = (await client.get(f"/api/v1/tasks/{b['id']}/dependencies", headers=m.h)).json()
    assert [d["id"] for d in deps["depends_on"]] == [a["id"]] and deps["blocked"] is True
    blocking = (await client.get(f"/api/v1/tasks/{a['id']}/dependencies", headers=m.h)).json()["blocking"]
    assert [d["id"] for d in blocking] == [b["id"]]
    # completing A unblocks B
    await client.post(f"/api/v1/tasks/{a['id']}/move", json={"version": 1, "column_id": done_col}, headers=m.h)
    board = await api.board(m, pid)
    assert next(t for t in board["tasks"] if t["id"] == b["id"])["blocked"] is False
    r = await client.delete(f"/api/v1/tasks/{b['id']}/dependencies/{a['id']}", headers=m.h)
    assert r.status_code == 200 and r.json()["dependency_ids"] == []
    assert (await client.delete(f"/api/v1/tasks/{b['id']}/dependencies/{a['id']}", headers=m.h)).status_code == 404


async def test_cycles_are_rejected_with_readable_path(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    a, b, c, d = [await api.task(m, pid, n) for n in "ABCD"]
    assert (await _dep(client, m, b, a)).status_code == 201
    assert (await _dep(client, m, c, b)).status_code == 201
    assert (await _dep(client, m, d, c)).status_code == 201
    r = await _dep(client, m, a, d)
    assert r.status_code == 422
    err = r.json()["error"]
    assert "cycle" in err["message"] and "ACME-1 → ACME-4 → ACME-3 → ACME-2 → ACME-1" in err["message"]
    assert err["details"]["cycle"] == [a["id"], d["id"], c["id"], b["id"], a["id"]]
    assert (await _dep(client, m, a, a)).status_code == 422  # self
    # diamond is fine
    assert (await _dep(client, m, d, a)).status_code == 201


async def test_cross_project_dependency_rejected(client, api, world):
    m = world["member"]
    other = await api.project(world["owner"], world["org"]["id"], "OTHER", members=[m.id])
    a = await api.task(m, world["project"]["id"], "A")
    x = await api.task(m, other["id"], "X")
    r = await _dep(client, m, a, x)
    assert r.status_code == 404


async def test_dependency_graph_topological_order_blocked_ready(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    done_col = world["columns"][3]["id"]
    t = {n: await api.task(m, pid, n, priority=p) for n, p in [("design", "low"), ("api", "high"), ("ui", "urgent"), ("release", "none"), ("docs", "medium")]}
    for task, dep in [("api", "design"), ("ui", "design"), ("release", "api"), ("release", "ui")]:
        assert (await _dep(client, m, t[task], t[dep])).status_code == 201
    g = (await client.get(f"/api/v1/projects/{pid}/dependency-graph", headers=m.h)).json()
    order = g["topological_order"]
    pos = {tid: i for i, tid in enumerate(order)}
    for task_id, dep_id in g["edges"]:
        assert pos[dep_id] < pos[task_id]
    names = {v["id"]: k for k, v in t.items()}
    # ties broken by priority: docs(medium) before design(low) among roots, ui(urgent) before api(high)
    assert [names[i] for i in order] == ["docs", "design", "ui", "api", "release"]
    assert {names[i] for i in g["ready"]} == {"design", "docs"}
    assert {names[i] for i in g["blocked"]} == {"api", "ui", "release"}
    # complete design -> api & ui ready, release still blocked
    await client.post(f"/api/v1/tasks/{t['design']['id']}/move", json={"version": 1, "column_id": done_col}, headers=m.h)
    g = (await client.get(f"/api/v1/projects/{pid}/dependency-graph", headers=m.h)).json()
    assert {names[i] for i in g["ready"]} == {"api", "ui", "docs"}
    assert {names[i] for i in g["blocked"]} == {"release"}
    g2 = (await client.get(f"/api/v1/projects/{pid}/dependency-graph", params={"include_done": False}, headers=m.h)).json()
    assert t["design"]["id"] not in {n["id"] for n in g2["nodes"]}
    # filters on the task list
    r = (await client.get(f"/api/v1/projects/{pid}/tasks", params={"dependency_state": "blocked"}, headers=m.h)).json()
    assert {names[x["id"]] for x in r["items"]} == {"release"}
    r = (await client.get(f"/api/v1/projects/{pid}/tasks", params={"dependency_state": "ready"}, headers=m.h)).json()
    assert {names[x["id"]] for x in r["items"]} == {"api", "ui", "docs"}


@pytest.mark.slow
async def test_large_project_graph_is_fast(client, api, world):
    """3,000 tasks / ~6,000 edges inserted directly, then exercised through the API."""
    pid = uuid.UUID(world["project"]["id"])
    m = world["member"]
    n = 3000
    async with get_sessionmaker()() as s:
        col = await s.scalar(select(BoardColumn.id).where(BoardColumn.project_id == pid).order_by(BoardColumn.position))
        ids = [uuid.uuid4() for _ in range(n)]
        await s.execute(
            insert(Task),
            [{"id": ids[i], "project_id": pid, "column_id": col, "number": i + 1, "title": f"T{i}", "position": float(i)} for i in range(n)],
        )
        edges = set()
        for i in range(1, n):
            edges.add((ids[i], ids[i - 1]))  # long chain
            if i > 10:
                edges.add((ids[i], ids[i - 10]))
        await s.execute(insert(TaskDependency), [{"task_id": a, "depends_on_id": b, "project_id": pid} for a, b in edges])
        await s.execute(update(Project).where(Project.id == pid).values(task_seq=n))
        await s.commit()
    t0 = time.perf_counter()
    g = (await client.get(f"/api/v1/projects/{pid}/dependency-graph", headers=m.h)).json()
    graph_s = time.perf_counter() - t0
    assert len(g["topological_order"]) == n and g["topological_order"][0] == str(ids[0])
    assert g["ready"] == [str(ids[0])]
    # adding a back-edge across the whole chain must be detected as a cycle
    t0 = time.perf_counter()
    r = await client.post(f"/api/v1/tasks/{ids[0]}/dependencies", json={"depends_on_id": str(ids[-1])}, headers=m.h)
    cycle_s = time.perf_counter() - t0
    assert r.status_code == 422
    r = await client.post(f"/api/v1/tasks/{ids[-1]}/dependencies", json={"depends_on_id": str(ids[5])}, headers=m.h)
    assert r.status_code == 201
    assert graph_s < 3.0 and cycle_s < 3.0, (graph_s, cycle_s)
    print(f"\n[perf] graph endpoint {n} tasks/{len(edges)} edges: {graph_s*1000:.0f} ms; cycle check: {cycle_s*1000:.0f} ms")
