"""Projects, project membership, board columns and labels."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forgeboard.authz import Need, ProjectAccess, load_project, require_org_role, visible_projects_clause
from forgeboard.errors import Conflict, NotFound, ValidationFailed, VersionConflict
from forgeboard.models import (
    ActivityEvent,
    Attachment,
    BoardColumn,
    Label,
    Membership,
    Project,
    ProjectMember,
    ProjectStatus,
    Role,
    Task,
    User,
    task_assignees,
)
from forgeboard.realtime import bus
from forgeboard.schemas.project import (
    ColumnCreate,
    ColumnUpdate,
    LabelCreate,
    LabelUpdate,
    ProjectCreate,
    ProjectUpdate,
)
from forgeboard.services import activity
from forgeboard.services.attachments import delete_files_later
from forgeboard.services.serializers import user_brief

DEFAULT_COLUMNS = [("To Do", False), ("In Progress", False), ("In Review", False), ("Done", True)]
POSITION_STEP = 1024.0


def _now() -> datetime:
    return datetime.now(UTC)


def project_payload(p: Project) -> dict:
    from forgeboard.schemas.project import ProjectOut

    return ProjectOut.model_validate(p).model_dump(mode="json")


async def _validate_org_users(session: AsyncSession, org_id: uuid.UUID, user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return []
    found = set(
        (
            await session.scalars(
                select(Membership.user_id).where(Membership.org_id == org_id, Membership.user_id.in_(ids))
            )
        ).all()
    )
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise ValidationFailed("Some users are not members of this organization", details={"user_ids": missing})
    return ids


async def create_project(session: AsyncSession, user: User, org_id: uuid.UUID, data: ProjectCreate) -> Project:
    await require_org_role(session, org_id, user.id, Role.MEMBER)
    member_ids = await _validate_org_users(session, org_id, [user.id, *data.member_ids])
    project = Project(org_id=org_id, name=data.name, key=data.key, description=data.description, created_by=user.id)
    session.add(project)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict(f"A project with key {data.key} already exists in this organization") from None
    for i, (name, done) in enumerate(DEFAULT_COLUMNS):
        session.add(BoardColumn(project_id=project.id, name=name, position=(i + 1) * POSITION_STEP, is_done=done))
    for uid in member_ids:
        session.add(ProjectMember(project_id=project.id, user_id=uid, added_by=user.id))
    activity.record(
        session,
        org_id=org_id,
        project_id=project.id,
        actor_id=user.id,
        type="project.created",
        payload={"project": project_payload(project)},
    )
    await activity.commit(session, user_brief(user))
    await session.refresh(project)
    return project


async def list_projects(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID, status: ProjectStatus | None
) -> list[tuple[Project, int, int, int]]:
    await require_org_role(session, org_id, user_id)
    task_counts = (
        select(
            Task.project_id.label("pid"),
            func.count(Task.id).label("total"),
            func.count(Task.id).filter(BoardColumn.is_done.is_(True)).label("done"),
        )
        .join(BoardColumn, BoardColumn.id == Task.column_id)
        .group_by(Task.project_id)
        .subquery()
    )
    member_counts = (
        select(ProjectMember.project_id.label("pid"), func.count().label("members"))
        .group_by(ProjectMember.project_id)
        .subquery()
    )
    stmt = (
        select(
            Project,
            func.coalesce(task_counts.c.total, 0),
            func.coalesce(task_counts.c.done, 0),
            func.coalesce(member_counts.c.members, 0),
        )
        .outerjoin(task_counts, task_counts.c.pid == Project.id)
        .outerjoin(member_counts, member_counts.c.pid == Project.id)
        .where(Project.org_id == org_id, visible_projects_clause(user_id))
        .order_by(Project.name)
    )
    if status is not None:
        stmt = stmt.where(Project.status == status)
    return [(p, t, d, m) for p, t, d, m in (await session.execute(stmt)).all()]


async def update_project(session: AsyncSession, user: User, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
    access = await load_project(session, user.id, project_id, Need.ADMIN, for_update=True)
    p = access.project
    if p.version != data.version:
        raise VersionConflict(details={"current": project_payload(p)})
    changes = {}
    for field in ("name", "description"):
        val = getattr(data, field)
        if val is not None and val != getattr(p, field):
            changes[field] = {"old": getattr(p, field), "new": val}
            setattr(p, field, val)
    if changes:
        p.version += 1
        p.updated_at = _now()
        await session.flush()
        activity.record(
            session,
            org_id=p.org_id,
            project_id=p.id,
            actor_id=user.id,
            type="project.updated",
            payload={"changes": changes, "project": project_payload(p)},
        )
    await activity.commit(session, user_brief(user))
    return p


async def set_archived(session: AsyncSession, user: User, project_id: uuid.UUID, archived: bool) -> Project:
    access = await load_project(session, user.id, project_id, Need.ADMIN, for_update=True, allow_archived=True)
    p = access.project
    target = ProjectStatus.ARCHIVED if archived else ProjectStatus.ACTIVE
    if p.status != target:
        p.status = target
        p.archived_at = _now() if archived else None
        p.version += 1
        p.updated_at = _now()
        await session.flush()
        activity.record(
            session,
            org_id=p.org_id,
            project_id=p.id,
            actor_id=user.id,
            type="project.archived" if archived else "project.unarchived",
            payload={"project": project_payload(p)},
        )
    await activity.commit(session, user_brief(user))
    return p


async def delete_project(session: AsyncSession, user: User, project_id: uuid.UUID) -> None:
    """Retention policy: hard delete in a single transaction. Tasks, columns, labels,
    dependencies, comments, attachment rows and the project's activity history are
    removed via ON DELETE CASCADE; a `project.deleted` audit event (with a name
    snapshot) is kept at organization level. Attachment files are unlinked only
    after the transaction commits."""
    access = await load_project(session, user.id, project_id, Need.ADMIN, for_update=True, allow_archived=True)
    p = access.project
    keys = list((await session.scalars(select(Attachment.storage_key).where(Attachment.project_id == p.id))).all())
    counts = (await session.execute(select(func.count(Task.id)).where(Task.project_id == p.id))).scalar_one()
    snapshot = {"id": str(p.id), "name": p.name, "key": p.key, "task_count": counts, "attachment_count": len(keys)}
    await session.execute(delete(Project).where(Project.id == p.id))
    activity.record(session, org_id=p.org_id, actor_id=user.id, type="project.deleted", payload={"project": snapshot})
    # Also notify anyone currently viewing the project.
    activity.queue_control(session, bus.project_channel(p.id), {"kind": "project_deleted", "project_id": str(p.id)})
    delete_files_later(session, keys)
    await activity.commit(session, user_brief(user))


# ---------------------------------------------------------------- members


async def project_users(session: AsyncSession, project: Project) -> list[User]:
    """Users with access to the project: explicit members + org owners/admins."""
    stmt = (
        select(User)
        .join(Membership, and_(Membership.user_id == User.id, Membership.org_id == project.org_id))
        .outerjoin(ProjectMember, and_(ProjectMember.user_id == User.id, ProjectMember.project_id == project.id))
        .where(or_(ProjectMember.user_id.is_not(None), Membership.role.in_([Role.OWNER, Role.ADMIN])))
        .order_by(User.display_name)
    )
    return list((await session.scalars(stmt)).all())


async def list_members(session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID) -> list[tuple[User, datetime]]:
    access = await load_project(session, user_id, project_id)
    rows = await session.execute(
        select(User, ProjectMember.added_at)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == access.project.id)
        .order_by(User.display_name)
    )
    return [(u, a) for u, a in rows.all()]


async def add_members(session: AsyncSession, user: User, project_id: uuid.UUID, user_ids: list[uuid.UUID]) -> None:
    access = await load_project(session, user.id, project_id, Need.ADMIN)
    p = access.project
    ids = await _validate_org_users(session, p.org_id, user_ids)
    existing = set((await session.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == p.id))).all())
    new = [i for i in ids if i not in existing]
    for uid in new:
        session.add(ProjectMember(project_id=p.id, user_id=uid, added_by=user.id))
    if new:
        activity.record(
            session,
            org_id=p.org_id,
            project_id=p.id,
            actor_id=user.id,
            type="project.members_added",
            payload={"user_ids": [str(i) for i in new]},
        )
    await activity.commit(session, user_brief(user))


async def remove_member(session: AsyncSession, user: User, project_id: uuid.UUID, target: uuid.UUID) -> None:
    """Removes a project member and (atomically) unassigns them from the project's tasks."""
    access = await load_project(session, user.id, project_id, Need.ADMIN)
    p = access.project
    res = await session.execute(
        delete(ProjectMember).where(ProjectMember.project_id == p.id, ProjectMember.user_id == target)
    )
    if res.rowcount == 0:
        raise NotFound("Member not found")
    target_role = await session.scalar(
        select(Membership.role).where(Membership.org_id == p.org_id, Membership.user_id == target)
    )
    if target_role not in (Role.OWNER, Role.ADMIN):
        affected = (
            await session.scalars(
                select(task_assignees.c.task_id)
                .join(Task, Task.id == task_assignees.c.task_id)
                .where(Task.project_id == p.id, task_assignees.c.user_id == target)
            )
        ).all()
        if affected:
            await session.execute(
                delete(task_assignees).where(task_assignees.c.user_id == target, task_assignees.c.task_id.in_(affected))
            )
            await session.execute(
                update(Task).where(Task.id.in_(affected)).values(version=Task.version + 1, updated_at=_now())
            )
    activity.record(
        session,
        org_id=p.org_id,
        project_id=p.id,
        actor_id=user.id,
        type="project.member_removed",
        payload={"user_id": str(target)},
    )
    activity.queue_control(session, bus.user_channel(target), {"kind": "access_changed", "project_id": str(p.id)})
    await activity.commit(session, user_brief(user))


