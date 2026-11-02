"""Migration safety: fresh install, re-run (idempotent), full downgrade/upgrade
cycle, model/migration drift check, and concurrent runners serialized by the
advisory lock. Uses a scratch database so the suite's DB is untouched."""

import asyncio
import os
import subprocess

import asyncpg
import pytest

from taskboard.config import get_settings

pytestmark = pytest.mark.asyncio
SCRATCH = "taskboard_migration_test"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


async def _admin_conn():
    s = get_settings()
    return await asyncpg.connect(
        host=s.postgres_host, port=s.postgres_port, user=s.postgres_user,
        password=s.postgres_password.get_secret_value(), database=s.postgres_db,
    )


@pytest.fixture
async def scratch_db():
    conn = await _admin_conn()
    await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)')
    await conn.execute(f'CREATE DATABASE "{SCRATCH}"')
    await conn.close()
    yield SCRATCH
    conn = await _admin_conn()
    await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)')
    await conn.close()


def _alembic(*args, db):
    env = {**os.environ, "POSTGRES_DB": db}
    return subprocess.run(["alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)


async def _alembic_async(*args, db):
    env = {**os.environ, "POSTGRES_DB": db}
    proc = await asyncio.create_subprocess_exec(
        "alembic", *args, cwd=BACKEND_DIR, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode() + err.decode()


async def test_fresh_rerun_downgrade_and_drift(scratch_db):
    r = _alembic("upgrade", "head", db=scratch_db)
    assert r.returncode == 0, r.stderr
    r = _alembic("upgrade", "head", db=scratch_db)  # re-run on an existing DB is a no-op
    assert r.returncode == 0, r.stderr
    assert "Running upgrade" not in r.stderr
    r = _alembic("check", db=scratch_db)  # models and migrations agree
    assert r.returncode == 0, r.stdout + r.stderr
    r = _alembic("downgrade", "base", db=scratch_db)
    assert r.returncode == 0, r.stderr
    r = _alembic("upgrade", "head", db=scratch_db)
    assert r.returncode == 0, r.stderr


async def test_concurrent_migration_runners_do_not_race(scratch_db):
    results = await asyncio.gather(*[_alembic_async("upgrade", "head", db=scratch_db) for _ in range(4)])
    assert all(code == 0 for code, _ in results), results
    applied = sum("Running upgrade  -> 0001" in out for _, out in results)
    assert applied == 1, [out for _, out in results]
    conn = await asyncpg.connect(
        host=get_settings().postgres_host, user=get_settings().postgres_user,
        password=get_settings().postgres_password.get_secret_value(), database=scratch_db,
    )
    try:
        assert await conn.fetchval("SELECT count(*) FROM alembic_version") == 1
    finally:
        await conn.close()
