"""Tasks: CRUD, moves, optimistic concurrency, search/pagination, comments, history."""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from sqlalchemy import Select, and_, case, delete, exists, func, insert, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from forgeboard.authz import (
    Need,
    ProjectAccess,
    load_project,
    load_task_access,
    require_org_role,
    visible_projects_clause,
)
from forgeboard.domain.positions import position_between, rebalanced
from forgeboard.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from forgeboard.models import (
    ActivityEvent,
    Attachment,
    BoardColumn,
    Comment,
    Label,
    Priority,
    Project,
    Role,
    Task,
    TaskDependency,
    User,
    task_assignees,
    task_labels,
)
from forgeboard.schemas.task import CommentOut, TaskCreate, TaskMove, TaskOut, TaskRef, TaskUpdate
from forgeboard.services import activity
from forgeboard.services.attachments import delete_files_later
from forgeboard.services.projects import project_users
from forgeboard.services.serializers import load_task_full, task_query, task_snapshot, tasks_out, user_brief

POSITION_STEP = 1024.0


def _now() -> datetime:
    return datetime.now(UTC)


async def _column(session: AsyncSession, project_id: uuid.UUID, column_id: uuid.UUID) -> BoardColumn:
    col = await session.scalar(
        select(BoardColumn).where(BoardColumn.id == column_id, BoardColumn.project_id == project_id)
    )
    if col is None:
        raise ValidationFailed("Column does not belong to this project")
    return col


