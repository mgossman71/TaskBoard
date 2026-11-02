from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from taskboard.authz import load_project
from taskboard.deps import Auth, Session
from taskboard.models import Priority, ProjectStatus, Task
from taskboard.schemas.auth import UserBrief
from taskboard.schemas.common import Page
from taskboard.schemas.project import (
    BoardOut,
    ColumnCreate,
    ColumnOut,
    ColumnReorder,
    ColumnUpdate,
    LabelCreate,
    LabelOut,
    LabelUpdate,
    ProjectCreate,
    ProjectMemberOut,
    ProjectMembersSet,
    ProjectOut,
    ProjectSummary,
    ProjectUpdate,
)
from taskboard.schemas.task import ActivityOut, DependencyGraphOut, TaskCardOut, TaskCreate, TaskOut
from taskboard.services import dashboard as dashboard_svc
from taskboard.services import dependencies as dep_svc
from taskboard.services import projects as svc
from taskboard.services import tasks as task_svc
from taskboard.services.serializers import activity_out, task_query, tasks_out

router = APIRouter(tags=["projects"])


@router.get("/orgs/{org_id}/projects", response_model=list[ProjectSummary])
async def list_projects(
    org_id: uuid.UUID,
    auth: Auth,
    session: Session,
    status_: Annotated[ProjectStatus | None, Query(alias="status")] = None,
) -> list[ProjectSummary]:
    rows = await svc.list_projects(session, auth.user_id, org_id, status_)
    return [
        ProjectSummary(**ProjectOut.model_validate(p).model_dump(), task_count=t, done_count=d, member_count=m)
        for p, t, d, m in rows
    ]


@router.post("/orgs/{org_id}/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(org_id: uuid.UUID, body: ProjectCreate, auth: Auth, session: Session) -> ProjectOut:
    return ProjectOut.model_validate(await svc.create_project(session, auth.user, org_id, body))


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, auth: Auth, session: Session) -> ProjectOut:
    return ProjectOut.model_validate((await load_project(session, auth.user_id, project_id)).project)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: uuid.UUID, body: ProjectUpdate, auth: Auth, session: Session) -> ProjectOut:
    return ProjectOut.model_validate(await svc.update_project(session, auth.user, project_id, body))


@router.post("/projects/{project_id}/archive", response_model=ProjectOut)
async def archive_project(project_id: uuid.UUID, auth: Auth, session: Session) -> ProjectOut:
    return ProjectOut.model_validate(await svc.set_archived(session, auth.user, project_id, True))


@router.post("/projects/{project_id}/unarchive", response_model=ProjectOut)
async def unarchive_project(project_id: uuid.UUID, auth: Auth, session: Session) -> ProjectOut:
    return ProjectOut.model_validate(await svc.set_archived(session, auth.user, project_id, False))


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.delete_project(session, auth.user, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/board", response_model=BoardOut)
async def board(project_id: uuid.UUID, auth: Auth, session: Session) -> BoardOut:
    access = await load_project(session, auth.user_id, project_id)
    last_id = await svc.last_event_id(session, project_id)  # read first: events after this are replayed
    columns = await svc.list_columns(session, project_id)
    labels = await svc.list_labels(session, project_id)
    members = await svc.project_users(session, access.project)
    tasks = list(
        (await session.scalars(task_query().where(Task.project_id == project_id).order_by(Task.position))).all()
    )
    return BoardOut(
        project=ProjectOut.model_validate(access.project),
        columns=[ColumnOut.model_validate(c) for c in columns],
        labels=[LabelOut.model_validate(lab) for lab in labels],
        members=[UserBrief.model_validate(u) for u in members],
        tasks=await tasks_out(session, tasks, TaskCardOut),
        last_event_id=last_id,
        can_edit=access.can_write,
        role=access.role,
    )


# -------------------------------------------------------------- members


@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberOut])
async def project_members(project_id: uuid.UUID, auth: Auth, session: Session) -> list[ProjectMemberOut]:
    return [
        ProjectMemberOut(user=UserBrief.model_validate(u), added_at=a)
        for u, a in await svc.list_members(session, auth.user_id, project_id)
    ]


