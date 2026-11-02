"""Redis-backed rate limiting and login brute-force protection.

Policy (all values configurable):
* Per-IP request budget on authentication endpoints (`IP_AUTH_RATE_PER_MINUTE`).
* Per (email, IP) failure counter: after LOGIN_MAX_FAILURES failures inside
  LOGIN_FAILURE_WINDOW_SECONDS the pair is locked for LOGIN_LOCKOUT_SECONDS.
* Per email (any IP) counter with a 4x higher threshold to slow distributed
  guessing while limiting the ability of an attacker to lock out a victim.
While locked, login is rejected *before* the password is checked, so a correct
password does not reveal itself during lockout.
"""

from __future__ import annotations

import hashlib
import time

from taskboard.cache import get_redis
from taskboard.config import get_settings
from taskboard.errors import TooManyRequests


def _h(value: str) -> str:
    return hashlib.sha256(value.lower().encode()).hexdigest()[:32]


async def enforce_ip_rate(ip: str, bucket: str, limit: int | None = None) -> None:
    s = get_settings()
    limit = limit or s.ip_auth_rate_per_minute
    window = int(time.time() // 60)
    key = f"rl:ip:{bucket}:{ip}:{window}"
    r = get_redis()
    async with r.pipeline(transaction=True) as p:
        p.incr(key)
        p.expire(key, 70)
        count, _ = await p.execute()
    if int(count) > limit:
        retry = 60 - int(time.time() % 60)
        raise TooManyRequests(headers={"Retry-After": str(max(retry, 1))})


async def check_login_allowed(email: str, ip: str) -> None:
    r = get_redis()
    keys = [f"rl:lock:pair:{_h(email)}:{ip}", f"rl:lock:acct:{_h(email)}"]
    ttls = [await r.ttl(k) for k in keys]
    locked = [t for t in ttls if t and t > 0]
    if locked:
        raise TooManyRequests(
            "Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(max(locked))},
        )


async def register_login_failure(email: str, ip: str) -> None:
    s = get_settings()
    r = get_redis()
    pair = f"rl:fail:pair:{_h(email)}:{ip}"
    acct = f"rl:fail:acct:{_h(email)}"
    async with r.pipeline(transaction=True) as p:
        p.incr(pair)
        p.expire(pair, s.login_failure_window_seconds, nx=True)
        p.incr(acct)
        p.expire(acct, s.login_failure_window_seconds, nx=True)
        pair_count, _, acct_count, _ = await p.execute()
    if int(pair_count) >= s.login_max_failures:
        await r.set(f"rl:lock:pair:{_h(email)}:{ip}", "1", ex=s.login_lockout_seconds)
        await r.delete(pair)
    if int(acct_count) >= s.login_max_failures * 4:
        await r.set(f"rl:lock:acct:{_h(email)}", "1", ex=s.login_lockout_seconds)
        await r.delete(acct)


async def clear_login_failures(email: str, ip: str) -> None:
    await get_redis().delete(f"rl:fail:pair:{_h(email)}:{ip}")
