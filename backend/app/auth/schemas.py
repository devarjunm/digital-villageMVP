"""Authentication request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.config import settings
from app.core.enums import Language, OTPPurpose, Role, UserStatus


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(
        default=None, description="Phone number; +91 assumed for 10-digit Indian numbers"
    )
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    preferred_language: Language = Language.EN
    role_intent: Role = Field(
        default=Role.FARMER,
        description="Requested role. Only FARMER is self-assignable; expert/moderator/admin are granted by an admin.",
    )

    @field_validator("role_intent")
    @classmethod
    def _only_farmer(cls, v: Role) -> Role:
        if v != Role.FARMER:
            raise ValueError("Only the FARMER role can be self-registered.")
        return v


class OTPRequest(BaseModel):
    identifier: str = Field(description="Phone number or email address")
    purpose: OTPPurpose = OTPPurpose.LOGIN
    channel: str | None = Field(
        default=None, description="sms | email (defaults by identifier type)"
    )


class OTPRequestResponse(BaseModel):
    status: str = "sent"
    message: str
    expires_in_seconds: int
    channel: str
    provider: str
    is_demo_provider: bool
    # Present only in non-production with the console provider, so the whole
    # flow is testable without SMS infrastructure.
    dev_otp: str | None = Field(
        default=None,
        description="Development-only echo of the OTP (never present in production).",
    )


class OTPVerifyRequest(BaseModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)
    purpose: OTPPurpose = OTPPurpose.LOGIN
    full_name: str | None = Field(default=None, description="Required when completing registration")
    preferred_language: Language | None = None


class LoginRequest(BaseModel):
    identifier: str
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    identifier: str


class PasswordResetConfirm(BaseModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, description="Log out this session")
    all_sessions: bool = Field(default=False, description="Revoke every active session")


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    access_expires_at: datetime
    refresh_expires_at: datetime


class PublicUser(BaseModel):
    id: uuid.UUID
    full_name: str
    primary_role: Role
    roles: list[str]
    preferred_language: Language
    status: UserStatus
    phone_masked: str | None = None
    email_masked: str | None = None
    phone_verified: bool = False
    email_verified: bool = False
    created_at: datetime
    is_demo: bool = False


class AuthResponse(BaseModel):
    user: PublicUser
    tokens: TokenPair

    model_config = {
        "json_schema_extra": {
            "example": {
                "user": {"id": "…", "full_name": "Demo Farmer", "primary_role": "farmer"},
                "tokens": {"access_token": "…", "refresh_token": "…", "expires_in": 1800},
            }
        }
    }


class SessionInfo(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    device_label: str | None
    ip_address: str | None
    user_agent: str | None
    current: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


def otp_ttl_seconds() -> int:
    return settings.otp_ttl_seconds
