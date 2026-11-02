"""CSRF protection for the (few) cookie-authenticated endpoints.

Only /auth/refresh and /auth/logout read the refresh-token cookie; every other
endpoint requires a Bearer token which browsers never attach automatically.
Defence in depth for the cookie endpoints:
1. Refresh cookie is SameSite=Strict and HttpOnly.
2. Origin (or Referer) header, when present, must match an allowed origin.
3. Double-submit token: the non-HttpOnly `tb_csrf` cookie must equal the
   `X-CSRF-Token` request header (a cross-site page can read neither).
"""

from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi import Request

from taskboard.config import get_settings
from taskboard.errors import Forbidden

CSRF_COOKIE = "tb_csrf"
CSRF_HEADER = "x-csrf-token"


def origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in get_settings().origins


def verify_csrf(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None and (referer := request.headers.get("referer")):
        parts = urlsplit(referer)
        origin = f"{parts.scheme}://{parts.netloc}"
    if origin is not None and not origin_allowed(origin):
        raise Forbidden("Cross-origin request rejected")
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise Forbidden("CSRF token missing or invalid")
