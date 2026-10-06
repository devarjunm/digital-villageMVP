"""Authentication endpoints (see docs/api.md → Auth)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.auth.dependencies import CurrentUser, DbSession, client_metadata, current_session_id
from app.auth.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    PublicUser,
    RefreshRequest,
    RegisterRequest,
    SessionInfo,
    TokenPair,
)
from app.auth.service import AuthService
from app.core.ratelimit import enforce_rate_limit

router = APIRouter()

# Client metadata (ip / user agent / device label) as a dependency alias.
ClientMeta = Annotated[dict, Depends(client_metadata)]


@router.post(
    "/register",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account (phone-first or email+password)",
)
def register(payload: RegisterRequest, db: DbSession, request: Request, meta: ClientMeta) -> dict:
    enforce_rate_limit(request, "auth_register")
    service = AuthService(db)
    user, conflict, otp_result = service.register(
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        password=payload.password,
        preferred_language=payload.preferred_language,
        request_ip=meta.get("ip_address"),
    )
    if conflict:
        return {
            "status": "conflict",
            "field": conflict.field,
            "message": conflict.message,
            "requires_login": True,
        }
    assert user is not None
    response: dict = {
        "user": service.to_public_user(user).model_dump(),
        "otp_required": otp_result is not None,
        "status": "pending_verification" if otp_result else "active",
    }
    if otp_result is not None:
        response["otp"] = {
            "provider": otp_result.provider,
            "is_demo_provider": otp_result.provider == "console",
            "dev_otp": otp_result.dev_code,
            "message": "Verify the code to finish creating your account.",
        }
    return response


@router.post("/otp/request", response_model=OTPRequestResponse, summary="Request a one-time code")
def request_otp(
    payload: OTPRequest, db: DbSession, request: Request, meta: ClientMeta
) -> OTPRequestResponse:
    enforce_rate_limit(request, "auth_otp")
    result = AuthService(db).request_otp(
        identifier=payload.identifier,
        purpose=payload.purpose,
        request_ip=meta.get("ip_address"),
        channel=payload.channel,
    )
    result.pop("identifier_exists", None)  # never leak account existence
    if not result.get("dev_otp"):
        result.pop("detail", None)
    return OTPRequestResponse(**result)


@router.post("/otp/verify", response_model=AuthResponse, summary="Verify a code, returning tokens")
def verify_otp(
    payload: OTPVerifyRequest, db: DbSession, request: Request, meta: ClientMeta
) -> AuthResponse:
    enforce_rate_limit(request, "auth_login")
    service = AuthService(db)
    user, tokens, _session_id = service.verify_otp(
        identifier=payload.identifier,
        code=payload.code,
        purpose=payload.purpose,
        full_name=payload.full_name,
        preferred_language=payload.preferred_language,
        ip_address=meta.get("ip_address"),
        user_agent=meta.get("user_agent"),
        device_label=meta.get("device_label"),
    )
    return AuthResponse(user=service.to_public_user(user), tokens=tokens)


@router.post("/login", response_model=AuthResponse, summary="Password login")
def login(payload: LoginRequest, db: DbSession, request: Request, meta: ClientMeta) -> AuthResponse:
    enforce_rate_limit(request, "auth_login")
    service = AuthService(db)
    user, tokens, _session_id = service.login_with_password(
        identifier=payload.identifier,
        password=payload.password,
        ip_address=meta.get("ip_address"),
        user_agent=meta.get("user_agent"),
        device_label=meta.get("device_label"),
    )
    return AuthResponse(user=service.to_public_user(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
def refresh(
    payload: RefreshRequest, db: DbSession, request: Request, meta: ClientMeta
) -> TokenPair:
    enforce_rate_limit(request, "auth_refresh")
    _user, tokens, _session_id = AuthService(db).refresh(
        raw_refresh_token=payload.refresh_token,
        ip_address=meta.get("ip_address"),
        user_agent=meta.get("user_agent"),
    )
    return tokens


@router.post("/logout", summary="End the current session (or all sessions)")
def logout(
    payload: LogoutRequest, db: DbSession, user: CurrentUser, request: Request
) -> dict[str, object]:
    revoked = AuthService(db).logout(
        user=user, raw_refresh_token=payload.refresh_token, all_sessions=payload.all_sessions
    )
    return {"status": "logged_out", "revoked_sessions": revoked}


@router.get("/me", response_model=PublicUser, summary="Current account")
def me(user: CurrentUser, db: DbSession) -> PublicUser:
    return AuthService(db).to_public_user(user)


@router.get("/sessions", response_model=list[SessionInfo], summary="Active sessions")
def sessions(
    user: CurrentUser,
    db: DbSession,
    session_id: Annotated[uuid.UUID | None, Depends(current_session_id)] = None,
) -> list[SessionInfo]:
    rows = AuthService(db).list_sessions(user, current_session_id=session_id)
    return [SessionInfo(**row) for row in rows]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke a session",
)
def revoke_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    AuthService(db).revoke_session(user, session_id)


@router.post("/password/change", summary="Change password (revokes other sessions)")
def change_password(
    payload: ChangePasswordRequest, user: CurrentUser, db: DbSession
) -> dict[str, str]:
    AuthService(db).change_password(
        user, current_password=payload.current_password, new_password=payload.new_password
    )
    return {"status": "password_changed", "message": "All other sessions were signed out."}


@router.post(
    "/password/reset/request",
    response_model=OTPRequestResponse,
    summary="Start account recovery",
)
def request_password_reset(
    payload: PasswordResetRequest, db: DbSession, request: Request, meta: ClientMeta
) -> OTPRequestResponse:
    enforce_rate_limit(request, "auth_otp")
    result = AuthService(db).request_password_reset(
        identifier=payload.identifier, request_ip=meta.get("ip_address")
    )
    result.setdefault("message", "If the account exists, a reset code has been sent.")
    result.setdefault("expires_in_seconds", 300)
    result.setdefault("provider", "none")
    result.setdefault("is_demo_provider", False)
    result.setdefault("channel", "sms" if "@" not in payload.identifier else "email")
    return OTPRequestResponse(**result)


@router.post("/password/reset/confirm", summary="Finish account recovery")
def confirm_password_reset(
    payload: PasswordResetConfirm, db: DbSession, request: Request, meta: ClientMeta
) -> dict[str, str]:
    enforce_rate_limit(request, "auth_login")
    AuthService(db).confirm_password_reset(
        identifier=payload.identifier,
        code=payload.code,
        new_password=payload.new_password,
        ip_address=meta.get("ip_address"),
    )
    return {"status": "password_reset", "message": "Password updated. Please sign in."}
