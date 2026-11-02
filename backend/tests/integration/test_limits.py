"""Defense-in-depth limits that hold even if the API is reached without nginx."""

import os
import time
from pathlib import Path

import pytest

from forgeboard.main import JSON_BODY_LIMIT

pytestmark = pytest.mark.asyncio


async def test_oversized_json_body_rejected(client, world):
    pid = world["project"]["id"]
    big = "x" * (JSON_BODY_LIMIT + 10)
    r = await client.post(f"/api/v1/projects/{pid}/tasks", content=f'{{"title":"{big}"}}', headers={**world["member"].h, "content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


async def test_oversized_chunked_body_rejected(client, world):
    """No Content-Length (chunked streaming): bytes are counted as they arrive."""
    pid = world["project"]["id"]

    async def stream():
        for _ in range(20):
            yield b"x" * 100_000

    r = await client.post(f"/api/v1/projects/{pid}/tasks", content=stream(), headers={**world["member"].h, "content-type": "application/json"})
    assert r.status_code == 413


async def test_oversized_multipart_rejected_before_app(client, api, world, settings, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    t = await api.task(world["member"], world["project"]["id"])
    data = b"a" * (2 * 1024 * 1024 + 100)  # over upload limit + 1 MB multipart allowance
    r = await client.post(f"/api/v1/tasks/{t['id']}/attachments", files={"file": ("big.txt", data, "text/plain")}, headers=world["member"].h)
    assert r.status_code == 413


async def test_normal_requests_unaffected(client, api, world):
    t = await api.task(world["member"], world["project"]["id"], "ok", description="d" * 15000)
    assert t["title"] == "ok"
    r = await client.post(f"/api/v1/tasks/{t['id']}/attachments", files={"file": ("n.txt", b"hello", "text/plain")}, headers=world["member"].h)
    assert r.status_code == 201


async def test_orphan_sweep_is_batched_and_respects_grace(client, api, world, settings, monkeypatch):
    import forgeboard.services.attachments as att
    from forgeboard.db import get_sessionmaker

    t = await api.task(world["member"], world["project"]["id"])
    kept = []
    for i in range(3):
        r = await client.post(f"/api/v1/tasks/{t['id']}/attachments", files={"file": (f"k{i}.txt", b"keep", "text/plain")}, headers=world["member"].h)
        kept.append(r.json()["id"])
    root = Path(settings.attachments_dir)
    old = time.time() - 7200
    real_files = [p for p in root.rglob("*") if p.is_file()]
    for p in real_files:
        os.utime(p, (old, old))
    orphans = []
    for i in range(7):
        p = root / "ab" / f"ab{i:038x}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"orphan")
        os.utime(p, (old, old))
        orphans.append(p)
    young = root / "cd" / ("cd" + "0" * 38)
    young.parent.mkdir(parents=True, exist_ok=True)
    young.write_bytes(b"in-flight upload")  # within the grace period
    partial = root / "ef" / ("ef" + "1" * 38 + ".part")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"crashed upload")
    os.utime(partial, (old, old))
    monkeypatch.setattr(att, "SWEEP_BATCH", 2)  # force several DB batches
    async with get_sessionmaker()() as s:
        removed = await att.sweep_orphans(s)
    assert removed == 8
    assert all(not p.exists() for p in orphans) and not partial.exists()
    assert young.exists() and all(p.exists() for p in real_files)
    for aid in kept:
        assert (await client.get(f"/api/v1/attachments/{aid}/download", headers=world["member"].h)).status_code == 200
