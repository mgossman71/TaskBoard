from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from taskboard.models.org import Role
from taskboard.schemas.auth import UserBrief
from taskboard.schemas.common import CleanStr, ORMModel

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")]


class OrgCreate(BaseModel):
    name: Annotated[CleanStr, StringConstraints(max_length=100)]
    slug: Slug | None = None


class OrgUpdate(BaseModel):
    name: Annotated[CleanStr, StringConstraints(max_length=100)]


class OrgOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrgWithRole(OrgOut):
    role: Role


class MemberOut(BaseModel):
    user: UserBrief
    role: Role
    created_at: datetime


class MemberRoleUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: EmailStr = Field(max_length=254)
    role: Role = Role.MEMBER


class InvitationOut(ORMModel):
    id: uuid.UUID
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InvitationCreated(InvitationOut):
    # Returned once, so admins can share the link even without SMTP configured.
    invite_url: str


class InvitationPreview(BaseModel):
    org_name: str
    email: str
    role: Role
    expires_at: datetime


class AcceptInvitation(BaseModel):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
