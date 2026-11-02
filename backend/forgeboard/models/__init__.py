"""SQLAlchemy ORM models. Importing this package registers every table on Base.metadata."""

from forgeboard.models.activity import ActivityEvent
from forgeboard.models.auth import AuthSession, PasswordResetToken, RefreshToken
from forgeboard.models.org import Invitation, Membership, Organization, Role
from forgeboard.models.project import BoardColumn, Label, Project, ProjectMember, ProjectStatus
from forgeboard.models.task import (
    Attachment,
    Comment,
    Priority,
    Task,
    TaskDependency,
    task_assignees,
    task_labels,
)
from forgeboard.models.user import User

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