# ---------------------------------------------------------------- columns


async def list_columns(session: AsyncSession, project_id: uuid.UUID) -> list[BoardColumn]:
    return list(
        (
            await session.scalars(
                select(BoardColumn).where(BoardColumn.project_id == project_id).order_by(BoardColumn.position)
            )
        ).all()
    )


def _column_payload(c: BoardColumn) -> dict:
    from forgeboard.schemas.project import ColumnOut

    return ColumnOut.model_validate(c).model_dump(mode="json")


async def _lock_columns(session: AsyncSession, access: ProjectAccess) -> list[BoardColumn]:
    return list(
        (
            await session.scalars(
                select(BoardColumn)
                .where(BoardColumn.project_id == access.project.id)
                .order_by(BoardColumn.position)
                .with_for_update()
            )
        ).all()
    )


async def create_column(session: AsyncSession, user: User, project_id: uuid.UUID, data: ColumnCreate) -> BoardColumn:
    access = await load_project(session, user.id, project_id, Need.ADMIN)
    cols = await _lock_columns(session, access)
    if len(cols) >= 20:
        raise ValidationFailed("A board can have at most 20 columns")
    if data.after_id is None:
        position = (cols[-1].position + POSITION_STEP) if cols else POSITION_STEP
    else:
        idx = next((i for i, c in enumerate(cols) if c.id == data.after_id), None)
        if idx is None:
            raise ValidationFailed("after_id does not belong to this board")
        nxt = cols[idx + 1].position if idx + 1 < len(cols) else cols[idx].position + 2 * POSITION_STEP
        position = (cols[idx].position + nxt) / 2
    col = BoardColumn(
        project_id=access.project.id, name=data.name, position=position, wip_limit=data.wip_limit, is_done=data.is_done
    )
    session.add(col)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict("A column with this name already exists") from None
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        actor_id=user.id,
        type="column.created",
        payload={"column": _column_payload(col)},
    )
    await activity.commit(session, user_brief(user))
    return col


