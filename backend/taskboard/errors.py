"""Application error types mapped to consistent JSON error responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str | None = None, *, details: Any = None, headers: dict | None = None):
        super().__init__(message or self.__class__.default_message())
        self.message = message or self.__class__.default_message()
        self.details = details
        self.headers = headers

    @classmethod
    def default_message(cls) -> str:
        return "Bad request"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"

    @classmethod
    def default_message(cls) -> str:
        return "Validation failed"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"

    @classmethod
    def default_message(cls) -> str:
        return "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"

    @classmethod
    def default_message(cls) -> str:
        return "You do not have permission to perform this action"


class NotFound(AppError):
    status_code = 404
    code = "not_found"

    @classmethod
    def default_message(cls) -> str:
        return "Resource not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"

    @classmethod
    def default_message(cls) -> str:
        return "Conflict"


class VersionConflict(Conflict):
    code = "version_conflict"

    @classmethod
    def default_message(cls) -> str:
        return "This item was modified by someone else. Reload to see the latest version."


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"

    @classmethod
    def default_message(cls) -> str:
        return "Too many requests. Please try again later."


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"

    @classmethod
    def default_message(cls) -> str:
        return "Payload too large"


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "unsupported_media_type"

    @classmethod
    def default_message(cls) -> str:
        return "Unsupported file type"
