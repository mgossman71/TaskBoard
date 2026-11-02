import datetime as dt

import pytest

pytestmark = pytest.mark.asyncio


async def test_dashboard_reflects_database(client, api, world):
    oid, pid = world["org"]["id"], world["project"]["id"]
    m, o = world["member"], world["owner"]
    done_col = world["columns"][3]["id"]
    today = dt.date.today()
    second = await api.project(o, oid, "SEC", members=[m.id])
    t1 = await api.task(m, pid, "overdue", due_date=(today - dt.timedelta(days=2)).isoformat(), assignee_ids=[m.id], priority="urgent")
    await api.task(m, pid, "due today", due_date=today.isoformat(), assignee_ids=[m.id])
    t3 = await api.task(m, pid, "done one", assignee_ids=[o.id])
    await api.task(m, second["id"], "other project")
    await client.post(f"/api/v1/tasks/{t3['id']}/move", json={"version": 1, "column_id": done_col}, headers=m.h)
    d = (await client.get(f"/api/v1/orgs/{oid}/dashboard", headers=o.h)).json()
    assert d["totals"] == {"tasks": 4, "done": 1, "open": 3, "overdue": 1, "due_today": 1, "completion_pct": 25.0}
    by_status = {s["status"]: s["count"] for s in d["by_status"]}
    assert by_status == {"To Do": 3, "Done": 1}
    projects = {p["key"]: p for p in d["projects"]}
    assert projects["ACME"]["total"] == 3 and projects["ACME"]["done"] == 1 and projects["ACME"]["completion_pct"] == 33.3
    assert projects["SEC"]["completion_pct"] == 0.0
    workload = {w["display_name"]: w for w in d["workload"]}
    assert workload["member"]["open"] == 2 and workload["member"]["overdue"] == 1 and workload["member"]["high_priority"] == 1
    assert workload["owner"]["open"] == 0 and workload["owner"]["completed_recently"] == 1
    assert d["unassigned_open"] == 1
    assert len(d["trend"]) == 30 and d["trend"][-1]["date"] == today.isoformat()
    assert d["trend"][-1]["created"] == 4 and d["trend"][-1]["completed"] == 1
    assert sum(x["created"] for x in d["trend"]) == 4
    assert d["by_priority"]["urgent"] == 1
    # project-scoped
    p = (await client.get(f"/api/v1/orgs/{oid}/dashboard", params={"project_id": second["id"], "days": 7}, headers=o.h)).json()
    assert p["totals"]["tasks"] == 1 and len(p["trend"]) == 7
    _ = t1


async def test_dashboard_respects_project_visibility(client, api, world):
    oid = world["org"]["id"]
    hidden = await api.project(world["owner"], oid, "HIDE")
    await api.task(world["owner"], hidden["id"], "hidden task")
    await api.task(world["member"], world["project"]["id"], "visible task")
    d = (await client.get(f"/api/v1/orgs/{oid}/dashboard", headers=world["member"].h)).json()
    assert d["totals"]["tasks"] == 1 and {p["key"] for p in d["projects"]} == {"ACME"}
    r = await client.get(f"/api/v1/orgs/{oid}/dashboard", params={"project_id": hidden["id"]}, headers=world["member"].h)
    assert r.status_code == 404


async def test_activity_feed_and_task_history(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    t = await api.task(m, pid, "tracked")
    await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 1, "priority": "high", "due_date": "2031-05-06"}, headers=m.h)
    await client.post(f"/api/v1/tasks/{t['id']}/move", json={"version": 2, "column_id": world["columns"][1]["id"]}, headers=m.h)
    hist = (await client.get(f"/api/v1/tasks/{t['id']}/history", headers=m.h)).json()
    assert [h["type"] for h in hist] == ["task.moved", "task.updated", "task.created"]
    changes = hist[1]["payload"]["changes"]
    assert changes["priority"] == {"old": "none", "new": "high"}
    assert changes["due_date"] == {"old": None, "new": "2031-05-06"}
    assert hist[0]["payload"]["from_column"]["name"] == "To Do" and hist[0]["payload"]["to_column"]["name"] == "In Progress"
    assert all(h["actor"]["id"] == m.id for h in hist)
    feed = (await client.get(f"/api/v1/projects/{pid}/activity", params={"limit": 2}, headers=m.h)).json()
    assert len(feed) == 2 and feed[0]["id"] > feed[1]["id"]
    older = (await client.get(f"/api/v1/projects/{pid}/activity", params={"before": feed[-1]["id"]}, headers=m.h)).json()
    assert all(e["id"] < feed[-1]["id"] for e in older)
    newer = (await client.get(f"/api/v1/projects/{pid}/activity", params={"after": older[-1]["id"]}, headers=m.h)).json()
    assert [e["id"] for e in newer] == sorted(e["id"] for e in newer)