async def update_column(
    session: AsyncSession, user: User, project_id: uuid.UUID, column_id: uuid.UUID, data: ColumnUpdate
) -> BoardColumn:
    access = await load_project(session, user.id, project_id, Need.ADMIN)
    col = await session.scalar(
        select(BoardColumn).where(BoardColumn.id == column_id, BoardColumn.project_id == access.project.id)
    )
    if col is None:
        raise NotFound("Column not found")
    old_done = col.is_done
    if data.name is not None:
        col.name = data.name
    if data.clear_wip_limit:
        col.wip_limit = None
    elif data.wip_limit is not None:
        col.wip_limit = data.wip_limit
    if data.is_done is not None:
        col.is_done = data.is_done
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict("A column with this name already exists") from None
    if old_done != col.is_done:
        # Keep completed_at consistent with the column's "done" semantics.
        await session.execute(
            update(Task)
            .where(Task.column_id == col.id)
            .values(completed_at=_now() if col.is_done else None, version=Task.version + 1)
        )
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        actor_id=user.id,
        type="column.updated",
        payload={"column": _column_payload(col), "done_changed": old_done != col.is_done},
    )
    await activity.commit(session, user_brief(user))
    return col


async def reorder_columns(
    session: AsyncSession, user: User, project_id: uuid.UUID, column_ids: list[uuid.UUID]
) -> list[BoardColumn]:
    access = await load_project(session, user.id, project_id, Need.ADMIN)
    cols = await _lock_columns(session, access)
    if sorted(map(str, column_ids)) != sorted(str(c.id) for c in cols) or len(set(column_ids)) != len(column_ids):
        raise ValidationFailed("column_ids must list every column of the board exactly once")
    by_id = {c.id: c for c in cols}
    for i, cid in enumerate(column_ids):
        by_id[cid].position = (i + 1) * POSITION_STEP
    await session.flush()
    ordered = [by_id[c] for c in column_ids]
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        actor_id=user.id,
        type="column.reordered",
        payload={"columns": [_column_payload(c) for c in ordered]},
    )
    await activity.commit(session, user_brief(user))
    return ordered


