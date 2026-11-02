import time

import httpx
import jwt
import pytest

from tests.conftest import ORIGIN, PASSWORD

pytestmark = pytest.mark.asyncio


async def test_register_login_me(client, api):
    u = await api.register("alice", "alice@example.com")
    r = await client.get("/api/v1/auth/me", headers=u.h)
    assert r.status_code == 200 and r.json()["email"] == "alice@example.com"
    assert "password" not in r.text and "hash" not in r.text
    r = await client.post("/api/v1/auth/login", json={"email": "ALICE@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert "tb_refresh" in r.cookies and "tb_csrf" in r.cookies
    set_cookie = r.headers.get_list("set-cookie")
    refresh_cookie = next(c for c in set_cookie if c.startswith("tb_refresh="))
    assert "HttpOnly" in refresh_cookie and "SameSite=strict" in refresh_cookie and "Path=/api/v1/auth" in refresh_cookie


async def test_duplicate_email_case_insensitive(client, api):
    await api.register("bob", "bob@example.com")
    r = await client.post(
        "/api/v1/auth/register", json={"email": "BOB@example.com", "password": PASSWORD, "display_name": "Bob 2"}
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD, "display_name": "x"},
        {"email": "a@example.com", "password": "short", "display_name": "x"},
        {"email": "a@example.com", "password": "alllowercaseletters", "display_name": "x"},
        {"email": "a@example.com", "password": PASSWORD, "display_name": "   "},
        {"email": "a@example.com", "password": PASSWORD, "display_name": "x" * 101},
        {"email": "a@example.com", "password": "A1!" + "a" * 200, "display_name": "x"},
        {"email": "a@example.com", "password": PASSWORD},
    ],
)
async def test_register_validation(client, payload):
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_login_errors_do_not_reveal_account_existence(client, api):
    await api.register("carol", "carol@example.com")
    wrong_pw = await client.post("/api/v1/auth/login", json={"email": "carol@example.com", "password": "Wrong-pass1!"})
    no_user = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "Wrong-pass1!"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


async def test_unauthenticated_and_tampered_tokens_rejected(client, api, settings):
    u = await api.register()
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"authorization": "Bearer garbage"})).status_code == 401
    claims = jwt.decode(u.token, options={"verify_signature": False})
    forged = jwt.encode(claims, "attacker-secret-attacker-secret!", algorithm="HS256")
    assert (await client.get("/api/v1/auth/me", headers={"authorization": f"Bearer {forged}"})).status_code == 401
    none_alg = jwt.encode(claims, key="", algorithm="none")
    assert (await client.get("/api/v1/auth/me", headers={"authorization": f"Bearer {none_alg}"})).status_code == 401
    expired = dict(claims, exp=int(time.time()) - 60)
    expired_tok = jwt.encode(expired, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    assert (await client.get("/api/v1/auth/me", headers={"authorization": f"Bearer {expired_tok}"})).status_code == 401


def _refresh_headers(cookies: httpx.Cookies) -> dict[str, str]:
    return {"x-csrf-token": cookies.get("tb_csrf") or "", "origin": ORIGIN}


async def _refresh(client, cookies: httpx.Cookies) -> httpx.Response:
    client.cookies.clear()
    for k, v in cookies.items():
        client.cookies.set(k, v)
    r = await client.post("/api/v1/auth/refresh", headers=_refresh_headers(cookies))
    client.cookies.clear()
    return r


async def test_refresh_rotation_and_replay_detection(client, api):
    u = await api.register()
    old = httpx.Cookies(u.cookies)
    r1 = await _refresh(client, old)
    assert r1.status_code == 200, r1.text
    new_refresh = r1.cookies.get("tb_refresh")
    assert new_refresh and new_refresh != old.get("tb_refresh")
    new_cookies = httpx.Cookies({"tb_refresh": new_refresh, "tb_csrf": r1.cookies.get("tb_csrf")})
    new_access = r1.json()["access_token"]
    assert (await client.get("/api/v1/auth/me", headers={"authorization": f"Bearer {new_access}"})).status_code == 200

    # Replay of the consumed token => theft assumed => whole session revoked.
    replay = await _refresh(client, old)
    assert replay.status_code == 401
    assert "reuse" in replay.json()["error"]["message"].lower()
    # The legitimately rotated token and the access token are now dead too.
    assert (await _refresh(client, new_cookies)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"authorization": f"Bearer {new_access}"})).status_code == 401


