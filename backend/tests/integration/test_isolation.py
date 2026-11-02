"""Cross-organization isolation: a user of org B must not be able to read or
modify anything of org A, and responses must not leak whether resources exist."""

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def two_orgs(api, client):
    a = await api.register("alice")
    b = await api.register("bob")
    org_a = await api.org(a, "Alpha Secret Corp")
    org_b = await api.org(b, "Beta Inc")
    proj_a = await api.project(a, org_a["id"], "ALPHA")
    await api.project(b, org_b["id"], "BETA")
    board = await api.board(a, proj_a["id"])
    label = (await client.post(f"/api/v1/projects/{proj_a['id']}/labels", json={"name": "confidential", "color": "#ff0000"}, headers=a.h)).json()
    t1 = await api.task(a, proj_a["id"], "Alpha merger plan", description="top secret details")
    t2 = await api.task(a, proj_a["id"], "Alpha second task")
    await client.post(f"/api/v1/tasks/{t2['id']}/dependencies", json={"depends_on_id": t1["id"]}, headers=a.h)
    comment = (await client.post(f"/api/v1/tasks/{t1['id']}/comments", json={"body": "secret comment"}, headers=a.h)).json()
    files = {"file": ("plan.txt", b"secret file contents", "text/plain")}
    att = (await client.post(f"/api/v1/tasks/{t1['id']}/attachments", files=files, headers=a.h)).json()
    return {
        "a": a, "b": b, "org_a": org_a, "org_b": org_b, "proj_a": proj_a, "t1": t1, "t2": t2,
        "comment": comment, "att": att, "label": label, "column": board["columns"][0],
    }


SECRET_MARKERS = ["Alpha", "secret", "ALPHA", "merger", "confidential"]


async def test_cross_org_reads_are_not_found(client, two_orgs):
    w = two_orgs
    b = w["b"].h
    oa, pa, t1 = w["org_a"]["id"], w["proj_a"]["id"], w["t1"]["id"]
    reads = [
        f"/api/v1/orgs/{oa}",
        f"/api/v1/orgs/{oa}/members",
        f"/api/v1/orgs/{oa}/projects",
        f"/api/v1/orgs/{oa}/tasks",
        f"/api/v1/orgs/{oa}/activity",
        f"/api/v1/orgs/{oa}/dashboard",
        f"/api/v1/orgs/{oa}/invitations",
        f"/api/v1/projects/{pa}",
        f"/api/v1/projects/{pa}/board",
        f"/api/v1/projects/{pa}/tasks",
        f"/api/v1/projects/{pa}/columns",
        f"/api/v1/projects/{pa}/labels",
        f"/api/v1/projects/{pa}/members",
        f"/api/v1/projects/{pa}/activity",
        f"/api/v1/projects/{pa}/dependency-graph",
        f"/api/v1/tasks/{t1}",
        f"/api/v1/tasks/{t1}/history",
        f"/api/v1/tasks/{t1}/dependencies",
        f"/api/v1/attachments/{w['att']['id']}/download",
    ]
    for url in reads:
        r = await client.get(url, headers=b)
        assert r.status_code == 404, (url, r.status_code, r.text)
        for marker in SECRET_MARKERS:
            assert marker not in r.text, (url, marker)


