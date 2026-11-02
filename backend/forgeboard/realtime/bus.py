"""Redis pub/sub message bus used to fan realtime events out to every API worker."""

from __future__ import annotations

import json
import uuid
from typing import Any

from forgeboard.cache import get_redis
from forgeboard.logging import get_logger

log = get_logger(__name__)

PREFIX = "fb:"


def project_channel(project_id: uuid.UUID | str) -> str:
    return f"{PREFIX}project:{project_id}"


def org_channel(org_id: uuid.UUID | str) -> str:
    return f"{PREFIX}org:{org_id}"


def user_channel(user_id: uuid.UUID | str) -> str:
    return f"{PREFIX}user:{user_id}"


async def publish(channel: str, message: dict[str, Any]) -> None:
    try:
        await get_redis().publish(channel, json.dumps(message, default=str))
    except Exception:  # pragma: no cover - logged; clients recover through replay on reconnect
        log.exception("realtime_publish_failed", channel=channel)
