from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from forgeboard.deps import Auth, Session
from forgeboard.schemas.auth import UserBrief
from forgeboard.schemas.org import (
    AcceptInvitation,
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
    InvitationPreview,
    MemberOut,
    MemberRoleUpdate,
    OrgCreate,
    OrgOut,
    OrgUpdate,
    OrgWithRole,
)
from forgeboard.services import orgs as svc

router = APIRouter(tags=["organizations"])


@router.get("/orgs", response_model=list[OrgWithRole])
async def list_orgs(auth: Auth, session: Session) -> list[OrgWithRole]:
    return [
        OrgWithRole(**OrgOut.model_validate(o).model_dump(), role=r)
        for o, r in await svc.list_user_orgs(session, auth.user_id)
    ]


@router.post("/orgs", response_model=OrgWithRole, status_code=status.HTTP_201_CREATED)
async def create_org(body: OrgCreate, auth: Auth, session: Session) -> OrgWithRole:
    org = await svc.create_org(session, auth.user, body.name, body.slug)
    return OrgWithRole(**OrgOut.model_validate(org).model_dump(), role="owner")


@router.get("/orgs/{org_id}", response_model=OrgWithRole)
async def get_org(org_id: uuid.UUID, auth: Auth, session: Session) -> OrgWithRole:
    org, role = await svc.get_org(session, auth.user_id, org_id)
    return OrgWithRole(**OrgOut.model_validate(org).model_dump(), role=role)


@router.patch("/orgs/{org_id}", response_model=OrgOut)
async def update_org(org_id: uuid.UUID, body: OrgUpdate, auth: Auth, session: Session) -> OrgOut:
    return OrgOut.model_validate(await svc.update_org(session, auth.user, org_id, body.name))


@router.delete("/orgs/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(org_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.delete_org(session, auth.user, org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/orgs/{org_id}/members", response_model=list[MemberOut])
async def list_members(org_id: uuid.UUID, auth: Auth, session: Session) -> list[MemberOut]:
    return [
        MemberOut(user=UserBrief.model_validate(u), role=m.role, created_at=m.created_at)
        for u, m in await svc.list_members(session, auth.user_id, org_id)
    ]


@router.patch("/orgs/{org_id}/members/{user_id}", response_model=MemberOut)
async def change_role(
    org_id: uuid.UUID, user_id: uuid.UUID, body: MemberRoleUpdate, auth: Auth, session: Session
) -> MemberOut:
    m = await svc.change_role(session, auth.user, org_id, user_id, body.role)
    from forgeboard.models import User

    u = await session.get(User, m.user_id)
    return MemberOut(user=UserBrief.model_validate(u), role=m.role, created_at=m.created_at)


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(org_id: uuid.UUID, user_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.remove_member(session, auth.user, org_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/orgs/{org_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(org_id: uuid.UUID, auth: Auth, session: Session) -> list[InvitationOut]:
    return [InvitationOut.model_validate(i) for i in await svc.list_invitations(session, auth.user_id, org_id)]


@router.post("/orgs/{org_id}/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    org_id: uuid.UUID, body: InvitationCreate, auth: Auth, session: Session
) -> InvitationCreated:
    inv, url = await svc.create_invitation(session, auth.user, org_id, str(body.email), body.role)
    return InvitationCreated(**InvitationOut.model_validate(inv).model_dump(), invite_url=url)


@router.delete("/orgs/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(org_id: uuid.UUID, invitation_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await svc.revoke_invitation(session, auth.user, org_id, invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invitations/preview", response_model=InvitationPreview)
async def preview_invitation(token: str, session: Session) -> InvitationPreview:
    inv, org = await svc.preview_invitation(session, token[:200])
    return InvitationPreview(org_name=org.name, email=inv.email, role=inv.role, expires_at=inv.expires_at)


@router.post("/invitations/accept", response_model=OrgOut)
async def accept_invitation(body: AcceptInvitation, auth: Auth, session: Session) -> OrgOut:
    return OrgOut.model_validate(await svc.accept_invitation(session, auth.user, body.token))