async def delete_column(
    session: AsyncSession, user: User, project_id: uuid.UUID, column_id: uuid.UUID, move_to: uuid.UUID | None
) -> None:
    """Deletes a column, atomically moving its tasks to `move_to` (required if non-empty)."""
    access = await load_project(session, user.id, project_id, Need.ADMIN)
    cols = await _lock_columns(session, access)
    by_id = {c.id: c for c in cols}
    col = by_id.get(column_id)
    if col is None:
        raise NotFound("Column not found")
    if len(cols) <= 1:
        raise Conflict("A board must have at least one column")
    count = await session.scalar(select(func.count()).where(Task.column_id == column_id))
    moved = 0
    if count:
        if move_to is None or move_to not in by_id or move_to == column_id:
            raise ValidationFailed("This column contains tasks; choose another column to move them to")
        target = by_id[move_to]
        base = await session.scalar(
            select(func.coalesce(func.max(Task.position), 0.0)).where(Task.column_id == move_to)
        )
        rows = (await session.scalars(select(Task).where(Task.column_id == column_id).order_by(Task.position))).all()
        for i, t in enumerate(rows):
            t.column_id = move_to
            t.position = float(base) + (i + 1) * POSITION_STEP
            t.version += 1
            if target.is_done and t.completed_at is None:
                t.completed_at = _now()
            elif not target.is_done:
                t.completed_at = None
        moved = len(rows)
        await session.flush()
    await session.delete(col)
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        actor_id=user.id,
        type="column.deleted",
        payload={
            "column_id": str(column_id),
            "name": col.name,
            "moved_to": str(move_to) if move_to else None,
            "moved": moved,
        },
    )
    await activity.commit(session, user_brief(user))


# ---------------------------------------------------------------- labels


async def list_labels(session: AsyncSession, project_id: uuid.UUID) -> list[Label]:
    return list((await session.scalars(select(Label).where(Label.project_id == project_id).order_by(Label.name))).all())


async def create_label(session: AsyncSession, user: User, project_id: uuid.UUID, data: LabelCreate) -> Label:
    access = await load_project(session, user.id, project_id, Need.WRITE)
    label = Label(project_id=access.project.id, name=data.name, color=data.color.lower())
    session.add(label)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict("A label with this name already exists") from None
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        actor_id=user.id,
        type="label.created",
        payload={"label": {"id": str(label.id), "name": label.name, "color": label.color}},
    )
    await activity.commit(session, user_brief(user))
    return label


async def update_label(
    session: AsyncSession, user: User, project_id: uuid.UUID, label_id: uuid.UUID, data: LabelUpdate
) -> Label:
    access = await load_project(session, user.id, project_id, Need.WRITE)
    label = await session.scalar(select(Label).where(Label.id == label_id, Label.project_id == access.project.id))
    if label is None:
        raise NotFound("Label not found")
    if data.name is not None:
        label.name = data.name
    if data.color is not None:
        label.color = data.color.lower()
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict("A label with this name already exists") from None
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        actor_id=user.id,
        type="label.updated",
        payload={"label": {"id": str(label.id), "name": label.name, "color": label.color}},
    )
    await activity.commit(session, user_brief(user))
    return label


async def delete_label(session: AsyncSession, user: User, project_id: uuid.UUID, label_id: uuid.UUID) -> None:
    access = await load_project(session, user.id, project_id, Need.WRITE)
    res = await session.execute(delete(Label).where(Label.id == label_id, Label.project_id == access.project.id))
    if res.rowcount == 0:
        raise NotFound("Label not found")
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        actor_id=user.id,
        type="label.deleted",
        payload={"label_id": str(label_id)},
    )
    await activity.commit(session, user_brief(user))


async def last_event_id(session: AsyncSession, project_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.max(ActivityEvent.id), 0)).where(ActivityEvent.project_id == project_id)
        )
        or 0
    )
