"""Organizations, memberships and invitations."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from taskboard.authz import require_org_role
from taskboard.config import get_settings
from taskboard.errors import Conflict, Forbidden, NotFound, ValidationFailed
from taskboard.models import (
    Attachment,
    Invitation,
    Membership,
    Organization,
    Project,
    ProjectMember,
    Role,
    Task,
    User,
    task_assignees,
)
from taskboard.realtime import bus
from taskboard.security.tokens import hash_token, new_opaque_token
from taskboard.services import activity
from taskboard.services.attachments import delete_files_later
from taskboard.services.email import send_email


def _now() -> datetime:
    return datetime.now(UTC)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "org"
    return f"{base}-{secrets.token_hex(3)}"


async def create_org(session: AsyncSession, user: User, name: str, slug: str | None) -> Organization:
    org = Organization(name=name, slug=slug or _slugify(name))
    session.add(org)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict("This organization slug is already taken") from None
    session.add(Membership(org_id=org.id, user_id=user.id, role=Role.OWNER))
    activity.record(session, org_id=org.id, actor_id=user.id, type="org.created", payload={"name": org.name})
    await activity.commit(session)
    return org


async def list_user_orgs(session: AsyncSession, user_id: uuid.UUID) -> list[tuple[Organization, Role]]:
    rows = await session.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user_id)
        .order_by(Organization.name)
    )
    return [(o, r) for o, r in rows.all()]


async def get_org(session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> tuple[Organization, Role]:
    role = await require_org_role(session, org_id, user_id)
    org = await session.get(Organization, org_id)
    assert org is not None
    return org, role


async def update_org(session: AsyncSession, user: User, org_id: uuid.UUID, name: str) -> Organization:
    await require_org_role(session, org_id, user.id, Role.ADMIN)
    org = await session.get(Organization, org_id)
    assert org is not None
    old = org.name
    org.name = name
    activity.record(
        session, org_id=org_id, actor_id=user.id, type="org.updated", payload={"name": {"old": old, "new": name}}
    )
    await activity.commit(session)
    return org


async def delete_org(session: AsyncSession, user: User, org_id: uuid.UUID) -> None:
    """Owner only. Hard-deletes the organization and everything in it in one transaction;
    attachment files are removed from disk after the commit succeeds."""
    await require_org_role(session, org_id, user.id, Role.OWNER)
    keys = (
        await session.scalars(
            select(Attachment.storage_key)
            .join(Project, Project.id == Attachment.project_id)
            .where(Project.org_id == org_id)
        )
    ).all()
    member_ids = (await session.scalars(select(Membership.user_id).where(Membership.org_id == org_id))).all()
    await session.execute(delete(Organization).where(Organization.id == org_id))
    delete_files_later(session, list(keys))
    for uid in member_ids:
        activity.queue_control(session, bus.user_channel(uid), {"kind": "access_changed", "org_id": str(org_id)})
    await activity.commit(session)


async def list_members(session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> list[tuple[User, Membership]]:
    await require_org_role(session, org_id, user_id)
    rows = await session.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id)
        .order_by(User.display_name)
    )
    return [(u, m) for u, m in rows.all()]


async def _owner_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        await session.scalar(select(func.count()).where(Membership.org_id == org_id, Membership.role == Role.OWNER))
        or 0
    )


async def change_role(
    session: AsyncSession, actor: User, org_id: uuid.UUID, target_user_id: uuid.UUID, new_role: Role
) -> Membership:
    actor_role = await require_org_role(session, org_id, actor.id, Role.ADMIN)
    target = await session.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == target_user_id).with_for_update()
    )
    if target is None:
        raise NotFound("Member not found")
    # Only owners may create owners or modify existing owners.
    if (target.role == Role.OWNER or new_role == Role.OWNER) and actor_role != Role.OWNER:
        raise Forbidden("Only an owner can change owner roles")
    if target.role == Role.OWNER and new_role != Role.OWNER and await _owner_count(session, org_id) <= 1:
        raise Conflict("An organization must keep at least one owner")
    old = target.role
    target.role = new_role
    activity.record(
        session,
        org_id=org_id,
        actor_id=actor.id,
        type="member.role_changed",
        payload={"user_id": str(target_user_id), "old": old.value, "new": new_role.value},
    )
    activity.queue_control(session, bus.user_channel(target_user_id), {"kind": "access_changed", "org_id": str(org_id)})
    await activity.commit(session)
    return target


async def remove_member(session: AsyncSession, actor: User, org_id: uuid.UUID, target_user_id: uuid.UUID) -> None:
    """Atomically removes the membership, all project memberships in this org and
    task assignments in this org."""
    is_self = actor.id == target_user_id
    actor_role = await require_org_role(session, org_id, actor.id, Role.VIEWER if is_self else Role.ADMIN)
    target = await session.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == target_user_id).with_for_update()
    )
    if target is None:
        raise NotFound("Member not found")
    if target.role == Role.OWNER:
        if not is_self and actor_role != Role.OWNER:
            raise Forbidden("Only an owner can remove another owner")
        if await _owner_count(session, org_id) <= 1:
            raise Conflict("An organization must keep at least one owner")
    org_projects = select(Project.id).where(Project.org_id == org_id)
    await session.execute(
        delete(ProjectMember).where(ProjectMember.user_id == target_user_id, ProjectMember.project_id.in_(org_projects))
    )
    await session.execute(
        delete(task_assignees).where(
            task_assignees.c.user_id == target_user_id,
            task_assignees.c.task_id.in_(select(Task.id).where(Task.project_id.in_(org_projects))),
        )
    )
    await session.delete(target)
    activity.record(
        session,
        org_id=org_id,
        actor_id=actor.id,
        type="member.removed" if not is_self else "member.left",
        payload={"user_id": str(target_user_id)},
    )
    activity.queue_control(session, bus.user_channel(target_user_id), {"kind": "access_changed", "org_id": str(org_id)})
    await activity.commit(session)


# ---------------------------------------------------------------- invitations


async def create_invitation(
    session: AsyncSession, actor: User, org_id: uuid.UUID, email: str, role: Role
) -> tuple[Invitation, str]:
    s = get_settings()
    actor_role = await require_org_role(session, org_id, actor.id, Role.ADMIN)
    if role == Role.OWNER and actor_role != Role.OWNER:
        raise Forbidden("Only an owner can invite owners")
    email = email.lower()
    existing_member = await session.scalar(
        select(Membership.user_id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id, User.email == email)
    )
    if existing_member is not None:
        raise Conflict("This user is already a member of the organization")
    now = _now()
    # Re-inviting replaces any pending invitation for the same address.
    await session.execute(
        update(Invitation)
        .where(
            Invitation.org_id == org_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    raw = new_opaque_token()
    inv = Invitation(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=hash_token(raw),
        invited_by=actor.id,
        expires_at=now + timedelta(days=s.invitation_expire_days),
    )
    session.add(inv)
    await session.flush()
    activity.record(
        session,
        org_id=org_id,
        actor_id=actor.id,
        type="invitation.created",
        payload={"email": email, "role": role.value},
    )
    await activity.commit(session)
    org = await session.get(Organization, org_id)
    url = invite_url(raw)
    await send_email(
        email,
        f"You're invited to {org.name if org else 'an organization'} on {s.app_name}",
        f"{actor.display_name} invited you to join {org.name if org else ''} as {role.value}.\n\n"
        f"Accept the invitation: {url}\n\nThis link expires in {s.invitation_expire_days} days.",
    )
    return inv, url


def invite_url(raw: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/invite?token={raw}"


async def list_invitations(session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> list[Invitation]:
    await require_org_role(session, org_id, user_id, Role.ADMIN)
    return list(
        (
            await session.scalars(
                select(Invitation)
                .where(
                    Invitation.org_id == org_id,
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                    Invitation.expires_at > _now(),
                )
                .order_by(Invitation.created_at.desc())
            )
        ).all()
    )


async def revoke_invitation(session: AsyncSession, actor: User, org_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
    await require_org_role(session, org_id, actor.id, Role.ADMIN)
    inv = await session.scalar(select(Invitation).where(Invitation.id == invitation_id, Invitation.org_id == org_id))
    if inv is None or inv.accepted_at is not None or inv.revoked_at is not None:
        raise NotFound("Invitation not found")
    inv.revoked_at = _now()
    activity.record(session, org_id=org_id, actor_id=actor.id, type="invitation.revoked", payload={"email": inv.email})
    await activity.commit(session)


async def _valid_invitation(session: AsyncSession, raw: str, lock: bool = False) -> Invitation:
    stmt = select(Invitation).where(Invitation.token_hash == hash_token(raw))
    if lock:
        stmt = stmt.with_for_update()
    inv = await session.scalar(stmt)
    if inv is None or inv.accepted_at is not None or inv.revoked_at is not None or inv.expires_at <= _now():
        raise NotFound("This invitation is invalid or has expired")
    return inv


async def preview_invitation(session: AsyncSession, raw: str) -> tuple[Invitation, Organization]:
    inv = await _valid_invitation(session, raw)
    org = await session.get(Organization, inv.org_id)
    assert org is not None
    return inv, org


async def accept_invitation(session: AsyncSession, user: User, raw: str) -> Organization:
    inv = await _valid_invitation(session, raw, lock=True)
    if inv.email.lower() != user.email.lower():
        raise Forbidden("This invitation was sent to a different email address")
    existing = await session.scalar(
        select(Membership).where(Membership.org_id == inv.org_id, Membership.user_id == user.id)
    )
    if existing is None:
        session.add(Membership(org_id=inv.org_id, user_id=user.id, role=inv.role))
    inv.accepted_at = _now()
    inv.accepted_by = user.id
    activity.record(
        session,
        org_id=inv.org_id,
        actor_id=user.id,
        type="member.joined",
        payload={"user_id": str(user.id), "role": inv.role.value},
    )
    await activity.commit(session)
    org = await session.get(Organization, inv.org_id)
    assert org is not None
    return org


def validate_role(value: str) -> Role:
    try:
        return Role(value)
    except ValueError:
        raise ValidationFailed("Unknown role") from None
