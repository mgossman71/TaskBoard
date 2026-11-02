"""Shared fixtures. Integration tests run against real PostgreSQL and Redis
(see compose.test.yaml); every test starts from empty tables and an empty Redis."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import event, text

from forgeboard.cache import get_redis
from forgeboard.config import get_settings
from forgeboard.db import Base, get_engine

ORIGIN = "http://testserver"
PASSWORD = "Corr3ct-Horse-Battery!"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Apply migrations exactly like production does (alembic upgrade head)."""
    subprocess.run(["alembic", "upgrade", "head"], check=True, cwd=os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(autouse=True)
async def clean_state(request) -> AsyncIterator[None]:
    if "unit" in request.node.nodeid.split("/"):
        yield
        return
    import forgeboard.models  # noqa: F401

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await get_redis().flushdb()
    root = get_settings().attachments_dir
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    yield


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from forgeboard.main import app

    transport = httpx.ASGITransport(app=app, client=("10.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={"origin": ORIGIN}) as c:
        yield c


@dataclass
class UserCtx:
    id: str
    email: str
    token: str
    display_name: str
    cookies: httpx.Cookies

    @property
    def h(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


class Api:
    """Thin helper around the HTTP API used by the tests."""

    def __init__(self, client: httpx.AsyncClient):
        self.c = client

    async def register(self, name: str | None = None, email: str | None = None) -> UserCtx:
        name = name or f"user-{uuid.uuid4().hex[:6]}"
        email = email or f"{name}-{uuid.uuid4().hex[:6]}@example.com"
        r = await self.c.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": name})
        assert r.status_code == 201, r.text
        body = r.json()
        cookies = httpx.Cookies()
        for k, v in r.cookies.items():
            cookies.set(k, v)
        self.c.cookies.clear()
        return UserCtx(body["user"]["id"], email, body["access_token"], name, cookies)

    async def org(self, u: UserCtx, name: str = "Acme") -> dict[str, Any]:
        r = await self.c.post("/api/v1/orgs", json={"name": name}, headers=u.h)
        assert r.status_code == 201, r.text
        return r.json()

    async def add_member(self, owner: UserCtx, org_id: str, member: UserCtx, role: str = "member") -> None:
        r = await self.c.post(
            f"/api/v1/orgs/{org_id}/invitations", json={"email": member.email, "role": role}, headers=owner.h
        )
        assert r.status_code == 201, r.text
        token = r.json()["invite_url"].split("token=")[1]
        r = await self.c.post("/api/v1/invitations/accept", json={"token": token}, headers=member.h)
        assert r.status_code == 200, r.text

    async def project(self, u: UserCtx, org_id: str, key: str = "PRJ", members: list[str] | None = None) -> dict:
        r = await self.c.post(
            f"/api/v1/orgs/{org_id}/projects",
            json={"name": f"Project {key}", "key": key, "member_ids": members or []},
            headers=u.h,
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def board(self, u: UserCtx, project_id: str) -> dict:
        r = await self.c.get(f"/api/v1/projects/{project_id}/board", headers=u.h)
        assert r.status_code == 200, r.text
        return r.json()

    async def task(self, u: UserCtx, project_id: str, title: str = "Task", **kw: Any) -> dict:
        r = await self.c.post(f"/api/v1/projects/{project_id}/tasks", json={"title": title, **kw}, headers=u.h)
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def api(client: httpx.AsyncClient) -> Api:
    return Api(client)


@pytest.fixture
async def world(api: Api) -> dict[str, Any]:
    """Org with owner/admin/member/viewer, one project (owner+member+viewer are members)."""
    owner = await api.register("owner")
    admin = await api.register("admin")
    member = await api.register("member")
    viewer = await api.register("viewer")
    outsider = await api.register("outsider")
    org = await api.org(owner, "Acme")
    await api.add_member(owner, org["id"], admin, "admin")
    await api.add_member(owner, org["id"], member, "member")
    await api.add_member(owner, org["id"], viewer, "viewer")
    project = await api.project(owner, org["id"], "ACME", members=[member.id, viewer.id])
    board = await api.board(owner, project["id"])
    return {
        "owner": owner,
        "admin": admin,
        "member": member,
        "viewer": viewer,
        "outsider": outsider,
        "org": org,
        "project": project,
        "columns": board["columns"],
    }


class QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *args, **kwargs) -> None:
        self.count += 1


@pytest.fixture
def query_counter():
    counter = QueryCounter()
    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", counter)
    yield counter
    event.remove(sync_engine, "before_cursor_execute", counter)


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def captured_emails(monkeypatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    async def fake_send(to: str, subject: str, body: str) -> None:
        sent.append({"to": to, "subject": subject, "body": body})

    import forgeboard.services.auth as auth_mod
    import forgeboard.services.orgs as orgs_mod

    monkeypatch.setattr(auth_mod, "send_email", fake_send)
    monkeypatch.setattr(orgs_mod, "send_email", fake_send)
    return sent


async def gather(*aws):
    return await asyncio.gather(*aws)
