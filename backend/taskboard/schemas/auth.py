from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator

from taskboard.schemas.common import CleanStr, ORMModel

Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]


def _password_strength(v: str) -> str:
    classes = sum(
        [
            any(c.islower() for c in v),
            any(c.isupper() for c in v),
            any(c.isdigit() for c in v),
            any(not c.isalnum() for c in v),
        ]
    )
    if classes < 3:
        raise ValueError("Password must contain at least three of: lowercase, uppercase, digits, symbols")
    return v


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: Password
    display_name: Annotated[CleanStr, StringConstraints(max_length=100)]

    _pw = field_validator("password")(_password_strength)


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime


class UserBrief(ORMModel):
    id: uuid.UUID
    display_name: str
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class SessionOut(ORMModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_address: str | None
    current: bool = False


class PasswordResetRequest(BaseModel):
    email: EmailStr = Field(max_length=254)


class PasswordResetConfirm(BaseModel):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
    new_password: Password

    _pw = field_validator("new_password")(_password_strength)


class ChangePasswordRequest(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Password

    _pw = field_validator("new_password")(_password_strength)


class UpdateProfileRequest(BaseModel):
    display_name: Annotated[CleanStr, StringConstraints(max_length=100)]
