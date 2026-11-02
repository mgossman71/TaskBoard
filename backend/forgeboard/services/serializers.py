"""Helpers converting ORM objects into API/realtime payloads."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from forgeboard.models import BoardColumn, Task, TaskDependency, User
from forgeboard.schemas.auth import UserBrief
from forgeboard.schemas.task import TaskCardOut, TaskOut


def user_brief(u: User | None) -> dict[str, Any] | None:
    return UserBrief.model_validate(u).model_dump(mode="json") if u else None


def task_query():
    return select(Task).options(selectinload(Task.assignees), selectinload(Task.labels))


async def load_task_full(session: AsyncSession, task_id: uuid.UUID) -> Task | None:
    return await session.scalar(task_query().where(Task.id == task_id).execution_options(populate_existing=True))


async def dependency_info(
    session: AsyncSession, task_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[uuid.UUID]], set[uuid.UUID]]:
    """For the given tasks return (task -> depends_on ids, set of blocked task ids)."""
    if not task_ids:
        return {}, set()
    rows = (
        await session.execute(
            select(TaskDependency.task_id, TaskDependency.depends_on_id, BoardColumn.is_done)
            .join(Task, Task.id == TaskDependency.depends_on_id)
            .join(BoardColumn, BoardColumn.id == Task.column_id)
            .where(TaskDependency.task_id.in_(task_ids))
        )
    ).all()
    deps: dict[uuid.UUID, list[uuid.UUID]] = {}
    blocked: set[uuid.UUID] = set()
    for tid, dep_id, dep_done in rows:
        deps.setdefault(tid, []).append(dep_id)
        if not dep_done:
            blocked.add(tid)
    return deps, blocked


async def tasks_out(session: AsyncSession, tasks: list[Task], schema: type[TaskCardOut] = TaskOut) -> list:
    deps, blocked = await dependency_info(session, [t.id for t in tasks])
    out = []
    for t in tasks:
        o = schema.model_validate(t)
        o.dependency_ids = deps.get(t.id, [])
        o.blocked = t.id in blocked
        out.append(o)
    return out


async def task_snapshot(session: AsyncSession, task_id: uuid.UUID) -> dict[str, Any]:
    task = await load_task_full(session, task_id)
    assert task is not None
    return (await tasks_out(session, [task]))[0].model_dump(mode="json")
