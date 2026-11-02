"""Server-side authorization. Every resource access goes through these loaders.

Rules
-----
* Organization data is visible only to members of that organization.
* Owner/Admin see every project in the org; Member/Viewer only projects they
  were added to.
* Resources the caller cannot see produce 404 (never revealing existence);
  visible resources the caller may not modify produce 403.
* Archived projects are read-only for everyone (409 until unarchived).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from taskboard.errors import Conflict, Forbidden, NotFound
from taskboard.models import Membership, Project, ProjectMember, ProjectStatus, Role, Task


class Need(StrEnum):
    READ = "read"  # view project contents
    WRITE = "write"  # create/edit tasks, comments, attachments, labels, dependencies
    ADMIN = "admin"  # project settings: columns, members, rename, archive, delete


@dataclass
class ProjectAccess:
    project: Project
    role: Role
    is_project_member: bool

    @property
    def can_write(self) -> bool:
        return self.role.at_least(Role.MEMBER) and self.project.status == ProjectStatus.ACTIVE

    @property
    def can_admin(self) -> bool:
        return self.role.at_least(Role.ADMIN)


async def get_role(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> Role | None:
    return await session.scalar(
        select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )


async def require_org_role(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, minimum: Role = Role.VIEWER
) -> Role:
    role = await get_role(session, org_id, user_id)
    if role is None:
        raise NotFound("Organization not found")
    if not role.at_least(minimum):
        raise Forbidden()
    return role


def visible_projects_clause(user_id: uuid.UUID):
    """SQL predicate (over Project) restricting to projects the user may see."""
    admin_orgs = select(Membership.org_id).where(
        Membership.user_id == user_id, Membership.role.in_([Role.OWNER, Role.ADMIN])
    )
    member_projects = (
        select(ProjectMember.project_id)
        .join(Project, Project.id == ProjectMember.project_id)
        .join(Membership, and_(Membership.org_id == Project.org_id, Membership.user_id == user_id))
        .where(ProjectMember.user_id == user_id)
    )
    return or_(Project.org_id.in_(admin_orgs), Project.id.in_(member_projects))


async def load_project(
    session: AsyncSession,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    need: Need = Need.READ,
    *,
    for_update: bool = False,
    allow_archived: bool = False,
) -> ProjectAccess:
    stmt = (
        select(Project, Membership.role, ProjectMember.user_id)
        .join(Membership, and_(Membership.org_id == Project.org_id, Membership.user_id == user_id))
        .outerjoin(ProjectMember, and_(ProjectMember.project_id == Project.id, ProjectMember.user_id == user_id))
        .where(Project.id == project_id)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Project)
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFound("Project not found")
    project, role, pm_user = row
    access = ProjectAccess(project=project, role=role, is_project_member=pm_user is not None)
    if not (access.can_admin or access.is_project_member):
        raise NotFound("Project not found")
    if need is Need.READ:
        return access
    if need is Need.WRITE and not role.at_least(Role.MEMBER):
        raise Forbidden()
    if need is Need.ADMIN and not access.can_admin:
        raise Forbidden()
    if project.status == ProjectStatus.ARCHIVED and not allow_archived:
        raise Conflict("Project is archived and read-only")
    return access


async def load_task_access(
    session: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID, need: Need = Need.READ
) -> tuple[uuid.UUID, ProjectAccess]:
    project_id = await session.scalar(select(Task.project_id).where(Task.id == task_id))
    if project_id is None:
        raise NotFound("Task not found")
    try:
        access = await load_project(session, user_id, project_id, need)
    except NotFound:
        raise NotFound("Task not found") from None
    return project_id, access
