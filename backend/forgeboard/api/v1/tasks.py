from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from forgeboard.deps import Auth, Session
from forgeboard.schemas.task import (
    ActivityOut,
    AttachmentOut,
    CommentCreate,
    CommentOut,
    DependencyCreate,
    TaskDependenciesOut,
    TaskDetailOut,
    TaskMove,
    TaskOut,
    TaskUpdate,
)
from forgeboard.services import attachments as att_svc
from forgeboard.services import dependencies as dep_svc
from forgeboard.services import tasks as svc
from forgeboard.services.serializers import activity_out, user_brief

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
async def get_task(task_id: uuid.UUID, auth: Auth, session: Session) -> TaskDetailOut:
    return TaskDetailOut.model_validate(await svc.get_task_detail(session, auth.user, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: uuid.UUID, body: TaskUpdate, auth: Auth, session: Session) -> TaskOut:
    return await svc.update_task(session, auth.user, task_id, body)


@router.post("/tasks/{task_id}/move", response_model=TaskOut)
async def move_task(task_id: uuid.UUID, body: TaskMove, auth: Auth, session: Session) -> TaskOut:
    return await svc.move_task(session, auth.user, task_id, body)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.delete_task(session, auth.user, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks/{task_id}/history", response_model=list[ActivityOut])
async def task_history(
    task_id: uuid.UUID,
    auth: Auth,
    session: Session,
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ActivityOut]:
    return activity_out(await svc.list_activity(session, auth.user, task_id=task_id, before=before, limit=limit))


# -------------------------------------------------------------- comments


@router.post("/tasks/{task_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(task_id: uuid.UUID, body: CommentCreate, auth: Auth, session: Session) -> CommentOut:
    return await svc.add_comment(session, auth.user, task_id, body.body)


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def edit_comment(comment_id: uuid.UUID, body: CommentCreate, auth: Auth, session: Session) -> CommentOut:
    return await svc.edit_comment(session, auth.user, comment_id, body.body)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.delete_comment(session, auth.user, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------- attachments


@router.post("/tasks/{task_id}/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    task_id: uuid.UUID, auth: Auth, session: Session, file: Annotated[UploadFile, File()]
) -> AttachmentOut:
    att = await att_svc.store_upload(session, auth.user, task_id, file)
    return AttachmentOut(
        id=att.id,
        task_id=att.task_id,
        filename=att.filename,
        content_type=att.content_type,
        size_bytes=att.size_bytes,
        sha256=att.sha256,
        created_at=att.created_at,
        uploader=user_brief(auth.user),
    )


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: uuid.UUID, auth: Auth, session: Session) -> FileResponse:
    att, path = await att_svc.get_for_download(session, auth.user, attachment_id)
    ascii_name = att.filename.encode("ascii", "replace").decode().replace('"', "").replace("?", "_")
    return FileResponse(
        path,
        media_type=att.content_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(att.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(attachment_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await att_svc.delete_attachment(session, auth.user, attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------- dependencies


@router.get("/tasks/{task_id}/dependencies", response_model=TaskDependenciesOut)
async def get_dependencies(task_id: uuid.UUID, auth: Auth, session: Session) -> TaskDependenciesOut:
    from forgeboard.authz import load_task_access

    await load_task_access(session, auth.user_id, task_id)
    depends_on, blocking = await svc.task_dependency_refs(session, task_id)
    return TaskDependenciesOut(depends_on=depends_on, blocking=blocking, blocked=any(not d.done for d in depends_on))


@router.post("/tasks/{task_id}/dependencies", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def add_dependency(task_id: uuid.UUID, body: DependencyCreate, auth: Auth, session: Session) -> TaskOut:
    return await dep_svc.add_dependency(session, auth.user, task_id, body.depends_on_id)


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", response_model=TaskOut)
async def remove_dependency(task_id: uuid.UUID, depends_on_id: uuid.UUID, auth: Auth, session: Session) -> TaskOut:
    return await dep_svc.remove_dependency(session, auth.user, task_id, depends_on_id)