async def test_refresh_requires_csrf_token_and_same_origin(client, api):
    u = await api.register()
    client.cookies.set("tb_refresh", u.cookies.get("tb_refresh"))
    client.cookies.set("tb_csrf", u.cookies.get("tb_csrf"))
    r = await client.post("/api/v1/auth/refresh")  # no CSRF header
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/auth/refresh", headers={"x-csrf-token": u.cookies.get("tb_csrf"), "origin": "https://evil.example"}
    )
    assert r.status_code == 403
    r = await client.post("/api/v1/auth/refresh", headers={"x-csrf-token": "wrong", "origin": ORIGIN})
    assert r.status_code == 403
    client.cookies.clear()


async def test_logout_revokes_session_immediately(client, api):
    u = await api.register()
    for k, v in u.cookies.items():
        client.cookies.set(k, v)
    r = await client.post("/api/v1/auth/logout", headers=_refresh_headers(u.cookies))
    client.cookies.clear()
    assert r.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=u.h)).status_code == 401
    assert (await _refresh(client, u.cookies)).status_code == 401


async def test_sessions_list_revoke_and_logout_all(client, api):
    u = await api.register("multi", "multi@example.com")
    r = await client.post("/api/v1/auth/login", json={"email": "multi@example.com", "password": PASSWORD})
    client.cookies.clear()
    second = {"authorization": f"Bearer {r.json()['access_token']}"}
    sessions = (await client.get("/api/v1/auth/sessions", headers=u.h)).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert (await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=u.h)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=second)).status_code == 401
    # cannot revoke someone else's session
    v = await api.register()
    vs = (await client.get("/api/v1/auth/sessions", headers=v.h)).json()
    assert (await client.delete(f"/api/v1/auth/sessions/{vs[0]['id']}", headers=u.h)).status_code == 404
    assert (await client.post("/api/v1/auth/logout-all", headers=u.h)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=u.h)).status_code == 401


async def test_brute_force_lockout(client, api, settings):
    await api.register("dave", "dave@example.com")
    for _ in range(settings.login_max_failures):
        r = await client.post("/api/v1/auth/login", json={"email": "dave@example.com", "password": "Wrong-pass1!"})
        assert r.status_code == 401
    # Even the correct password is refused while locked out.
    r = await client.post("/api/v1/auth/login", json={"email": "dave@example.com", "password": PASSWORD})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0


async def test_ip_rate_limit_on_login(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "ip_auth_rate_per_minute", 3)
    codes = []
    for i in range(5):
        r = await client.post("/api/v1/auth/login", json={"email": f"x{i}@example.com", "password": "Whatever1!"})
        codes.append(r.status_code)
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


async def test_password_reset_flow(client, api, captured_emails):
    u = await api.register("erin", "erin@example.com")
    r = await client.post("/api/v1/auth/password/forgot", json={"email": "erin@example.com"})
    assert r.status_code == 202
    r2 = await client.post("/api/v1/auth/password/forgot", json={"email": "unknown@example.com"})
    assert r2.status_code == 202 and r2.json() == r.json()  # no enumeration
    assert len(captured_emails) == 1 and captured_emails[0]["to"] == "erin@example.com"
    token = captured_emails[0]["body"].split("token=")[1].split()[0]
    new_pw = "Brand-New-Passw0rd!"
    r = await client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": new_pw})
    assert r.status_code == 204
    # single use
    r = await client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": new_pw})
    assert r.status_code == 422
    # all sessions revoked; new password works, old does not
    assert (await client.get("/api/v1/auth/me", headers=u.h)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": u.email, "password": new_pw})).status_code == 200


async def test_password_reset_rejects_bad_token_and_weak_password(client):
    r = await client.post("/api/v1/auth/password/reset", json={"token": "x" * 43, "new_password": "Valid-Passw0rd!"})
    assert r.status_code == 422
    r = await client.post("/api/v1/auth/password/reset", json={"token": "x" * 43, "new_password": "weak"})
    assert r.status_code == 422


async def test_change_password_revokes_other_sessions(client, api):
    u = await api.register("frank", "frank@example.com")
    r = await client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    client.cookies.clear()
    other = {"authorization": f"Bearer {r.json()['access_token']}"}
    bad = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "Wrong-pass1!", "new_password": "Another-Passw0rd!"},
        headers=u.h,
    )
    assert bad.status_code == 422
    ok = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "Another-Passw0rd!"},
        headers=u.h,
    )
    assert ok.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=u.h)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=other)).status_code == 401


async def test_refresh_cookie_secure_behind_https(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://board.example.com")
    monkeypatch.setattr(settings, "cookie_secure", None)
    r = await client.post(
        "/api/v1/auth/register", json={"email": "tls@example.com", "password": PASSWORD, "display_name": "TLS"}
    )
    client.cookies.clear()
    assert r.status_code == 201
    cookies = r.headers.get_list("set-cookie")
    assert all("Secure" in c for c in cookies if c.startswith(("tb_refresh=", "tb_csrf=")))
