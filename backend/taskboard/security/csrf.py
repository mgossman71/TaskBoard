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


def origin_allowed(origin: str | None, host: str | None = None) -> bool:
    """An origin is allowed if it is configured (PUBLIC_BASE_URL / ALLOWED_ORIGINS) or if it
    is the very host the request was sent to (same-origin). A cross-site page always has a
    different origin than the target host, so this keeps CSRF/CSWSH protection while not
    requiring PUBLIC_BASE_URL to match every address (IP, hostname, port) users type."""
    if not origin:
        return False
    origin = origin.rstrip("/")
    if origin in get_settings().origins:
        return True
    if host:
        netloc = urlsplit(origin).netloc.lower()
        return bool(netloc) and netloc == host.strip().lower()
    return False


def verify_csrf(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None and (referer := request.headers.get("referer")):
        parts = urlsplit(referer)
        origin = f"{parts.scheme}://{parts.netloc}"
    if origin is not None and not origin_allowed(origin, request.headers.get("host")):
        raise Forbidden("Cross-origin request rejected")
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise Forbidden("CSRF token missing or invalid")
