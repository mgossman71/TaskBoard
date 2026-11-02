"""Authentication: registration, login, refresh-token rotation, sessions, password reset."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forgeboard.config import get_settings
from forgeboard.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from forgeboard.models import AuthSession, PasswordResetToken, RefreshToken, User
from forgeboard.realtime import bus
from forgeboard.security import ratelimit
from forgeboard.security.passwords import hash_password, needs_rehash, verify_password
from forgeboard.security.tokens import create_access_token, hash_token, new_opaque_token
from forgeboard.services import activity
from forgeboard.services.email import send_email

INVALID_CREDENTIALS = "Invalid email or password"


@dataclass
class IssuedTokens:
    user: User
    session_id: uuid.UUID
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


async def _issue_refresh(session: AsyncSession, auth_session: AuthSession) -> tuple[str, datetime]:
    raw = new_opaque_token()
    expires = auth_session.expires_at
    session.add(RefreshToken(session_id=auth_session.id, token_hash=hash_token(raw), expires_at=expires))
    return raw, expires


async def _start_session(session: AsyncSession, user: User, user_agent: str | None, ip: str | None) -> IssuedTokens:
    s = get_settings()
    auth_session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        expires_at=_now() + timedelta(days=s.refresh_token_expire_days),
        user_agent=(user_agent or "")[:255] or None,
        ip_address=ip,
    )
    session.add(auth_session)
    await session.flush()
    raw, exp = await _issue_refresh(session, auth_session)
    access, access_exp = create_access_token(user.id, auth_session.id)
    return IssuedTokens(user, auth_session.id, access, access_exp, raw, exp)


async def register(
    session: AsyncSession, *, email: str, password: str, display_name: str, user_agent: str | None, ip: str
) -> IssuedTokens:
    await ratelimit.enforce_ip_rate(ip, "register", limit=get_settings().register_rate_per_minute)
    user = User(email=email.lower(), display_name=display_name, password_hash=hash_password(password))
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise Conflict("An account with this email already exists") from None
    tokens = await _start_session(session, user, user_agent, ip)
    await session.commit()
    return tokens


async def login(session: AsyncSession, *, email: str, password: str, user_agent: str | None, ip: str) -> IssuedTokens:
    email = email.lower()
    await ratelimit.enforce_ip_rate(ip, "login")
    await ratelimit.check_login_allowed(email, ip)
    user = await session.scalar(select(User).where(User.email == email))
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        await ratelimit.register_login_failure(email, ip)
        raise Unauthorized(INVALID_CREDENTIALS)
    await ratelimit.clear_login_failures(email, ip)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    tokens = await _start_session(session, user, user_agent, ip)
    await session.commit()
    return tokens


async def _revoke_session(session: AsyncSession, session_id: uuid.UUID, reason: str) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )


async def refresh(session: AsyncSession, raw_token: str | None, ip: str) -> IssuedTokens:
    """Rotate a refresh token. Presenting an already-used token is treated as theft:
    the whole session (token family) is revoked."""
    if not raw_token:
        raise Unauthorized("Missing refresh token")
    await ratelimit.enforce_ip_rate(ip, "refresh", limit=120)
    row = (
        await session.execute(
            select(RefreshToken, AuthSession)
            .join(AuthSession, AuthSession.id == RefreshToken.session_id)
            .where(RefreshToken.token_hash == hash_token(raw_token))
            .with_for_update()
        )
    ).first()
    if row is None:
        raise Unauthorized("Invalid refresh token")
    token, auth_session = row
    now = _now()
    if token.used_at is not None:
        await _revoke_session(session, auth_session.id, "refresh_token_reuse")
        activity.queue_control(
            session,
            bus.user_channel(auth_session.user_id),
            {"kind": "session_revoked", "session_id": str(auth_session.id)},
        )
        await activity.commit(session)
        raise Unauthorized("Refresh token reuse detected; session revoked")
    if auth_session.revoked_at is not None or auth_session.expires_at <= now or token.expires_at <= now:
        raise Unauthorized("Session expired or revoked")
    user = await session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Session expired or revoked")
    token.used_at = now
    auth_session.last_used_at = now
    auth_session.ip_address = ip
    raw, exp = await _issue_refresh(session, auth_session)
    access, access_exp = create_access_token(user.id, auth_session.id)
    await session.commit()
    return IssuedTokens(user, auth_session.id, access, access_exp, raw, exp)


async def session_id_from_refresh(session: AsyncSession, raw_token: str | None) -> uuid.UUID | None:
    if not raw_token:
        return None
    return await session.scalar(select(RefreshToken.session_id).where(RefreshToken.token_hash == hash_token(raw_token)))


async def logout(session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await _revoke_session(session, session_id, "logout")
    activity.queue_control(
        session, bus.user_channel(user_id), {"kind": "session_revoked", "session_id": str(session_id)}
    )
    await activity.commit(session)


async def list_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[AuthSession]:
    return list(
        (
            await session.scalars(
                select(AuthSession)
                .where(
                    AuthSession.user_id == user_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > _now(),
                )
                .order_by(AuthSession.last_used_at.desc())
            )
        ).all()
    )


async def revoke_session(session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    owner = await session.scalar(select(AuthSession.user_id).where(AuthSession.id == session_id))
    if owner != user_id:
        raise NotFound("Session not found")
    await logout(session, session_id, user_id)


async def revoke_all_sessions(
    session: AsyncSession, user_id: uuid.UUID, *, except_session: uuid.UUID | None = None, reason: str
) -> None:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    if except_session is not None:
        stmt = stmt.where(AuthSession.id != except_session)
    await session.execute(stmt)
    activity.queue_control(
        session,
        bus.user_channel(user_id),
        {"kind": "sessions_revoked", "except": str(except_session) if except_session else None},
    )


async def request_password_reset(session: AsyncSession, email: str, ip: str) -> None:
    s = get_settings()
    await ratelimit.enforce_ip_rate(ip, "pwreset", limit=s.password_reset_rate_per_minute)
    user = await session.scalar(select(User).where(User.email == email.lower(), User.is_active.is_(True)))
    if user is None:
        return  # Do not reveal whether the account exists.
    now = _now()
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw = new_opaque_token()
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(minutes=s.password_reset_expire_minutes),
        )
    )
    await session.commit()
    link = f"{s.public_base_url.rstrip('/')}/reset-password?token={raw}"
    await send_email(
        user.email,
        f"{s.app_name}: reset your password",
        f"Hello {user.display_name},\n\nUse the link below to choose a new password. "
        f"It expires in {s.password_reset_expire_minutes} minutes and can be used once.\n\n{link}\n\n"
        "If you did not request this, you can ignore this email.",
    )


async def confirm_password_reset(session: AsyncSession, raw_token: str, new_password: str, ip: str) -> None:
    await ratelimit.enforce_ip_rate(ip, "pwreset-confirm", limit=20)
    token = await session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(raw_token)).with_for_update()
    )
    now = _now()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise ValidationFailed("This password reset link is invalid or has expired")
    user = await session.get(User, token.user_id)
    if user is None:
        raise ValidationFailed("This password reset link is invalid or has expired")
    token.used_at = now
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    await revoke_all_sessions(session, user.id, reason="password_reset")
    await activity.commit(session)


async def change_password(
    session: AsyncSession, user: User, current_session: uuid.UUID, current: str, new: str
) -> None:
    if not verify_password(user.password_hash, current):
        raise ValidationFailed("Current password is incorrect")
    user.password_hash = hash_password(new)
    user.password_changed_at = _now()
    await revoke_all_sessions(session, user.id, except_session=current_session, reason="password_changed")
    await activity.commit(session)