async def _validate_assignees(session: AsyncSession, access: ProjectAccess, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    allowed = {u.id for u in await project_users(session, access.project)}
    bad = [str(i) for i in ids if i not in allowed]
    if bad:
        raise ValidationFailed("Assignees must have access to this project", details={"user_ids": bad})


async def _validate_labels(session: AsyncSession, project_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    found = set(
        (await session.scalars(select(Label.id).where(Label.project_id == project_id, Label.id.in_(ids)))).all()
    )
    bad = [str(i) for i in ids if i not in found]
    if bad:
        raise ValidationFailed("Labels must belong to this project", details={"label_ids": bad})


def _record(session: AsyncSession, access: ProjectAccess, user: User, type_: str, task_id, payload: dict) -> None:
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        task_id=task_id,
        actor_id=user.id,
        type=type_,
        payload=payload,
    )


# ---------------------------------------------------------------- create / read


async def create_task(session: AsyncSession, user: User, project_id: uuid.UUID, data: TaskCreate) -> TaskOut:
    access = await load_project(session, user.id, project_id, Need.WRITE)
    if data.column_id is not None:
        col = await _column(session, project_id, data.column_id)
    else:
        col = await session.scalar(
            select(BoardColumn).where(BoardColumn.project_id == project_id).order_by(BoardColumn.position).limit(1)
        )
        if col is None:
            raise Conflict("Project has no columns")
    if col.wip_limit is not None:
        count = await session.scalar(select(func.count()).where(Task.column_id == col.id))
        if (count or 0) >= col.wip_limit:
            raise Conflict(f"Column '{col.name}' has reached its WIP limit of {col.wip_limit}")
    await _validate_assignees(session, access, data.assignee_ids)
    await _validate_labels(session, project_id, data.label_ids)
    # Atomic per-project sequence (row lock on the project row).
    number = await session.scalar(
        update(Project)
        .where(Project.id == project_id)
        .values(task_seq=Project.task_seq + 1)
        .returning(Project.task_seq)
    )
    max_pos = await session.scalar(select(func.max(Task.position)).where(Task.column_id == col.id))
    task = Task(
        project_id=project_id,
        column_id=col.id,
        number=number,
        title=data.title,
        description=data.description,
        priority=data.priority,
        due_date=data.due_date,
        position=(max_pos or 0.0) + POSITION_STEP,
        created_by=user.id,
        completed_at=_now() if col.is_done else None,
    )
    session.add(task)
    await session.flush()
    if data.assignee_ids:
        await session.execute(insert(task_assignees), [{"task_id": task.id, "user_id": u} for u in data.assignee_ids])
    if data.label_ids:
        await session.execute(insert(task_labels), [{"task_id": task.id, "label_id": lab} for lab in data.label_ids])
    snap = await task_snapshot(session, task.id)
    _record(session, access, user, "task.created", task.id, {"task": snap})
    await activity.commit(session, user_brief(user))
    return TaskOut.model_validate(snap)


async def get_task_detail(session: AsyncSession, user: User, task_id: uuid.UUID) -> dict[str, Any]:
    await load_task_access(session, user.id, task_id, Need.READ)
    task = await load_task_full(session, task_id)
    assert task is not None
    base = (await tasks_out(session, [task]))[0].model_dump()
    comments = (
        await session.scalars(
            select(Comment)
            .options(selectinload(Comment.author))
            .where(Comment.task_id == task_id)
            .order_by(Comment.created_at)
        )
    ).all()
    attachments = (
        await session.scalars(
            select(Attachment)
            .options(selectinload(Attachment.uploader))
            .where(Attachment.task_id == task_id)
            .order_by(Attachment.created_at)
        )
    ).all()
    depends_on, blocking = await task_dependency_refs(session, task_id)
    base.update(
        comments=[CommentOut.model_validate(c) for c in comments],
        attachments=attachments,
        depends_on=depends_on,
        blocking=blocking,
    )
    return base


async def task_dependency_refs(session: AsyncSession, task_id: uuid.UUID) -> tuple[list[TaskRef], list[TaskRef]]:
    def refs_query(join_col, filter_col):
        return (
            select(Task.id, Task.number, Task.title, Task.column_id, BoardColumn.is_done)
            .join(TaskDependency, join_col == Task.id)
            .join(BoardColumn, BoardColumn.id == Task.column_id)
            .where(filter_col == task_id)
            .order_by(Task.number)
        )

    dep_rows = (await session.execute(refs_query(TaskDependency.depends_on_id, TaskDependency.task_id))).all()
    blk_rows = (await session.execute(refs_query(TaskDependency.task_id, TaskDependency.depends_on_id))).all()
    mk = lambda r: TaskRef(id=r[0], number=r[1], title=r[2], column_id=r[3], done=r[4])  # noqa: E731
    return [mk(r) for r in dep_rows], [mk(r) for r in blk_rows]


# ---------------------------------------------------------------- update (optimistic concurrency)


async def _conflict(session: AsyncSession, task_id: uuid.UUID) -> VersionConflict:
    await session.rollback()
    activity.discard(session)
    task = await load_task_full(session, task_id)
    if task is None:
        return VersionConflict("This task was deleted by someone else")  # type: ignore[return-value]
    current = (await tasks_out(session, [task]))[0].model_dump(mode="json")
    return VersionConflict(details={"current": current})


async def update_task(session: AsyncSession, user: User, task_id: uuid.UUID, data: TaskUpdate) -> TaskOut:
    project_id, access = await load_task_access(session, user.id, task_id, Need.WRITE)
    task = await load_task_full(session, task_id)
    assert task is not None
    if task.version != data.version:
        raise await _conflict(session, task_id)

    values: dict[str, Any] = {}
    changes: dict[str, Any] = {}
    for field in ("title", "description", "priority"):
        new = getattr(data, field)
        if new is not None and new != getattr(task, field):
            values[field] = new
            old = getattr(task, field)
            changes[field] = {
                "old": old.value if isinstance(old, Priority) else old,
                "new": new.value if isinstance(new, Priority) else new,
            }
    if data.clear_due_date and task.due_date is not None:
        values["due_date"] = None
        changes["due_date"] = {"old": task.due_date.isoformat(), "new": None}
    elif data.due_date is not None and data.due_date != task.due_date:
        values["due_date"] = data.due_date
        changes["due_date"] = {
            "old": task.due_date.isoformat() if task.due_date else None,
            "new": data.due_date.isoformat(),
        }

    assignee_diff = label_diff = None
    if data.assignee_ids is not None:
        current = {u.id for u in task.assignees}
        wanted = set(data.assignee_ids)
        if current != wanted:
            await _validate_assignees(session, access, list(wanted - current))
            assignee_diff = (wanted - current, current - wanted)
            names = {u.id: u.display_name for u in task.assignees}
            if assignee_diff[0]:
                for u in (await session.scalars(select(User).where(User.id.in_(assignee_diff[0])))).all():
                    names[u.id] = u.display_name
            changes["assignees"] = {
                "added": [{"id": str(i), "name": names.get(i)} for i in assignee_diff[0]],
                "removed": [{"id": str(i), "name": names.get(i)} for i in assignee_diff[1]],
            }
    if data.label_ids is not None:
        current = {lab.id for lab in task.labels}
        wanted = set(data.label_ids)
        if current != wanted:
            await _validate_labels(session, project_id, list(wanted - current))
            label_diff = (wanted - current, current - wanted)
            changes["labels"] = {"added": [str(i) for i in label_diff[0]], "removed": [str(i) for i in label_diff[1]]}

    if not changes:
        return (await tasks_out(session, [task]))[0]

    res = await session.execute(
        update(Task)
        .where(Task.id == task_id, Task.version == data.version)
        .values(**values, version=Task.version + 1, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        # A concurrent transaction committed first; nothing has been written by us.
        raise await _conflict(session, task_id)
    if assignee_diff:
        added, removed = assignee_diff
        if removed:
            await session.execute(
                delete(task_assignees).where(task_assignees.c.task_id == task_id, task_assignees.c.user_id.in_(removed))
            )
        if added:
            await session.execute(insert(task_assignees), [{"task_id": task_id, "user_id": u} for u in added])
    if label_diff:
        added, removed = label_diff
        if removed:
            await session.execute(
                delete(task_labels).where(task_labels.c.task_id == task_id, task_labels.c.label_id.in_(removed))
            )
        if added:
            await session.execute(insert(task_labels), [{"task_id": task_id, "label_id": lab} for lab in added])
    snap = await task_snapshot(session, task_id)
    only_assignees = set(changes) == {"assignees"}
    _record(
        session,
        access,
        user,
        "task.assigned" if only_assignees else "task.updated",
        task_id,
        {"task": snap, "changes": changes},
    )
    await activity.commit(session, user_brief(user))
    return TaskOut.model_validate(snap)


# ---------------------------------------------------------------- move


async def move_task(session: AsyncSession, user: User, task_id: uuid.UUID, data: TaskMove) -> TaskOut:
    project_id, access = await load_task_access(session, user.id, task_id, Need.WRITE)
    task = await session.get(Task, task_id, populate_existing=True)
    assert task is not None
    if task.version != data.version:
        raise await _conflict(session, task_id)
    target = await _column(session, project_id, data.column_id)
    source = await session.get(BoardColumn, task.column_id)
    assert source is not None
    if target.id != task.column_id and target.wip_limit is not None:
        count = await session.scalar(select(func.count()).where(Task.column_id == target.id))
        if (count or 0) >= target.wip_limit:
            raise Conflict(f"Column '{target.name}' has reached its WIP limit of {target.wip_limit}")

    async def neighbour_positions() -> tuple[float | None, float | None]:
        others = and_(Task.column_id == target.id, Task.id != task_id)
        if data.after_id is not None:
            prev = await session.scalar(select(Task.position).where(others, Task.id == data.after_id))
            if prev is None:
                raise ValidationFailed("after_id must be a task in the target column")
            nxt = await session.scalar(select(func.min(Task.position)).where(others, Task.position > prev))
            return prev, nxt
        if data.before_id is not None:
            nxt = await session.scalar(select(Task.position).where(others, Task.id == data.before_id))
            if nxt is None:
                raise ValidationFailed("before_id must be a task in the target column")
            prev = await session.scalar(select(func.max(Task.position)).where(others, Task.position < nxt))
            return prev, nxt
        last = await session.scalar(select(func.max(Task.position)).where(others))
        return last, None

    prev, nxt = await neighbour_positions()
    position = position_between(prev, nxt)
    if position is None:
        # Gap exhausted: renumber the target column (positions only; versions unchanged).
        ids = (
            await session.scalars(
                select(Task.id).where(Task.column_id == target.id, Task.id != task_id).order_by(Task.position, Task.id)
            )
        ).all()
        for tid, pos in zip(ids, rebalanced(len(ids)), strict=True):
            await session.execute(
                update(Task).where(Task.id == tid).values(position=pos).execution_options(synchronize_session=False)
            )
        _record(session, access, user, "column.rebalanced", None, {"column_id": str(target.id)})
        prev, nxt = await neighbour_positions()
        position = position_between(prev, nxt)
        assert position is not None

    values: dict[str, Any] = {"column_id": target.id, "position": position}
    if target.is_done and not source.is_done:
        values["completed_at"] = func.now()
    elif not target.is_done and source.is_done:
        values["completed_at"] = None
    res = await session.execute(
        update(Task)
        .where(Task.id == task_id, Task.version == data.version)
        .values(**values, version=Task.version + 1, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise await _conflict(session, task_id)
    snap = await task_snapshot(session, task_id)
    _record(
        session,
        access,
        user,
        "task.moved",
        task_id,
        {
            "task": snap,
            "from_column": {"id": str(source.id), "name": source.name},
            "to_column": {"id": str(target.id), "name": target.name},
        },
    )
    await activity.commit(session, user_brief(user))
    return TaskOut.model_validate(snap)


# ---------------------------------------------------------------- delete


async def delete_task(session: AsyncSession, user: User, task_id: uuid.UUID) -> None:
    """Deletes a task, its dependency edges (both directions), comments and attachments
    atomically. Its activity history is retained (task_id set NULL; payload keeps a
    snapshot) so the project timeline stays truthful."""
    _, access = await load_task_access(session, user.id, task_id, Need.WRITE)
    task = await session.get(Task, task_id)
    assert task is not None
    keys = list((await session.scalars(select(Attachment.storage_key).where(Attachment.task_id == task_id))).all())
    dependents = list(
        (await session.scalars(select(TaskDependency.task_id).where(TaskDependency.depends_on_id == task_id))).all()
    )
    info = {"id": str(task.id), "number": task.number, "title": task.title}
    await session.execute(delete(Task).where(Task.id == task_id))
    _record(
        session,
        access,
        user,
        "task.deleted",
        None,
        {"task": info, "unblocked_candidates": [str(d) for d in dependents]},
    )
    delete_files_later(session, keys)
    await activity.commit(session, user_brief(user))


# ---------------------------------------------------------------- listing / search


SortField = Literal["created_at", "updated_at", "due_date", "priority", "number", "title", "position"]

_PRIORITY_RANK = case({"none": 0, "low": 1, "medium": 2, "high": 3, "urgent": 4}, value=Task.priority, else_=0)


def _sort_expr(field: SortField):
    return {
        "created_at": Task.created_at,
        "updated_at": Task.updated_at,
        "due_date": func.coalesce(Task.due_date, date(9999, 12, 31)),
        "priority": _PRIORITY_RANK,
        "number": Task.number,
        "title": func.lower(Task.title),
        "position": Task.position,
    }[field]


def _encode_cursor(value: Any, id_: uuid.UUID) -> str:
    if isinstance(value, datetime | date):
        value = value.isoformat()
    raw = json.dumps([value, str(id_)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, field: SortField) -> tuple[Any, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value, id_ = json.loads(raw)
        if field in ("created_at", "updated_at"):
            value = datetime.fromisoformat(value)
        elif field == "due_date":
            value = date.fromisoformat(value)
        elif field in ("priority", "number"):
            value = int(value)
        elif field == "position":
            value = float(value)
        elif not isinstance(value, str):
            raise ValueError
        return value, uuid.UUID(id_)
    except Exception:
        raise ValidationFailed("Invalid cursor") from None


_TASK_REF = re.compile(r"^(?:[A-Za-z][A-Za-z0-9]{1,9}-|#)?(\d{1,9})$")


def apply_filters(
    stmt: Select,
    *,
    q: str | None = None,
    assignee_ids: list[uuid.UUID] | None = None,
    unassigned: bool = False,
    label_ids: list[uuid.UUID] | None = None,
    priorities: list[Priority] | None = None,
    column_ids: list[uuid.UUID] | None = None,
    status: Literal["open", "done"] | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    overdue: bool = False,
    dependency_state: Literal["blocked", "ready"] | None = None,
) -> Select:
    if q:
        q = q.strip()[:200]
        conds = [Task.search_vector.op("@@")(func.websearch_to_tsquery("simple", q))]
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(Task.title.ilike(f"%{escaped}%", escape="\\"))
        if m := _TASK_REF.match(q):
            conds.append(Task.number == int(m.group(1)))
        stmt = stmt.where(or_(*conds))
    if assignee_ids:
        stmt = stmt.where(
            exists().where(task_assignees.c.task_id == Task.id, task_assignees.c.user_id.in_(assignee_ids))
        )
    if unassigned:
        stmt = stmt.where(~exists().where(task_assignees.c.task_id == Task.id))
    if label_ids:
        stmt = stmt.where(exists().where(task_labels.c.task_id == Task.id, task_labels.c.label_id.in_(label_ids)))
    if priorities:
        stmt = stmt.where(Task.priority.in_(priorities))
    if column_ids:
        stmt = stmt.where(Task.column_id.in_(column_ids))
    if status == "done":
        stmt = stmt.where(Task.completed_at.is_not(None))
    elif status == "open":
        stmt = stmt.where(Task.completed_at.is_(None))
    if due_before:
        stmt = stmt.where(Task.due_date <= due_before)
    if due_after:
        stmt = stmt.where(Task.due_date >= due_after)
    if overdue:
        stmt = stmt.where(Task.completed_at.is_(None), Task.due_date < func.current_date())
    if dependency_state:
        dep_task = aliased(Task)
        open_dep = exists().where(
            TaskDependency.task_id == Task.id,
            dep_task.id == TaskDependency.depends_on_id,
            dep_task.completed_at.is_(None),
        )
        stmt = stmt.where(Task.completed_at.is_(None))
        stmt = stmt.where(open_dep if dependency_state == "blocked" else ~open_dep)
    return stmt


async def list_tasks(
    session: AsyncSession,
    user: User,
    *,
    project_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    sort: SortField = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    cursor: str | None = None,
    include_total: bool = False,
    **filters: Any,
) -> tuple[list[TaskOut], str | None, int | None]:
    stmt = task_query()
    if project_id is not None:
        await load_project(session, user.id, project_id)
        stmt = stmt.where(Task.project_id == project_id)
    elif org_id is not None:
        await require_org_role(session, org_id, user.id)
        stmt = stmt.join(Project, Project.id == Task.project_id).where(
            Project.org_id == org_id, visible_projects_clause(user.id)
        )
    else:  # pragma: no cover
        raise ValueError("project_id or org_id required")
    stmt = apply_filters(stmt, **filters)
    total = None
    if include_total:
        count_stmt = stmt.with_only_columns(func.count(Task.id)).order_by(None)
        count_stmt = count_stmt.options()  # strip loader options
        total = int(await session.scalar(count_stmt) or 0)
    expr = _sort_expr(sort)
    if cursor:
        value, cid = _decode_cursor(cursor, sort)
        cmp = (
            tuple_(expr, Task.id) > tuple_(value, cid)
            if direction == "asc"
            else tuple_(expr, Task.id) < tuple_(value, cid)
        )
        stmt = stmt.where(cmp)
    order = (expr.asc(), Task.id.asc()) if direction == "asc" else (expr.desc(), Task.id.desc())
    rows = list((await session.scalars(stmt.order_by(*order).limit(limit + 1))).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        value = {
            "due_date": last.due_date or date(9999, 12, 31),
            "priority": Priority(last.priority).rank,
            "title": last.title.lower(),
        }.get(sort, getattr(last, sort, None))
        next_cursor = _encode_cursor(value, last.id)
    return await tasks_out(session, rows), next_cursor, total


# ---------------------------------------------------------------- comments


async def add_comment(session: AsyncSession, user: User, task_id: uuid.UUID, body: str) -> CommentOut:
    _, access = await load_task_access(session, user.id, task_id, Need.WRITE)
    comment = Comment(task_id=task_id, author_id=user.id, body=body)
    session.add(comment)
    await session.flush()
    out = CommentOut(
        id=comment.id,
        task_id=task_id,
        author=user_brief(user),
        body=body,
        created_at=comment.created_at,
        edited_at=None,
    )
    title = await session.scalar(select(Task.title).where(Task.id == task_id))
    _record(
        session, access, user, "comment.created", task_id, {"comment": out.model_dump(mode="json"), "task_title": title}
    )
    await activity.commit(session, user_brief(user))
    return out


async def _load_comment(session: AsyncSession, user: User, comment_id: uuid.UUID) -> tuple[Comment, ProjectAccess]:
    comment = await session.get(Comment, comment_id)
    if comment is None:
        raise NotFound("Comment not found")
    try:
        _, access = await load_task_access(session, user.id, comment.task_id, Need.WRITE)
    except NotFound:
        raise NotFound("Comment not found") from None
    return comment, access


async def edit_comment(session: AsyncSession, user: User, comment_id: uuid.UUID, body: str) -> CommentOut:
    comment, access = await _load_comment(session, user, comment_id)
    if comment.author_id != user.id:
        raise Forbidden("Only the author can edit a comment")
    comment.body = body
    comment.edited_at = _now()
    await session.flush()
    out = CommentOut(
        id=comment.id,
        task_id=comment.task_id,
        author=user_brief(user),
        body=body,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
    )
    _record(session, access, user, "comment.updated", comment.task_id, {"comment": out.model_dump(mode="json")})
    await activity.commit(session, user_brief(user))
    return out


async def delete_comment(session: AsyncSession, user: User, comment_id: uuid.UUID) -> None:
    comment, access = await _load_comment(session, user, comment_id)
    if comment.author_id != user.id and not access.can_admin:
        raise Forbidden("Only the author or an admin can delete a comment")
    task_id = comment.task_id
    await session.delete(comment)
    _record(session, access, user, "comment.deleted", task_id, {"comment_id": str(comment_id), "task_id": str(task_id)})
    await activity.commit(session, user_brief(user))


# ---------------------------------------------------------------- activity


async def list_activity(
    session: AsyncSession,
    user: User,
    *,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    before: int | None = None,
    after: int | None = None,
    limit: int = 50,
) -> list[tuple[ActivityEvent, User | None]]:
    stmt = select(ActivityEvent).options(selectinload(ActivityEvent.actor))
    if task_id is not None:
        await load_task_access(session, user.id, task_id)
        stmt = stmt.where(ActivityEvent.task_id == task_id)
    elif project_id is not None:
        await load_project(session, user.id, project_id)
        stmt = stmt.where(ActivityEvent.project_id == project_id)
    elif org_id is not None:
        role = await require_org_role(session, org_id, user.id)
        stmt = stmt.where(ActivityEvent.org_id == org_id)
        visible = select(Project.id).where(Project.org_id == org_id, visible_projects_clause(user.id))
        if role.at_least(Role.ADMIN):
            stmt = stmt.where(or_(ActivityEvent.project_id.is_(None), ActivityEvent.project_id.in_(visible)))
        else:
            stmt = stmt.where(ActivityEvent.project_id.in_(visible))
    if before is not None:
        stmt = stmt.where(ActivityEvent.id < before)
    if after is not None:
        stmt = stmt.where(ActivityEvent.id > after).order_by(ActivityEvent.id.asc())
    else:
        stmt = stmt.order_by(ActivityEvent.id.desc())
    events = (await session.scalars(stmt.limit(limit))).all()
    return [(e, e.actor) for e in events]
