from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Request, Response, status

from taskboard.config import get_settings
from taskboard.deps import Auth, Session, client_ip
from taskboard.errors import Unauthorized
from taskboard.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    SessionOut,
    TokenResponse,
    UpdateProfileRequest,
    UserOut,
)
from taskboard.security.csrf import CSRF_COOKIE, verify_csrf
from taskboard.services import auth as auth_service
from taskboard.services.auth import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "tb_refresh"
REFRESH_PATH = "/api/v1/auth"


def _set_cookies(response: Response, tokens: IssuedTokens) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        expires=tokens.refresh_expires_at,
        path=REFRESH_PATH,
        httponly=True,
        secure=s.secure_cookies,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(24),
        expires=tokens.refresh_expires_at,
        path="/",
        httponly=False,
        secure=s.secure_cookies,
        samesite="strict",
    )


def _clear_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, secure=s.secure_cookies, httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=s.secure_cookies, samesite="strict")


def _token_response(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_at=tokens.access_expires_at,
        user=UserOut.model_validate(tokens.user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, response: Response, session: Session) -> TokenResponse:
    tokens = await auth_service.register(
        session,
        email=str(body.email),
        password=body.password,
        display_name=body.display_name,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    _set_cookies(response, tokens)
    return _token_response(tokens)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, response: Response, session: Session) -> TokenResponse:
    tokens = await auth_service.login(
        session,
        email=str(body.email),
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    _set_cookies(response, tokens)
    return _token_response(tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, session: Session) -> TokenResponse:
    verify_csrf(request)
    try:
        tokens = await auth_service.refresh(session, request.cookies.get(REFRESH_COOKIE), client_ip(request))
    except Unauthorized:
        _clear_cookies(response)
        raise
    _set_cookies(response, tokens)
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: Session) -> Response:
    """Revokes the session identified by the refresh cookie (or by the bearer token)."""
    verify_csrf(request)
    sid = await auth_service.session_id_from_refresh(session, request.cookies.get(REFRESH_COOKIE))
    user_id = None
    if sid is not None:
        from sqlalchemy import select

        from taskboard.models import AuthSession

        user_id = await session.scalar(select(AuthSession.user_id).where(AuthSession.id == sid))
    if sid is None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            from taskboard.deps import authenticate_token

            try:
                ctx = await authenticate_token(session, header[7:].strip())
                sid, user_id = ctx.session_id, ctx.user_id
            except Unauthorized:
                pass
    if sid is not None and user_id is not None:
        await auth_service.logout(session, sid, user_id)
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(resp)
    return resp


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(auth: Auth, session: Session) -> Response:
    from taskboard.services import activity

    await auth_service.revoke_all_sessions(session, auth.user_id, reason="logout_all")
    await activity.commit(session)
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(resp)
    return resp


@router.get("/me", response_model=UserOut)
async def me(auth: Auth) -> UserOut:
    return UserOut.model_validate(auth.user)


@router.patch("/me", response_model=UserOut)
async def update_me(body: UpdateProfileRequest, auth: Auth, session: Session) -> UserOut:
    # Deliberately not written to the activity log: activity is organization-scoped and a
    # profile belongs to no single organization (and is not a work item).
    user = await session.merge(auth.user)
    user.display_name = body.display_name
    await session.commit()
    return UserOut.model_validate(user)


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(auth: Auth, session: Session) -> list[SessionOut]:
    rows = await auth_service.list_sessions(session, auth.user_id)
    out = []
    for r in rows:
        o = SessionOut.model_validate(r)
        o.current = r.id == auth.session_id
        out.append(o)
    return out


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: uuid.UUID, auth: Auth, session: Session) -> Response:
    await auth_service.revoke_session(session, auth.user_id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: ChangePasswordRequest, auth: Auth, session: Session) -> Response:
    user = await session.merge(auth.user)
    await auth_service.change_password(session, user, auth.session_id, body.current_password, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: PasswordResetRequest, request: Request, session: Session) -> dict:
    await auth_service.request_password_reset(session, str(body.email), client_ip(request))
    return {"detail": "If an account exists for this email, a reset link has been sent."}


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: PasswordResetConfirm, request: Request, session: Session) -> Response:
    await auth_service.confirm_password_reset(session, body.token, body.new_password, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
