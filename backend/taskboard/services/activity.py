"""Activity log + transactional outbox for realtime events.

Mutating services call `record()` *inside* their transaction, so the activity
row commits atomically with the change. `commit()` commits the session and only
then publishes the queued events, guaranteeing clients never observe changes
that were rolled back.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from taskboard.models import ActivityEvent
from taskboard.realtime import bus

_PENDING = "tb_pending_events"
_PENDING_CONTROL = "tb_pending_control"
_POST_COMMIT = "tb_post_commit"


def record(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    type: str,
    payload: dict[str, Any],
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> ActivityEvent:
    ev = ActivityEvent(
        org_id=org_id,
        project_id=project_id,
        task_id=task_id,
        actor_id=actor_id,
        type=type,
        payload=payload,
    )
    session.add(ev)
    session.info.setdefault(_PENDING, []).append(ev)
    return ev


def queue_control(session: AsyncSession, channel: str, message: dict[str, Any]) -> None:
    """Queue a non-persisted realtime control message (e.g. access revoked) for after commit."""
    session.info.setdefault(_PENDING_CONTROL, []).append((channel, message))


def after_commit(session: AsyncSession, fn) -> None:
    """Register a sync callable to run after a successful commit (e.g. deleting files)."""
    session.info.setdefault(_POST_COMMIT, []).append(fn)


def serialize(ev: ActivityEvent, actor: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "event",
        "id": ev.id,
        "type": ev.type,
        "org_id": str(ev.org_id),
        "project_id": str(ev.project_id) if ev.project_id else None,
        "task_id": str(ev.task_id) if ev.task_id else None,
        "actor_id": str(ev.actor_id) if ev.actor_id else None,
        "actor": actor,
        "payload": ev.payload,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


async def commit(session: AsyncSession, actor: dict[str, Any] | None = None) -> list[ActivityEvent]:
    events: list[ActivityEvent] = session.info.pop(_PENDING, [])
    control = session.info.pop(_PENDING_CONTROL, [])
    post = session.info.pop(_POST_COMMIT, [])
    try:
        await session.commit()
    except BaseException:
        session.info.pop(_PENDING, None)
        raise
    for ev in events:
        msg = serialize(ev, actor)
        if ev.project_id:
            await bus.publish(bus.project_channel(ev.project_id), msg)
        else:
            await bus.publish(bus.org_channel(ev.org_id), msg)
    for channel, message in control:
        await bus.publish(channel, message)
    for fn in post:
        try:
            fn()
        except Exception:  # pragma: no cover
            from taskboard.logging import get_logger

            get_logger(__name__).exception("post_commit_hook_failed")
    return events


def discard(session: AsyncSession) -> None:
    session.info.pop(_PENDING, None)
    session.info.pop(_PENDING_CONTROL, None)
    session.info.pop(_POST_COMMIT, None)
