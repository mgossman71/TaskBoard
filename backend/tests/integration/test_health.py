import pytest

pytestmark = pytest.mark.asyncio


async def test_liveness_and_readiness(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    r = await client.get("/api/health/ready")
    body = r.json()
    assert r.status_code == 200, body
    assert body["checks"]["database"] == "ok" and body["checks"]["redis"] == "ok"
    assert body["checks"]["schema_version"] == "0001"


async def test_unknown_route_returns_json_error(client):
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert r.headers["x-request-id"]
    assert r.headers["cache-control"] == "no-store"
