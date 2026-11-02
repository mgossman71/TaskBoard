"""FastAPI dependencies: authentication context and request metadata."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forgeboard.db import get_session
from forgeboard.errors import Unauthorized
from forgeboard.models import AuthSession, User
from forgeboard.security.tokens import decode_access_token


@dataclass
class AuthContext:
    user: User
    session_id: uuid.UUID

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


async def authenticate_token(session: AsyncSession, token: str) -> AuthContext:
    claims = decode_access_token(token)
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(User, AuthSession.id)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.id == claims.session_id,
                User.id == claims.user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                User.is_active.is_(True),
            )
        )
    ).first()
    if row is None:
        raise Unauthorized("Session expired or revoked")
    return AuthContext(user=row[0], session_id=row[1])


async def get_auth(request: Request, session: Annotated[AsyncSession, Depends(get_session)]) -> AuthContext:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized(headers={"WWW-Authenticate": "Bearer"})
    ctx = await authenticate_token(session, token.strip())
    request.state.user_id = str(ctx.user_id)
    return ctx


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers resolves X-Forwarded-For from trusted proxies into client.host
    return request.client.host if request.client else "unknown"


Session = Annotated[AsyncSession, Depends(get_session)]
Auth = Annotated[AuthContext, Depends(get_auth)]
