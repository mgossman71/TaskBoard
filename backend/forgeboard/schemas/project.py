from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from forgeboard.models.org import Role
from forgeboard.models.project import ProjectStatus
from forgeboard.schemas.auth import UserBrief
from forgeboard.schemas.common import CleanStr, CleanText, ORMModel
from forgeboard.schemas.task import TaskCardOut

ProjectKey = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9]{1,9}$")]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class ProjectCreate(BaseModel):
    name: Annotated[CleanStr, StringConstraints(max_length=120)]
    key: ProjectKey
    description: Annotated[CleanText, StringConstraints(max_length=5000)] = ""
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class ProjectUpdate(BaseModel):
    version: int
    name: Annotated[CleanStr, StringConstraints(max_length=120)] | None = None
    description: Annotated[CleanText, StringConstraints(max_length=5000)] | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    key: str
    description: str
    status: ProjectStatus
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ProjectSummary(ProjectOut):
    task_count: int = 0
    done_count: int = 0
    member_count: int = 0


class ProjectMemberOut(BaseModel):
    user: UserBrief
    added_at: datetime


class ProjectMembersSet(BaseModel):
    user_ids: list[uuid.UUID] = Field(max_length=500)


class ColumnCreate(BaseModel):
    name: Annotated[CleanStr, StringConstraints(max_length=60)]
    wip_limit: int | None = Field(default=None, ge=1, le=1000)
    is_done: bool = False
    after_id: uuid.UUID | None = None


class ColumnUpdate(BaseModel):
    name: Annotated[CleanStr, StringConstraints(max_length=60)] | None = None
    wip_limit: int | None = Field(default=None, ge=1, le=1000)
    clear_wip_limit: bool = False
    is_done: bool | None = None


class ColumnReorder(BaseModel):
    column_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class ColumnOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    position: float
    wip_limit: int | None
    is_done: bool


class LabelCreate(BaseModel):
    name: Annotated[CleanStr, StringConstraints(max_length=40)]
    color: Color


class LabelUpdate(BaseModel):
    name: Annotated[CleanStr, StringConstraints(max_length=40)] | None = None
    color: Color | None = None


class LabelOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    color: str


class BoardOut(BaseModel):
    project: ProjectOut
    columns: list[ColumnOut]
    labels: list[LabelOut]
    members: list[UserBrief]
    tasks: list[TaskCardOut]
    last_event_id: int
    can_edit: bool
    role: Role
