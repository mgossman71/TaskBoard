"""SQLAlchemy ORM models. Importing this package registers every table on Base.metadata."""

from taskboard.models.activity import ActivityEvent
from taskboard.models.auth import AuthSession, PasswordResetToken, RefreshToken
from taskboard.models.org import Invitation, Membership, Organization, Role
from taskboard.models.project import BoardColumn, Label, Project, ProjectMember, ProjectStatus
from taskboard.models.task import (
    Attachment,
    Comment,
    Priority,
    Task,
    TaskDependency,
    task_assignees,
    task_labels,
)
from taskboard.models.user import User

__all__ = [
    "ActivityEvent",
    "Attachment",
    "AuthSession",
    "BoardColumn",
    "Comment",
    "Invitation",
    "Label",
    "Membership",
    "Organization",
    "PasswordResetToken",
    "Priority",
    "Project",
    "ProjectMember",
    "ProjectStatus",
    "RefreshToken",
    "Role",
    "Task",
    "TaskDependency",
    "User",
    "task_assignees",
    "task_labels",
]
