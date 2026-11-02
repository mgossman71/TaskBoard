"""Dashboard/reporting aggregates computed from live database records."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from forgeboard.authz import load_project, require_org_role, visible_projects_clause
from forgeboard.models import BoardColumn, Project, ProjectStatus, Task, User, task_assignees


async def _scope(session: AsyncSession, user: User, org_id: uuid.UUID, project_id: uuid.UUID | None):
    await require_org_role(session, org_id, user.id)
    if project_id is not None:
        access = await load_project(session, user.id, project_id)
        if access.project.org_id != org_id:
            from forgeboard.errors import NotFound

            raise NotFound("Project not found")
        return select(Project.id).where(Project.id == project_id)
    return select(Project.id).where(
        Project.org_id == org_id, visible_projects_clause(user.id), Project.status == ProjectStatus.ACTIVE
    )


async def summary(
    session: AsyncSession, user: User, org_id: uuid.UUID, project_id: uuid.UUID | None = None, days: int = 30
) -> dict[str, Any]:
    scope = (await _scope(session, user, org_id, project_id)).scalar_subquery()
    today = datetime.now(UTC).date()

    totals = (
        await session.execute(
            select(
                func.count(Task.id),
                func.count(Task.id).filter(Task.completed_at.is_not(None)),
                func.count(Task.id).filter(Task.completed_at.is_(None), Task.due_date < today),
                func.count(Task.id).filter(Task.completed_at.is_(None), Task.due_date == today),
            ).where(Task.project_id.in_(scope))
        )
    ).one()
    total, done, overdue, due_today = (int(x or 0) for x in totals)

    # Tasks grouped by status (column name, aggregated across projects)
    by_status_rows = (
        await session.execute(
            select(BoardColumn.name, BoardColumn.is_done, func.count(Task.id), func.min(BoardColumn.position))
            .join(Task, Task.column_id == BoardColumn.id)
            .where(BoardColumn.project_id.in_(scope))
            .group_by(BoardColumn.name, BoardColumn.is_done)
            .order_by(func.min(BoardColumn.position))
        )
    ).all()
    by_priority_rows = (
        await session.execute(
            select(Task.priority, func.count(Task.id))
            .where(Task.project_id.in_(scope), Task.completed_at.is_(None))
            .group_by(Task.priority)
        )
    ).all()

    # Completion per project
    proj_rows = (
        await session.execute(
            select(
                Project.id,
                Project.name,
                Project.key,
                func.count(Task.id),
                func.count(Task.id).filter(Task.completed_at.is_not(None)),
                func.count(Task.id).filter(Task.completed_at.is_(None), Task.due_date < today),
            )
            .outerjoin(Task, Task.project_id == Project.id)
            .where(Project.id.in_(scope))
            .group_by(Project.id)
            .order_by(Project.name)
        )
    ).all()

    # Workload per user (open tasks assigned)
    workload_rows = (
        await session.execute(
            select(
                User.id,
                User.display_name,
                func.count(Task.id).filter(Task.completed_at.is_(None)),
                func.count(Task.id).filter(Task.completed_at.is_(None), Task.due_date < today),
                func.count(Task.id).filter(Task.completed_at.is_(None), Task.priority.in_(["high", "urgent"])),
                func.count(Task.id).filter(Task.completed_at >= datetime.now(UTC) - timedelta(days=days)),
            )
            .join(task_assignees, task_assignees.c.user_id == User.id)
            .join(Task, Task.id == task_assignees.c.task_id)
            .where(Task.project_id.in_(scope))
            .group_by(User.id)
            .order_by(func.count(Task.id).filter(Task.completed_at.is_(None)).desc(), User.display_name)
        )
    ).all()
    unassigned_open = int(
        await session.scalar(
            select(func.count(Task.id)).where(
                Task.project_id.in_(scope),
                Task.completed_at.is_(None),
                ~select(task_assignees.c.task_id).where(task_assignees.c.task_id == Task.id).exists(),
            )
        )
        or 0
    )

    # Trend: created vs completed per day, zero-filled with generate_series
    start = today - timedelta(days=days - 1)
    series = select(
        cast(func.generate_series(start, today, literal_column("interval '1 day'")), Date).label("day")
    ).subquery()
    created = (
        select(cast(Task.created_at, Date).label("day"), func.count().label("n"))
        .where(Task.project_id.in_(scope), Task.created_at >= start)
        .group_by(literal_column("1"))
        .subquery()
    )
    completed = (
        select(cast(Task.completed_at, Date).label("day"), func.count().label("n"))
        .where(Task.project_id.in_(scope), Task.completed_at >= start)
        .group_by(literal_column("1"))
        .subquery()
    )
    trend_rows = (
        await session.execute(
            select(series.c.day, func.coalesce(created.c.n, 0), func.coalesce(completed.c.n, 0))
            .outerjoin(created, created.c.day == series.c.day)
            .outerjoin(completed, completed.c.day == series.c.day)
            .order_by(series.c.day)
        )
    ).all()

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {"org_id": str(org_id), "project_id": str(project_id) if project_id else None},
        "totals": {
            "tasks": total,
            "done": done,
            "open": total - done,
            "overdue": overdue,
            "due_today": due_today,
            "completion_pct": round(done * 100.0 / total, 1) if total else 0.0,
        },
        "by_status": [{"status": name, "is_done": is_done, "count": int(n)} for name, is_done, n, _ in by_status_rows],
        "by_priority": {str(p.value if hasattr(p, "value") else p): int(n) for p, n in by_priority_rows},
        "projects": [
            {
                "id": str(pid),
                "name": name,
                "key": key,
                "total": int(t),
                "done": int(d),
                "overdue": int(o),
                "completion_pct": round(int(d) * 100.0 / int(t), 1) if t else 0.0,
            }
            for pid, name, key, t, d, o in proj_rows
        ],
        "workload": [
            {
                "user_id": str(uid),
                "display_name": name,
                "open": int(o),
                "overdue": int(od),
                "high_priority": int(hp),
                "completed_recently": int(cr),
            }
            for uid, name, o, od, hp, cr in workload_rows
        ],
        "unassigned_open": unassigned_open,
        "trend": [
            {"date": d.isoformat() if isinstance(d, date) else str(d), "created": int(c), "completed": int(k)}
            for d, c, k in trend_rows
        ],
        "trend_days": days,
    }