@router.post("/projects/{project_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def add_project_members(project_id: uuid.UUID, body: ProjectMembersSet, auth: Auth, session: Session) -> Response:
    await svc.add_members(session, auth.user, project_id, body.user_ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/projects/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(project_id: uuid.UUID, user_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.remove_member(session, auth.user, project_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------- columns


@router.get("/projects/{project_id}/columns", response_model=list[ColumnOut])
async def list_columns(project_id: uuid.UUID, auth: Auth, session: Session) -> list[ColumnOut]:
    await load_project(session, auth.user_id, project_id)
    return [ColumnOut.model_validate(c) for c in await svc.list_columns(session, project_id)]


@router.post("/projects/{project_id}/columns", response_model=ColumnOut, status_code=status.HTTP_201_CREATED)
async def create_column(project_id: uuid.UUID, body: ColumnCreate, auth: Auth, session: Session) -> ColumnOut:
    return ColumnOut.model_validate(await svc.create_column(session, auth.user, project_id, body))


@router.put("/projects/{project_id}/columns/order", response_model=list[ColumnOut])
async def reorder_columns(project_id: uuid.UUID, body: ColumnReorder, auth: Auth, session: Session) -> list[ColumnOut]:
    return [
        ColumnOut.model_validate(c) for c in await svc.reorder_columns(session, auth.user, project_id, body.column_ids)
    ]


@router.patch("/projects/{project_id}/columns/{column_id}", response_model=ColumnOut)
async def update_column(
    project_id: uuid.UUID, column_id: uuid.UUID, body: ColumnUpdate, auth: Auth, session: Session
) -> ColumnOut:
    return ColumnOut.model_validate(await svc.update_column(session, auth.user, project_id, column_id, body))


@router.delete("/projects/{project_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_column(
    project_id: uuid.UUID, column_id: uuid.UUID, auth: Auth, session: Session, move_to: uuid.UUID | None = None
) -> Response:
    await svc.delete_column(session, auth.user, project_id, column_id, move_to)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------- labels


@router.get("/projects/{project_id}/labels", response_model=list[LabelOut])
async def list_labels(project_id: uuid.UUID, auth: Auth, session: Session) -> list[LabelOut]:
    await load_project(session, auth.user_id, project_id)
    return [LabelOut.model_validate(lab) for lab in await svc.list_labels(session, project_id)]


@router.post("/projects/{project_id}/labels", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
async def create_label(project_id: uuid.UUID, body: LabelCreate, auth: Auth, session: Session) -> LabelOut:
    return LabelOut.model_validate(await svc.create_label(session, auth.user, project_id, body))


@router.patch("/projects/{project_id}/labels/{label_id}", response_model=LabelOut)
async def update_label(
    project_id: uuid.UUID, label_id: uuid.UUID, body: LabelUpdate, auth: Auth, session: Session
) -> LabelOut:
    return LabelOut.model_validate(await svc.update_label(session, auth.user, project_id, label_id, body))


@router.delete("/projects/{project_id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(project_id: uuid.UUID, label_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.delete_label(session, auth.user, project_id, label_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------- tasks (collection)

SortParam = Literal["created_at", "updated_at", "due_date", "priority", "number", "title", "position"]


def _filters(
    q: str | None,
    assignee: list[uuid.UUID] | None,
    unassigned: bool,
    label: list[uuid.UUID] | None,
    priority: list[Priority] | None,
    column: list[uuid.UUID] | None,
    status_: Literal["open", "done"] | None,
    due_before: date | None,
    due_after: date | None,
    overdue: bool,
    dependency_state: Literal["blocked", "ready"] | None,
) -> dict:
    return dict(
        q=q,
        assignee_ids=assignee,
        unassigned=unassigned,
        label_ids=label,
        priorities=priority,
        column_ids=column,
        status=status_,
        due_before=due_before,
        due_after=due_after,
        overdue=overdue,
        dependency_state=dependency_state,
    )


@router.get("/projects/{project_id}/tasks", response_model=Page[TaskOut])
async def list_project_tasks(
    project_id: uuid.UUID,
    auth: Auth,
    session: Session,
    q: Annotated[str | None, Query(max_length=200)] = None,
    assignee: Annotated[list[uuid.UUID] | None, Query()] = None,
    unassigned: bool = False,
    label: Annotated[list[uuid.UUID] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    column: Annotated[list[uuid.UUID] | None, Query()] = None,
    status_: Annotated[Literal["open", "done"] | None, Query(alias="status")] = None,
    due_before: date | None = None,
    due_after: date | None = None,
    overdue: bool = False,
    dependency_state: Literal["blocked", "ready"] | None = None,
    sort: SortParam = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    include_total: bool = False,
) -> Page[TaskOut]:
    items, nxt, total = await task_svc.list_tasks(
        session,
        auth.user,
        project_id=project_id,
        sort=sort,
        direction=direction,
        limit=limit,
        cursor=cursor,
        include_total=include_total,
        **_filters(
            q, assignee, unassigned, label, priority, column, status_, due_before, due_after, overdue, dependency_state
        ),
    )
    return Page(items=items, next_cursor=nxt, total=total)


@router.get("/orgs/{org_id}/tasks", response_model=Page[TaskOut])
async def list_org_tasks(
    org_id: uuid.UUID,
    auth: Auth,
    session: Session,
    q: Annotated[str | None, Query(max_length=200)] = None,
    assignee: Annotated[list[uuid.UUID] | None, Query()] = None,
    unassigned: bool = False,
    label: Annotated[list[uuid.UUID] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    status_: Annotated[Literal["open", "done"] | None, Query(alias="status")] = None,
    due_before: date | None = None,
    due_after: date | None = None,
    overdue: bool = False,
    dependency_state: Literal["blocked", "ready"] | None = None,
    sort: SortParam = "updated_at",
    direction: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    include_total: bool = False,
) -> Page[TaskOut]:
    items, nxt, total = await task_svc.list_tasks(
        session,
        auth.user,
        org_id=org_id,
        sort=sort,
        direction=direction,
        limit=limit,
        cursor=cursor,
        include_total=include_total,
        **_filters(
            q, assignee, unassigned, label, priority, None, status_, due_before, due_after, overdue, dependency_state
        ),
    )
    return Page(items=items, next_cursor=nxt, total=total)


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(project_id: uuid.UUID, body: TaskCreate, auth: Auth, session: Session) -> TaskOut:
    return await task_svc.create_task(session, auth.user, project_id, body)


# -------------------------------------------------------------- activity / graph / dashboard


@router.get("/projects/{project_id}/activity", response_model=list[ActivityOut])
async def project_activity(
    project_id: uuid.UUID,
    auth: Auth,
    session: Session,
    before: int | None = None,
    after: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityOut]:
    return activity_out(
        await task_svc.list_activity(session, auth.user, project_id=project_id, before=before, after=after, limit=limit)
    )


@router.get("/orgs/{org_id}/activity", response_model=list[ActivityOut])
async def org_activity(
    org_id: uuid.UUID,
    auth: Auth,
    session: Session,
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityOut]:
    return activity_out(await task_svc.list_activity(session, auth.user, org_id=org_id, before=before, limit=limit))


@router.get("/projects/{project_id}/dependency-graph", response_model=DependencyGraphOut)
async def dependency_graph(
    project_id: uuid.UUID, auth: Auth, session: Session, include_done: bool = True
) -> DependencyGraphOut:
    return await dep_svc.dependency_graph(session, auth.user, project_id, include_done)


@router.get("/orgs/{org_id}/dashboard")
async def org_dashboard(
    org_id: uuid.UUID,
    auth: Auth,
    session: Session,
    project_id: uuid.UUID | None = None,
    days: Annotated[int, Query(ge=7, le=180)] = 30,
) -> dict:
    return await dashboard_svc.summary(session, auth.user, org_id, project_id, days)
