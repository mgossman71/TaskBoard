"""Task dependency engine (DAG) backed by PostgreSQL.

Consistency under concurrency: every dependency mutation takes a per-project
transaction-scoped advisory lock before reading the edge set, so two concurrent
requests cannot each pass the cycle check and jointly create a cycle.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from taskboard.authz import Need, load_project, load_task_access
from taskboard.domain import dag
from taskboard.errors import Conflict, NotFound, ValidationFailed
from taskboard.models import BoardColumn, Priority, Task, TaskDependency, User
from taskboard.schemas.task import DependencyGraphOut, TaskOut, TaskRef
from taskboard.services import activity
from taskboard.services.serializers import task_snapshot, user_brief

MAX_DEPENDENCIES_PER_TASK = 100


def _lock_key(project_id: uuid.UUID) -> int:
    return int.from_bytes(project_id.bytes[:8], "big", signed=True)


async def _project_edges(session: AsyncSession, project_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID]]:
    rows = await session.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_id).where(TaskDependency.project_id == project_id)
    )
    return [(a, b) for a, b in rows.all()]


async def add_dependency(session: AsyncSession, user: User, task_id: uuid.UUID, depends_on_id: uuid.UUID) -> TaskOut:
    project_id, access = await load_task_access(session, user.id, task_id, Need.WRITE)
    await session.execute(select(func.pg_advisory_xact_lock(_lock_key(project_id))))
    other = await session.scalar(select(Task).where(Task.id == depends_on_id, Task.project_id == project_id))
    if other is None:
        # Same response whether the task doesn't exist or lives in another project/org.
        raise NotFound("Dependency target task not found in this project")
    edges = await _project_edges(session, project_id)
    if (task_id, depends_on_id) in set(edges):
        raise Conflict("This dependency already exists")
    if sum(1 for t, _ in edges if t == task_id) >= MAX_DEPENDENCIES_PER_TASK:
        raise ValidationFailed(f"A task can have at most {MAX_DEPENDENCIES_PER_TASK} dependencies")
    cycle = dag.cycle_if_added(edges, task_id, depends_on_id)
    if cycle is not None:
        numbers = dict((await session.execute(select(Task.id, Task.number).where(Task.id.in_(set(cycle))))).all())
        key = access.project.key
        readable = " → ".join(f"{key}-{numbers.get(n, '?')}" for n in cycle)
        raise ValidationFailed(
            f"Adding this dependency would create a cycle: {readable}",
            details={"cycle": [str(n) for n in cycle]},
        )
    session.add(TaskDependency(task_id=task_id, depends_on_id=depends_on_id, project_id=project_id, created_by=user.id))
    await session.flush()
    snap = await task_snapshot(session, task_id)
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=project_id,
        task_id=task_id,
        actor_id=user.id,
        type="dependency.added",
        payload={"task": snap, "depends_on": {"id": str(other.id), "number": other.number, "title": other.title}},
    )
    await activity.commit(session, user_brief(user))
    return TaskOut.model_validate(snap)


async def remove_dependency(session: AsyncSession, user: User, task_id: uuid.UUID, depends_on_id: uuid.UUID) -> TaskOut:
    project_id, access = await load_task_access(session, user.id, task_id, Need.WRITE)
    await session.execute(select(func.pg_advisory_xact_lock(_lock_key(project_id))))
    res = await session.execute(
        delete(TaskDependency).where(TaskDependency.task_id == task_id, TaskDependency.depends_on_id == depends_on_id)
    )
    if res.rowcount == 0:
        raise NotFound("Dependency not found")
    snap = await task_snapshot(session, task_id)
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=project_id,
        task_id=task_id,
        actor_id=user.id,
        type="dependency.removed",
        payload={"task": snap, "depends_on_id": str(depends_on_id)},
    )
    await activity.commit(session, user_brief(user))
    return TaskOut.model_validate(snap)


async def dependency_graph(
    session: AsyncSession, user: User, project_id: uuid.UUID, include_done: bool = True
) -> DependencyGraphOut:
    await load_project(session, user.id, project_id, Need.READ)
    rows = (
        await session.execute(
            select(Task.id, Task.number, Task.title, Task.column_id, Task.priority, BoardColumn.is_done)
            .join(BoardColumn, BoardColumn.id == Task.column_id)
            .where(Task.project_id == project_id)
        )
    ).all()
    edges = await _project_edges(session, project_id)
    done = {r[0] for r in rows if r[5]}
    meta = {r[0]: r for r in rows}
    # Deterministic order: dependencies first, then higher priority, then lower task number.
    order = dag.topological_order(meta.keys(), edges, key=lambda n: (-Priority(meta[n][4]).rank, meta[n][1]))
    blocked, ready = dag.blocked_and_ready(meta.keys(), edges, done)
    visible = set(meta) if include_done else set(meta) - done
    nodes = [TaskRef(id=r[0], number=r[1], title=r[2], column_id=r[3], done=r[5]) for r in rows if r[0] in visible]
    nodes.sort(key=lambda n: n.number)
    return DependencyGraphOut(
        nodes=nodes,
        edges=[(a, b) for a, b in edges if a in visible and b in visible],
        topological_order=[n for n in order if n in visible],
        blocked=sorted(blocked, key=lambda n: meta[n][1]),
        ready=sorted(ready, key=lambda n: (-Priority(meta[n][4]).rank, meta[n][1])),
    )
