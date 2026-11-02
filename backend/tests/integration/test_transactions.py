"""Transactional integrity of multi-record operations and the retention policy."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

import taskboard.services.projects as projects_module
from taskboard.db import get_sessionmaker
from taskboard.models import ActivityEvent, Attachment, Comment, Task, TaskDependency

pytestmark = pytest.mark.asyncio

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89" + b"\x00" * 64


async def _populated_project(client, api, world):
    pid, m = world["project"]["id"], world["member"]
    a = await api.task(m, pid, "A")
    b = await api.task(m, pid, "B")
    await client.post(f"/api/v1/tasks/{b['id']}/dependencies", json={"depends_on_id": a["id"]}, headers=m.h)
    await client.post(f"/api/v1/tasks/{a['id']}/comments", json={"body": "c1"}, headers=m.h)
    att = (await client.post(f"/api/v1/tasks/{a['id']}/attachments", files={"file": ("p.png", PNG, "image/png")}, headers=m.h)).json()
    return a, b, att


async def _counts(project_id):
    async with get_sessionmaker()() as s:
        return {
            "tasks": await s.scalar(select(func.count()).select_from(Task).where(Task.project_id == project_id)),
            "deps": await s.scalar(select(func.count()).select_from(TaskDependency).where(TaskDependency.project_id == project_id)),
            "comments": await s.scalar(select(func.count()).select_from(Comment).join(Task).where(Task.project_id == project_id)),
            "attachments": await s.scalar(select(func.count()).select_from(Attachment).where(Attachment.project_id == project_id)),
            "activity": await s.scalar(select(func.count()).select_from(ActivityEvent).where(ActivityEvent.project_id == project_id)),
        }


def _attachment_files(settings) -> list[Path]:
    root = Path(settings.attachments_dir)
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


async def test_delete_project_removes_everything_and_keeps_audit(client, api, world, settings):
    import uuid

    a, b, att = await _populated_project(client, api, world)
    pid = uuid.UUID(world["project"]["id"])
    before = await _counts(pid)
    assert before == {"tasks": 2, "deps": 1, "comments": 1, "attachments": 1, "activity": before["activity"]}
    files_before = len(_attachment_files(settings))
    r = await client.delete(f"/api/v1/projects/{pid}", headers=world["admin"].h)
    assert r.status_code == 204
    after = await _counts(pid)
    assert after == {"tasks": 0, "deps": 0, "comments": 0, "attachments": 0, "activity": 0}
    assert len(_attachment_files(settings)) == files_before - 1
    org_activity = (await client.get(f"/api/v1/orgs/{world['org']['id']}/activity", headers=world["owner"].h)).json()
    deleted = [e for e in org_activity if e["type"] == "project.deleted"]
    assert len(deleted) == 1
    assert deleted[0]["payload"]["project"]["name"] == world["project"]["name"]
    assert deleted[0]["payload"]["project"]["task_count"] == 2


async def test_failed_project_delete_rolls_back_completely(client, api, world, settings, monkeypatch):
    import uuid

    await _populated_project(client, api, world)
    pid = uuid.UUID(world["project"]["id"])
    before = await _counts(pid)
    files_before = len(_attachment_files(settings))
    real_record = projects_module.activity.record

    def boom(*args, **kwargs):
        if kwargs.get("type") == "project.deleted":
            raise RuntimeError("simulated crash after the DELETE statement ran")
        return real_record(*args, **kwargs)

    monkeypatch.setattr(projects_module.activity, "record", boom)
    r = await client.delete(f"/api/v1/projects/{pid}", headers=world["admin"].h)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error" and "simulated" not in r.text
    monkeypatch.setattr(projects_module.activity, "record", real_record)
    assert await _counts(pid) == before
    assert len(_attachment_files(settings)) == files_before  # files only deleted after commit
    assert (await client.get(f"/api/v1/projects/{pid}/board", headers=world["owner"].h)).status_code == 200


async def test_delete_task_cascades_but_keeps_history(client, api, world):
    a, b, _ = await _populated_project(client, api, world)
    m = world["member"]
    r = await client.delete(f"/api/v1/tasks/{a['id']}", headers=m.h)
    assert r.status_code == 204
    # dependency edge from B is gone, B is no longer blocked
    detail = (await client.get(f"/api/v1/tasks/{b['id']}", headers=m.h)).json()
    assert detail["depends_on"] == [] and detail["blocked"] is False
    activity = (await client.get(f"/api/v1/projects/{world['project']['id']}/activity", headers=m.h)).json()
    types = [e["type"] for e in activity]
    assert "task.deleted" in types and "task.created" in types
    deleted = next(e for e in activity if e["type"] == "task.deleted")
    assert deleted["payload"]["task"]["title"] == "A"
    assert deleted["payload"]["unblocked_candidates"] == [b["id"]]


async def test_failed_task_update_does_not_partially_apply(client, api, world, monkeypatch):
    pid, m = world["project"]["id"], world["member"]
    t = await api.task(m, pid, "atomic", assignee_ids=[m.id])
    import taskboard.services.tasks as tasks_module

    real = tasks_module.task_snapshot

    async def boom(*args, **kwargs):
        raise RuntimeError("crash after assignee rows were changed")

    monkeypatch.setattr(tasks_module, "task_snapshot", boom)
    r = await client.patch(
        f"/api/v1/tasks/{t['id']}", json={"version": 1, "title": "changed", "assignee_ids": [world["owner"].id]}, headers=m.h
    )
    assert r.status_code == 500
    monkeypatch.setattr(tasks_module, "task_snapshot", real)
    detail = (await client.get(f"/api/v1/tasks/{t['id']}", headers=m.h)).json()
    assert detail["title"] == "atomic" and detail["version"] == 1
    assert [a["id"] for a in detail["assignees"]] == [m.id]


async def test_delete_org_cascades(client, api, world, settings):
    await _populated_project(client, api, world)
    oid = world["org"]["id"]
    r = await client.delete(f"/api/v1/orgs/{oid}", headers=world["owner"].h)
    assert r.status_code == 204
    assert (await client.get(f"/api/v1/orgs/{oid}", headers=world["owner"].h)).status_code == 404
    assert _attachment_files(settings) == []