async def test_cross_org_writes_are_rejected(client, two_orgs):
    w = two_orgs
    b = w["b"].h
    oa, pa, t1, t2 = w["org_a"]["id"], w["proj_a"]["id"], w["t1"]["id"], w["t2"]["id"]
    col = w["column"]["id"]
    writes = [
        ("patch", f"/api/v1/orgs/{oa}", {"name": "pwned"}),
        ("delete", f"/api/v1/orgs/{oa}", None),
        ("post", f"/api/v1/orgs/{oa}/invitations", {"email": "x@example.com"}),
        ("patch", f"/api/v1/orgs/{oa}/members/{w['a'].id}", {"role": "viewer"}),
        ("delete", f"/api/v1/orgs/{oa}/members/{w['a'].id}", None),
        ("post", f"/api/v1/orgs/{oa}/projects", {"name": "x", "key": "XX"}),
        ("patch", f"/api/v1/projects/{pa}", {"version": 1, "name": "pwned"}),
        ("post", f"/api/v1/projects/{pa}/archive", None),
        ("delete", f"/api/v1/projects/{pa}", None),
        ("post", f"/api/v1/projects/{pa}/tasks", {"title": "x"}),
        ("post", f"/api/v1/projects/{pa}/columns", {"name": "x"}),
        ("delete", f"/api/v1/projects/{pa}/columns/{col}", None),
        ("post", f"/api/v1/projects/{pa}/labels", {"name": "x", "color": "#000000"}),
        ("delete", f"/api/v1/projects/{pa}/labels/{w['label']['id']}", None),
        ("post", f"/api/v1/projects/{pa}/members", {"user_ids": [w["b"].id]}),
        ("patch", f"/api/v1/tasks/{t1}", {"version": 1, "title": "pwned"}),
        ("post", f"/api/v1/tasks/{t1}/move", {"version": 1, "column_id": col}),
        ("delete", f"/api/v1/tasks/{t1}", None),
        ("post", f"/api/v1/tasks/{t1}/comments", {"body": "x"}),
        ("patch", f"/api/v1/comments/{w['comment']['id']}", {"body": "x"}),
        ("delete", f"/api/v1/comments/{w['comment']['id']}", None),
        ("delete", f"/api/v1/attachments/{w['att']['id']}", None),
        ("post", f"/api/v1/tasks/{t1}/dependencies", {"depends_on_id": t2}),
        ("delete", f"/api/v1/tasks/{t2}/dependencies/{t1}", None),
    ]
    for method, url, body in writes:
        kwargs = {"headers": b}
        if body is not None:
            kwargs["json"] = body
        r = await client.request(method.upper(), url, **kwargs)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
    r = await client.post(f"/api/v1/tasks/{t1}/attachments", files={"file": ("a.txt", b"x", "text/plain")}, headers=b)
    assert r.status_code == 404
    # nothing changed for A
    a = w["a"].h
    task = (await client.get(f"/api/v1/tasks/{t1}", headers=a)).json()
    assert task["title"] == "Alpha merger plan" and len(task["comments"]) == 1 and len(task["attachments"]) == 1
    assert (await client.get(f"/api/v1/orgs/{oa}", headers=a)).json()["name"] == "Alpha Secret Corp"


async def test_cannot_link_foreign_resources_into_own_org(client, api, two_orgs):
    """B owns its own project but tries to reference A's ids inside it."""
    w = two_orgs
    b = w["b"]
    org_b = w["org_b"]["id"]
    proj_b = (await client.get(f"/api/v1/orgs/{org_b}/projects", headers=b.h)).json()[0]["id"]
    own_task = await api.task(b, proj_b, "own")
    r = await client.post(f"/api/v1/tasks/{own_task['id']}/dependencies", json={"depends_on_id": w["t1"]["id"]}, headers=b.h)
    assert r.status_code == 404
    r = await client.post(f"/api/v1/projects/{proj_b}/tasks", json={"title": "x", "column_id": w["column"]["id"]}, headers=b.h)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/projects/{proj_b}/tasks", json={"title": "x", "label_ids": [w["label"]["id"]]}, headers=b.h)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/projects/{proj_b}/tasks", json={"title": "x", "assignee_ids": [w["a"].id]}, headers=b.h)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/projects/{proj_b}/members", json={"user_ids": [w["a"].id]}, headers=b.h)
    assert r.status_code == 422
    r = await client.get("/api/v1/orgs/" + org_b + "/dashboard", params={"project_id": w["proj_a"]["id"]}, headers=b.h)
    assert r.status_code == 404


async def test_search_never_returns_foreign_tasks(client, two_orgs):
    b = two_orgs["b"]
    r = await client.get(f"/api/v1/orgs/{two_orgs['org_b']['id']}/tasks", params={"q": "Alpha"}, headers=b.h)
    assert r.status_code == 200 and r.json()["items"] == []
    orgs = (await client.get("/api/v1/orgs", headers=b.h)).json()
    assert [o["name"] for o in orgs] == ["Beta Inc"]
