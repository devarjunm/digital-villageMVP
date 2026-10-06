"""Domain errors and the single error envelope returned by the API.

Handlers in app.main translate these into HTTP responses. Internal exception
detail is logged with the request id and never returned to clients.
"""

from __future__ import annotations

from typing import Any

from fastapi import status


class AppError(Exception):
    """Base class for all expected, client-visible failures."""

    code: str = "internal_error"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        self.http_status = http_status or self.http_status
        super().__init__(self.message)


class ValidationError(AppError):
    code = "validation_error"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "The submitted data is invalid."


class AuthError(AppError):
    code = "unauthorized"
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "Authentication required."


class InvalidCredentialsError(AuthError):
    code = "invalid_credentials"
    message = "Invalid credentials."


class OTPError(AuthError):
    code = "otp_invalid"
    message = "That code is not valid."


class OTPExpiredError(OTPError):
    code = "otp_expired"
    message = "That code has expired. Please request a new one."


class OTPTooManyAttemptsError(OTPError):
    code = "otp_attempts_exceeded"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many incorrect attempts. Please request a new code."


class AccountLockedError(AuthError):
    code = "account_locked"
    http_status = status.HTTP_423_LOCKED
    message = "This account is temporarily locked. Try again later."


class AccountDisabledError(AuthError):
    code = "account_disabled"
    http_status = status.HTTP_403_FORBIDDEN
    message = "This account is not active."


class TokenError(AuthError):
    code = "token_invalid"
    message = "The session token is invalid or expired."


class PermissionDeniedError(AppError):
    code = "forbidden"
    http_status = status.HTTP_403_FORBIDDEN
    message = "You do not have permission to do that."


class NotFoundError(AppError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND
    message = "Not found."


def not_found() -> None:
    """Raise the error returned when a row exists but is not the caller's.

    Multi-tenant APIs have a choice for "you asked for a farm that belongs to
    somebody else": 403 (forbidden) or 404 (not found). 403 confirms that the
    requested id exists, which turns any endpoint into an enumeration oracle for
    other people's farms, crops, posts and photos — the exact weakness class
    OWASP API Security calls Broken Object Level Authorization. This project
    therefore answers **404** for every ownership failure and keeps 403 for what
    it actually means: the caller's *role* does not permit the action at all
    (a farmer calling an admin endpoint).

    Raising `NotFoundError` keeps the message identical to a genuinely missing
    row, so the two cases are indistinguishable from outside — which is the
    point. Call sites use this helper instead of hand-writing the error so the
    policy stays in one place.
    """
    raise NotFoundError()


class ConflictError(AppError):
    code = "conflict"
    http_status = status.HTTP_409_CONFLICT
    message = "That action conflicts with the current state."


class RateLimitedError(AppError):
    code = "rate_limited"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many requests. Please slow down."

    def __init__(self, message: str | None = None, *, retry_after: int = 60, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class PayloadTooLargeError(AppError):
    code = "payload_too_large"
    http_status = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    message = "The uploaded file is too large."


class UnsupportedMediaError(AppError):
    code = "unsupported_media_type"
    http_status = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    message = "That file type is not supported."


class ConfigurationError(AppError):
    """Server-side misconfiguration (e.g. a production provider without credentials).

    Surfaces as HTTP 500 with an actionable message. It is never used to signal a
    user error, and it never masks an external call that did not happen.
    """

    code = "configuration_error"
    status_code = 500
    message = "The server is not configured correctly for this feature."

    def __init__(self, message: str | None = None, *, details: dict | None = None) -> None:
        super().__init__(message or self.message, details=details)


class ProviderUnavailableError(AppError):
    """An external dependency (weather, market, SMS, storage) is unavailable."""

    code = "provider_unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "An upstream data provider is currently unavailable."


class ModelUnavailableError(AppError):
    """No usable ML artefact / sufficient data for a model-backed feature.

    Returned instead of guessing, so a missing model is visible to the client
    rather than silently replaced by fabricated output.
    """

    code = "model_unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The model for this feature is not available yet."


class InsufficientEvidenceError(AppError):
    """RAG/agent could not ground an answer in retrieved evidence."""

    code = "insufficient_evidence"
    http_status = status.HTTP_200_OK
    message = "There is not enough indexed evidence to answer this reliably."


def error_envelope(
    *, code: str, message: str, details: dict[str, Any] | None, request_id: str | None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }
