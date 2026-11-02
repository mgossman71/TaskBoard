import pytest

pytestmark = pytest.mark.asyncio


async def test_org_creation_and_listing(client, api):
    u = await api.register()
    org = await api.org(u, "My Org")
    assert org["role"] == "owner"
    orgs = (await client.get("/api/v1/orgs", headers=u.h)).json()
    assert [o["id"] for o in orgs] == [org["id"]]
    members = (await client.get(f"/api/v1/orgs/{org['id']}/members", headers=u.h)).json()
    assert members[0]["role"] == "owner"


async def test_invitation_flow_and_email_binding(client, api, captured_emails):
    owner = await api.register()
    invitee = await api.register()
    other = await api.register()
    org = await api.org(owner)
    r = await client.post(
        f"/api/v1/orgs/{org['id']}/invitations", json={"email": invitee.email, "role": "member"}, headers=owner.h
    )
    assert r.status_code == 201
    token = r.json()["invite_url"].split("token=")[1]
    assert captured_emails and captured_emails[-1]["to"] == invitee.email
    preview = await client.get("/api/v1/invitations/preview", params={"token": token})
    assert preview.status_code == 200 and preview.json()["org_name"] == org["name"]
    # Someone else cannot use the invitation
    assert (await client.post("/api/v1/invitations/accept", json={"token": token}, headers=other.h)).status_code == 403
    assert (await client.post("/api/v1/invitations/accept", json={"token": token}, headers=invitee.h)).status_code == 200
    # Single use
    assert (await client.post("/api/v1/invitations/accept", json={"token": token}, headers=invitee.h)).status_code == 404
    roles = {m["user"]["id"]: m["role"] for m in (await client.get(f"/api/v1/orgs/{org['id']}/members", headers=owner.h)).json()}
    assert roles[invitee.id] == "member"


async def test_revoked_invitation_cannot_be_used(client, api):
    owner = await api.register()
    invitee = await api.register()
    org = await api.org(owner)
    r = await client.post(f"/api/v1/orgs/{org['id']}/invitations", json={"email": invitee.email}, headers=owner.h)
    inv = r.json()
    token = inv["invite_url"].split("token=")[1]
    assert (await client.delete(f"/api/v1/orgs/{org['id']}/invitations/{inv['id']}", headers=owner.h)).status_code == 204
    assert (await client.post("/api/v1/invitations/accept", json={"token": token}, headers=invitee.h)).status_code == 404


async def test_role_permissions_matrix(client, api, world):
    pid = world["project"]["id"]
    oid = world["org"]["id"]
    # Viewer: read but not write
    assert (await client.get(f"/api/v1/projects/{pid}/board", headers=world["viewer"].h)).status_code == 200
    r = await client.post(f"/api/v1/projects/{pid}/tasks", json={"title": "x"}, headers=world["viewer"].h)
    assert r.status_code == 403
    # Member: write tasks, but not project settings
    t = await api.task(world["member"], pid, "member task")
    r = await client.post(f"/api/v1/projects/{pid}/columns", json={"name": "QA"}, headers=world["member"].h)
    assert r.status_code == 403
    assert (await client.delete(f"/api/v1/projects/{pid}", headers=world["member"].h)).status_code == 403
    # Viewer cannot comment, member can
    assert (await client.post(f"/api/v1/tasks/{t['id']}/comments", json={"body": "hi"}, headers=world["viewer"].h)).status_code == 403
    assert (await client.post(f"/api/v1/tasks/{t['id']}/comments", json={"body": "hi"}, headers=world["member"].h)).status_code == 201
    # Admin: manage columns, members; invite; cannot invite owners
    r = await client.post(f"/api/v1/projects/{pid}/columns", json={"name": "QA"}, headers=world["admin"].h)
    assert r.status_code == 201
    r = await client.post(f"/api/v1/orgs/{oid}/invitations", json={"email": "n@example.com", "role": "owner"}, headers=world["admin"].h)
    assert r.status_code == 403
    # Member cannot invite
    r = await client.post(f"/api/v1/orgs/{oid}/invitations", json={"email": "n@example.com"}, headers=world["member"].h)
    assert r.status_code == 403
    # Only owners delete the org
    assert (await client.delete(f"/api/v1/orgs/{oid}", headers=world["admin"].h)).status_code == 403


async def test_members_only_see_assigned_projects(client, api, world):
    oid = world["org"]["id"]
    secret = await api.project(world["owner"], oid, "SECRET")  # only owner is a member
    t = await api.task(world["owner"], secret["id"], "classified")
    for who in ("member", "viewer"):
        h = world[who].h
        listed = [p["id"] for p in (await client.get(f"/api/v1/orgs/{oid}/projects", headers=h)).json()]
        assert secret["id"] not in listed and world["project"]["id"] in listed
        assert (await client.get(f"/api/v1/projects/{secret['id']}/board", headers=h)).status_code == 404
        assert (await client.get(f"/api/v1/tasks/{t['id']}", headers=h)).status_code == 404
        found = (await client.get(f"/api/v1/orgs/{oid}/tasks", params={"q": "classified"}, headers=h)).json()
        assert found["items"] == []
    # Admins see every project
    listed = [p["id"] for p in (await client.get(f"/api/v1/orgs/{oid}/projects", headers=world["admin"].h)).json()]
    assert secret["id"] in listed


async def test_role_change_rules(client, world):
    oid = world["org"]["id"]
    admin, owner, member = world["admin"], world["owner"], world["member"]
    # admin cannot promote to owner, nor demote the owner
    r = await client.patch(f"/api/v1/orgs/{oid}/members/{member.id}", json={"role": "owner"}, headers=admin.h)
    assert r.status_code == 403
    r = await client.patch(f"/api/v1/orgs/{oid}/members/{owner.id}", json={"role": "member"}, headers=admin.h)
    assert r.status_code == 403
    # last owner cannot demote themselves
    r = await client.patch(f"/api/v1/orgs/{oid}/members/{owner.id}", json={"role": "admin"}, headers=owner.h)
    assert r.status_code == 409
    # admin can change member -> viewer; member immediately loses write access
    r = await client.patch(f"/api/v1/orgs/{oid}/members/{member.id}", json={"role": "viewer"}, headers=admin.h)
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    pid = world["project"]["id"]
    assert (await client.post(f"/api/v1/projects/{pid}/tasks", json={"title": "x"}, headers=member.h)).status_code == 403
    # invalid role value
    r = await client.patch(f"/api/v1/orgs/{oid}/members/{member.id}", json={"role": "god"}, headers=owner.h)
    assert r.status_code == 422


async def test_remove_member_cleans_up_atomically(client, api, world):
    oid, pid = world["org"]["id"], world["project"]["id"]
    member = world["member"]
    t = await api.task(world["owner"], pid, "assigned", assignee_ids=[member.id])
    assert [a["id"] for a in t["assignees"]] == [member.id]
    assert (await client.delete(f"/api/v1/orgs/{oid}/members/{member.id}", headers=world["admin"].h)).status_code == 204
    detail = (await client.get(f"/api/v1/tasks/{t['id']}", headers=world["owner"].h)).json()
    assert detail["assignees"] == []
    pm = (await client.get(f"/api/v1/projects/{pid}/members", headers=world["owner"].h)).json()
    assert member.id not in [m["user"]["id"] for m in pm]
    assert (await client.get(f"/api/v1/projects/{pid}/board", headers=member.h)).status_code == 404
    assert (await client.get(f"/api/v1/orgs/{oid}", headers=member.h)).status_code == 404


async def test_last_owner_cannot_leave(client, world):
    oid = world["org"]["id"]
    r = await client.delete(f"/api/v1/orgs/{oid}/members/{world['owner'].id}", headers=world["owner"].h)
    assert r.status_code == 409
    # a member can leave voluntarily
    r = await client.delete(f"/api/v1/orgs/{oid}/members/{world['viewer'].id}", headers=world["viewer"].h)
    assert r.status_code == 204


async def test_assignee_must_have_project_access(client, api, world):
    pid = world["project"]["id"]
    r = await client.post(
        f"/api/v1/projects/{pid}/tasks", json={"title": "x", "assignee_ids": [world["outsider"].id]}, headers=world["owner"].h
    )
    assert r.status_code == 422


async def test_archived_project_is_read_only(client, api, world):
    pid = world["project"]["id"]
    t = await api.task(world["member"], pid)
    assert (await client.post(f"/api/v1/projects/{pid}/archive", headers=world["member"].h)).status_code == 403
    r = await client.post(f"/api/v1/projects/{pid}/archive", headers=world["admin"].h)
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert (await client.get(f"/api/v1/projects/{pid}/board", headers=world["member"].h)).json()["can_edit"] is False
    r = await client.patch(f"/api/v1/tasks/{t['id']}", json={"version": t["version"], "title": "new"}, headers=world["member"].h)
    assert r.status_code == 409
    archived = (await client.get(f"/api/v1/orgs/{world['org']['id']}/projects", params={"status": "archived"}, headers=world["admin"].h)).json()
    assert [p["id"] for p in archived] == [pid]
    r = await client.post(f"/api/v1/projects/{pid}/unarchive", headers=world["admin"].h)
    assert r.status_code == 200 and r.json()["status"] == "active"
