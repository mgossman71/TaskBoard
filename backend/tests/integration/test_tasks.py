import datetime as dt

import pytest

pytestmark = pytest.mark.asyncio


async def test_task_crud_and_numbering(client, api, world):
    pid = world["project"]["id"]
    m = world["member"]
    t1 = await api.task(m, pid, "First", priority="high", due_date="2030-01-02")
    t2 = await api.task(m, pid, "Second")
    assert (t1["number"], t2["number"]) == (1, 2)
    assert t1["column_id"] == world["columns"][0]["id"] and t1["version"] == 1
    r = await client.patch(
        f"/api/v1/tasks/{t1['id']}",
        json={"version": 1, "title": "First (edited)", "description": "Details\nline 2", "priority": "urgent"},
        headers=m.h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 2 and body["title"] == "First (edited)" and body["priority"] == "urgent"
    assert body["description"] == "Details\nline 2"
    r = await client.patch(f"/api/v1/tasks/{t1['id']}", json={"version": 2, "clear_due_date": True}, headers=m.h)
    assert r.json()["due_date"] is None
    # no-op update does not bump the version
    r = await client.patch(f"/api/v1/tasks/{t1['id']}", json={"version": 3, "title": "First (edited)"}, headers=m.h)
    assert r.json()["version"] == 3
    assert (await client.delete(f"/api/v1/tasks/{t1['id']}", headers=m.h)).status_code == 204
    assert (await client.get(f"/api/v1/tasks/{t1['id']}", headers=m.h)).status_code == 404
    t3 = await api.task(m, pid, "Third")
    assert t3["number"] == 3  # numbers are never reused


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"title": ""}, 422),
        ({"title": "   "}, 422),
        ({"title": "x" * 201}, 422),
        ({"title": "ok", "priority": "critical"}, 422),
        ({"title": "ok", "due_date": "not-a-date"}, 422),
        ({"title": "ok", "column_id": "00000000-0000-0000-0000-000000000000"}, 422),
        ({"title": "ok", "description": "x" * 20001}, 422),
        ({"title": "ok", "assignee_ids": ["not-a-uuid"]}, 422),
        ({"title": "x" * 200}, 201),
        ({"title": "<script>alert(1)</script>"}, 201),
        ({"title": "'; DROP TABLE tasks; --"}, 201),
    ],
)
async def test_task_input_validation(client, world, payload, status):
    r = await client.post(f"/api/v1/projects/{world['project']['id']}/tasks", json=payload, headers=world["member"].h)
    assert r.status_code == status, r.text
    if status == 201:
        # stored verbatim (React escapes on render); no SQL injection side-effects
        assert r.json()["title"] == payload["title"]


async def test_title_control_characters_stripped(client, world):
    r = await client.post(
        f"/api/v1/projects/{world['project']['id']}/tasks", json={"title": "  a\x00b\x07\n c  "}, headers=world["member"].h
    )
    assert r.json()["title"] == "ab c"


async def test_malformed_ids_and_bodies(client, world):
    h = world["member"].h
    assert (await client.get("/api/v1/tasks/not-a-uuid", headers=h)).status_code == 422
    r = await client.post(
        f"/api/v1/projects/{world['project']['id']}/tasks", content=b"{not json", headers={**h, "content-type": "application/json"}
    )
    assert r.status_code == 422
    r = await client.get(f"/api/v1/projects/{world['project']['id']}/tasks", params={"limit": 0}, headers=h)
    assert r.status_code == 422
    r = await client.get(f"/api/v1/projects/{world['project']['id']}/tasks", params={"cursor": "garbage!!"}, headers=h)
    assert r.status_code == 422


async def test_move_between_columns_sets_completed_and_order(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    cols = world["columns"]
    todo, doing, done = cols[0]["id"], cols[1]["id"], cols[3]["id"]
    a = await api.task(m, pid, "A")
    b = await api.task(m, pid, "B")
    c = await api.task(m, pid, "C")
    # Move C to the top of To Do (before A)
    r = await client.post(f"/api/v1/tasks/{c['id']}/move", json={"version": 1, "column_id": todo, "before_id": a["id"]}, headers=m.h)
    assert r.status_code == 200
    board = await api.board(m, pid)
    order = [t["title"] for t in sorted((t for t in board["tasks"] if t["column_id"] == todo), key=lambda t: t["position"])]
    assert order == ["C", "A", "B"]
    # Move A into Done
    r = await client.post(f"/api/v1/tasks/{a['id']}/move", json={"version": 1, "column_id": done}, headers=m.h)
    assert r.json()["completed_at"] is not None and r.json()["column_id"] == done
    # And back out again clears completion
    r = await client.post(f"/api/v1/tasks/{a['id']}/move", json={"version": 2, "column_id": doing}, headers=m.h)
    assert r.json()["completed_at"] is None
    # after_id in another column is rejected
    r = await client.post(
        f"/api/v1/tasks/{b['id']}/move", json={"version": 1, "column_id": doing, "after_id": c["id"]}, headers=m.h
    )
    assert r.status_code == 422


async def test_many_inserts_at_same_spot_trigger_rebalance(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    todo = world["columns"][0]["id"]
    first = await api.task(m, pid, "anchor-1")
    second = await api.task(m, pid, "anchor-2")
    moved = []
    for i in range(60):  # repeatedly insert between anchor-1 and its successor
        t = await api.task(m, pid, f"n{i}")
        r = await client.post(f"/api/v1/tasks/{t['id']}/move", json={"version": 1, "column_id": todo, "after_id": first["id"]}, headers=m.h)
        assert r.status_code == 200, r.text
        moved.append(t["title"])
    board = await api.board(m, pid)
    order = [t["title"] for t in sorted((t for t in board["tasks"] if t["column_id"] == todo), key=lambda t: (t["position"], t["id"]))]
    assert order[0] == "anchor-1" and order[-1] == "anchor-2"
    assert order[1:-1] == list(reversed(moved))
    assert len({t["position"] for t in board["tasks"] if t["column_id"] == todo}) == len(order)
    _ = second


async def test_wip_limit_enforced(client, api, world):
    pid = world["project"]["id"]
    col = world["columns"][1]
    r = await client.patch(f"/api/v1/projects/{pid}/columns/{col['id']}", json={"wip_limit": 1}, headers=world["admin"].h)
    assert r.status_code == 200
    first = await api.task(world["member"], pid, "in progress")
    r = await client.post(f"/api/v1/tasks/{first['id']}/move", json={"version": 1, "column_id": col["id"]}, headers=world["member"].h)
    assert r.status_code == 200
    t = await api.task(world["member"], pid, "waiting")
    r = await client.post(f"/api/v1/tasks/{t['id']}/move", json={"version": 1, "column_id": col["id"]}, headers=world["member"].h)
    assert r.status_code == 409 and "WIP" in r.json()["error"]["message"]
    # the intake column's own WIP limit also applies to task creation
    todo = world["columns"][0]
    await client.patch(f"/api/v1/projects/{pid}/columns/{todo['id']}", json={"wip_limit": 1}, headers=world["admin"].h)  # "waiting" already fills it
    r = await client.post(f"/api/v1/projects/{pid}/tasks", json={"title": "one too many"}, headers=world["member"].h)
    assert r.status_code == 409 and "WIP" in r.json()["error"]["message"]


async def test_tasks_can_only_be_created_in_first_column(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    cols = world["columns"]
    url = f"/api/v1/projects/{pid}/tasks"
    for later in cols[1:]:
        r = await client.post(url, json={"title": "skip planning", "column_id": later["id"]}, headers=m.h)
        assert r.status_code == 422, r.text
        assert 'first column ("To Do")' in r.json()["error"]["message"]
    r = await client.post(url, json={"title": "explicit intake", "column_id": cols[0]["id"]}, headers=m.h)
    assert r.status_code == 201 and r.json()["column_id"] == cols[0]["id"]
    r = await client.post(url, json={"title": "implicit intake"}, headers=m.h)
    assert r.status_code == 201 and r.json()["column_id"] == cols[0]["id"]
    # the rule follows the board order: after reordering, the new leftmost column is the intake
    order = [cols[1]["id"], cols[0]["id"], cols[2]["id"], cols[3]["id"]]
    assert (await client.put(f"/api/v1/projects/{pid}/columns/order", json={"column_ids": order}, headers=world["admin"].h)).status_code == 200
    r = await client.post(url, json={"title": "new intake", "column_id": cols[1]["id"]}, headers=m.h)
    assert r.status_code == 201
    r = await client.post(url, json={"title": "old intake", "column_id": cols[0]["id"]}, headers=m.h)
    assert r.status_code == 422 and 'first column ("In Progress")' in r.json()["error"]["message"]
    r = await client.post(url, json={"title": "default"}, headers=m.h)
    assert r.json()["column_id"] == cols[1]["id"]
    # nothing was created by the rejected requests
    titles = {t["title"] for t in (await api.board(m, pid))["tasks"]}
    assert titles == {"explicit intake", "implicit intake", "new intake", "default"}


async def test_column_management(client, api, world):
    pid, adm = world["project"]["id"], world["admin"].h
    cols = world["columns"]
    t = await api.task(world["member"], pid, "in todo")
    # duplicate name
    assert (await client.post(f"/api/v1/projects/{pid}/columns", json={"name": "Done"}, headers=adm)).status_code == 409
    qa = (await client.post(f"/api/v1/projects/{pid}/columns", json={"name": "QA", "after_id": cols[1]["id"]}, headers=adm)).json()
    names = [c["name"] for c in (await client.get(f"/api/v1/projects/{pid}/columns", headers=adm)).json()]
    assert names == ["To Do", "In Progress", "QA", "In Review", "Done"]
    # reorder must include every column
    assert (await client.put(f"/api/v1/projects/{pid}/columns/order", json={"column_ids": [qa["id"]]}, headers=adm)).status_code == 422
    new_order = [c["id"] for c in reversed(cols)] + [qa["id"]]
    r = await client.put(f"/api/v1/projects/{pid}/columns/order", json={"column_ids": new_order}, headers=adm)
    assert [c["id"] for c in r.json()] == new_order
    # deleting a non-empty column requires a target and moves tasks atomically
    r = await client.delete(f"/api/v1/projects/{pid}/columns/{cols[0]['id']}", headers=adm)
    assert r.status_code == 422
    r = await client.delete(f"/api/v1/projects/{pid}/columns/{cols[0]['id']}", params={"move_to": cols[3]["id"]}, headers=adm)
    assert r.status_code == 204
    task = (await client.get(f"/api/v1/tasks/{t['id']}", headers=adm)).json()
    assert task["column_id"] == cols[3]["id"] and task["completed_at"] is not None


async def test_assignees_and_labels(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    lab = (await client.post(f"/api/v1/projects/{pid}/labels", json={"name": "bug", "color": "#FF0000"}, headers=m.h)).json()
    assert lab["color"] == "#ff0000"
    assert (await client.post(f"/api/v1/projects/{pid}/labels", json={"name": "bug", "color": "#00ff00"}, headers=m.h)).status_code == 409
    assert (await client.post(f"/api/v1/projects/{pid}/labels", json={"name": "x", "color": "red"}, headers=m.h)).status_code == 422
    t = await api.task(m, pid, "labelled", label_ids=[lab["id"]], assignee_ids=[m.id, world["owner"].id])
    assert {a["id"] for a in t["assignees"]} == {m.id, world["owner"].id}
    r = await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": 1, "assignee_ids": [world["viewer"].id], "label_ids": []}, headers=m.h)
    body = r.json()
    assert [a["id"] for a in body["assignees"]] == [world["viewer"].id] and body["labels"] == []
    hist = (await client.get(f"/api/v1/tasks/{t['id']}/history", headers=m.h)).json()
    assert hist[0]["type"] == "task.updated"
    assert {x["id"] for x in hist[0]["payload"]["changes"]["assignees"]["removed"]} == {m.id, world["owner"].id}


async def test_comments(client, api, world):
    pid = world["project"]["id"]
    m, o = world["member"], world["owner"]
    t = await api.task(m, pid)
    c = (await client.post(f"/api/v1/tasks/{t['id']}/comments", json={"body": "  hello\nworld  "}, headers=m.h)).json()
    assert c["body"] == "hello\nworld" and c["author"]["id"] == m.id
    assert (await client.post(f"/api/v1/tasks/{t['id']}/comments", json={"body": ""}, headers=m.h)).status_code == 422
    # only author edits
    assert (await client.patch(f"/api/v1/comments/{c['id']}", json={"body": "x"}, headers=o.h)).status_code == 403
    r = await client.patch(f"/api/v1/comments/{c['id']}", json={"body": "edited"}, headers=m.h)
    assert r.json()["edited_at"] is not None
    # admins (owner) may delete others' comments
    assert (await client.delete(f"/api/v1/comments/{c['id']}", headers=o.h)).status_code == 204
    detail = (await client.get(f"/api/v1/tasks/{t['id']}", headers=m.h)).json()
    assert detail["comments"] == []


async def test_search_filter_sort_paginate(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    cols = world["columns"]
    lab = (await client.post(f"/api/v1/projects/{pid}/labels", json={"name": "backend", "color": "#123456"}, headers=m.h)).json()
    today = dt.date.today()
    for i in range(25):
        await api.task(
            m, pid, f"Implement feature {i}" if i % 2 == 0 else f"Fix bug {i}",
            description="database migration work" if i % 5 == 0 else "",
            priority=["low", "medium", "high", "urgent", "none"][i % 5],
            due_date=(today + dt.timedelta(days=i - 5)).isoformat(),
            assignee_ids=[m.id] if i % 3 == 0 else [],
            label_ids=[lab["id"]] if i % 4 == 0 else [],
        )
    url = f"/api/v1/projects/{pid}/tasks"
    # full-text + substring search
    r = (await client.get(url, params={"q": "feature", "include_total": True}, headers=m.h)).json()
    assert r["total"] == 13 and all("feature" in t["title"] for t in r["items"])
    r = (await client.get(url, params={"q": "migration"}, headers=m.h)).json()
    assert len(r["items"]) == 5
    r = (await client.get(url, params={"q": "eatur"}, headers=m.h)).json()  # substring
    assert len(r["items"]) == 13
    r = (await client.get(url, params={"q": "ACME-7"}, headers=m.h)).json()  # task key
    assert [t["number"] for t in r["items"]] == [7]
    # SQL/LIKE metacharacters are treated literally
    r = (await client.get(url, params={"q": "%' OR 1=1 --"}, headers=m.h)).json()
    assert r["items"] == []
    # filters
    r = (await client.get(url, params={"assignee": m.id, "include_total": True}, headers=m.h)).json()
    assert r["total"] == 9
    r = (await client.get(url, params={"unassigned": True, "include_total": True}, headers=m.h)).json()
    assert r["total"] == 16
    r = (await client.get(url, params={"label": lab["id"], "include_total": True}, headers=m.h)).json()
    assert r["total"] == 7
    r = (await client.get(url, params=[("priority", "high"), ("priority", "urgent")], headers=m.h)).json()
    assert len(r["items"]) == 10
    r = (await client.get(url, params={"overdue": True, "include_total": True}, headers=m.h)).json()
    assert r["total"] == 5
    r = (await client.get(url, params={"column": cols[1]["id"]}, headers=m.h)).json()
    assert r["items"] == []
    # sort by due date ascending with keyset pagination: no gaps, no duplicates
    seen, cursor = [], None
    while True:
        params = {"sort": "due_date", "direction": "asc", "limit": 7}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get(url, params=params, headers=m.h)).json()
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 25 and len({t["id"] for t in seen}) == 25
    dues = [t["due_date"] for t in seen]
    assert dues == sorted(dues)
    # priority sort descending, paginated
    seen, cursor = [], None
    while True:
        params = {"sort": "priority", "direction": "desc", "limit": 4}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get(url, params=params, headers=m.h)).json()
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "urgent": 4}
    ranks = [rank[t["priority"]] for t in seen]
    assert len(seen) == 25 and ranks == sorted(ranks, reverse=True)
    # title sort
    page = (await client.get(url, params={"sort": "title", "direction": "asc", "limit": 200}, headers=m.h)).json()
    titles = [t["title"].lower() for t in page["items"]]
    assert titles == sorted(titles)


async def test_listing_has_no_n_plus_one(client, api, world, query_counter):
    pid, m = world["project"]["id"], world["member"]
    lab = (await client.post(f"/api/v1/projects/{pid}/labels", json={"name": "l", "color": "#000000"}, headers=m.h)).json()

    async def count_for(n_tasks: int) -> int:
        while True:
            board = await api.board(m, pid)
            if len(board["tasks"]) >= n_tasks:
                break
            await api.task(m, pid, "t", assignee_ids=[m.id, world["owner"].id], label_ids=[lab["id"]])
        query_counter.count = 0
        r = await client.get(f"/api/v1/projects/{pid}/tasks", params={"limit": 200}, headers=m.h)
        assert r.status_code == 200
        list_q = query_counter.count
        query_counter.count = 0
        await api.board(m, pid)
        return list_q + query_counter.count

    small = await count_for(3)
    large = await count_for(40)
    assert large == small, f"query count grew with result size: {small} -> {large}"


async def test_board_cards_omit_descriptions(client, api, world):
    pid = world["project"]["id"]
    t = await api.task(world["member"], pid, "card", description="long text " * 50)
    board = await api.board(world["member"], pid)
    assert "description" not in board["tasks"][0]
    detail = (await client.get(f"/api/v1/tasks/{t['id']}", headers=world["member"].h)).json()
    assert detail["description"].startswith("long text")
