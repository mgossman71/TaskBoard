from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, model_validator

from forgeboard.models.task import Priority
from forgeboard.schemas.auth import UserBrief
from forgeboard.schemas.common import CleanStr, CleanText, ORMModel

Title = Annotated[CleanStr, StringConstraints(max_length=200)]
Description = Annotated[CleanText, StringConstraints(max_length=20000)]


class LabelBrief(ORMModel):
    id: uuid.UUID
    name: str
    color: str


class TaskCardOut(ORMModel):
    """Compact representation for board cards (no description)."""

    id: uuid.UUID
    project_id: uuid.UUID
    column_id: uuid.UUID
    number: int
    title: str
    priority: Priority
    due_date: date | None
    position: float
    version: int
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    assignees: list[UserBrief]
    labels: list[LabelBrief]
    blocked: bool = False
    dependency_ids: list[uuid.UUID] = Field(default_factory=list)


class TaskOut(TaskCardOut):
    description: str


class TaskCreate(BaseModel):
    title: Title
    description: Description = ""
    column_id: uuid.UUID | None = None
    priority: Priority = Priority.NONE
    due_date: date | None = None
    assignee_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    label_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _dedupe(self) -> TaskCreate:
        self.assignee_ids = list(dict.fromkeys(self.assignee_ids))
        self.label_ids = list(dict.fromkeys(self.label_ids))
        return self


class TaskUpdate(BaseModel):
    """Partial update. `version` is mandatory (optimistic concurrency control)."""

    version: int = Field(ge=1)
    title: Title | None = None
    description: Description | None = None
    priority: Priority | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    assignee_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    label_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _check(self) -> TaskUpdate:
        if self.assignee_ids is not None:
            self.assignee_ids = list(dict.fromkeys(self.assignee_ids))
        if self.label_ids is not None:
            self.label_ids = list(dict.fromkeys(self.label_ids))
        if self.clear_due_date and self.due_date is not None:
            raise ValueError("due_date and clear_due_date are mutually exclusive")
        return self


class TaskMove(BaseModel):
    version: int = Field(ge=1)
    column_id: uuid.UUID
    # Place the task directly after `after_id` (None => top of column)
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class CommentCreate(BaseModel):
    body: Annotated[CleanText, StringConstraints(min_length=1, max_length=10000)]


class CommentOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    author: UserBrief | None
    body: str
    created_at: datetime
    edited_at: datetime | None


class AttachmentOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    uploader: UserBrief | None


class DependencyCreate(BaseModel):
    depends_on_id: uuid.UUID


class TaskRef(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    column_id: uuid.UUID
    done: bool


class TaskDependenciesOut(BaseModel):
    depends_on: list[TaskRef]
    blocking: list[TaskRef]
    blocked: bool


class DependencyGraphOut(BaseModel):
    nodes: list[TaskRef]
    edges: list[tuple[uuid.UUID, uuid.UUID]]
    topological_order: list[uuid.UUID]
    blocked: list[uuid.UUID]
    ready: list[uuid.UUID]


class ActivityOut(BaseModel):
    id: int
    type: str
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    actor: UserBrief | None
    payload: dict[str, Any]
    created_at: datetime


class TaskDetailOut(TaskOut):
    comments: list[CommentOut]
    attachments: list[AttachmentOut]
    depends_on: list[TaskRef]
    blocking: list[TaskRef]
