"""FastAPI dependencies for authentication, authorisation and capability checks."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import AuthService
from app.core.context import set_user
from app.core.enums import Role, UserStatus
from app.core.errors import (
    AccountDisabledError,
    AuthError,
    PermissionDeniedError,
    TokenError,
    not_found,
)
from app.core.security import decode_access_token
from app.database.session import get_db
from app.moderation.models import UserRestriction
from app.users.models import User

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[Session, Depends(get_db)]


def get_token_payload(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict[str, object]:
    if credentials is None or not credentials.credentials:
        raise AuthError("Please sign in to continue.")
    payload = decode_access_token(credentials.credentials)
    # Expose the subject to rate limiting / logging middleware.
    if payload.get("sub"):
        request.state.user_id = str(payload["sub"])
    return payload


def get_current_user(
    request: Request,
    db: DbSession,
    payload: Annotated[dict[str, object], Depends(get_token_payload)],
) -> User:
    user = AuthService(db).authenticate_token(payload)
    set_user(str(user.id))
    request.state.user_id = str(user.id)
    return user


def get_optional_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    """For endpoints that personalise an anonymous-accessible response."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        user = AuthService(db).authenticate_token(payload)
    except AuthError:
        return None
    set_user(str(user.id))
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_roles(*roles: Role | str) -> Callable[[User], User]:
    wanted = {r.value if isinstance(r, Role) else str(r) for r in roles}

    def _dependency(user: CurrentUser) -> User:
        if not wanted & set(user.role_names):
            raise PermissionDeniedError(
                "This action requires a different account role.",
                details={"required_roles": sorted(wanted)},
            )
        return user

    return _dependency


STAFF_ROLES = (Role.MODERATOR, Role.ADMIN)
EXPERT_ROLES = (Role.EXPERT, Role.MODERATOR, Role.ADMIN)

require_staff = require_roles(*STAFF_ROLES)
require_admin = require_roles(Role.ADMIN)
require_expert = require_roles(*EXPERT_ROLES)

StaffUser = Annotated[User, Depends(require_staff)]
AdminUser = Annotated[User, Depends(require_admin)]
ExpertUser = Annotated[User, Depends(require_expert)]


def active_restrictions(
    db: Session, user_id: uuid.UUID, capability: str | None = None
) -> list[UserRestriction]:
    stmt = select(UserRestriction).where(
        UserRestriction.user_id == user_id, UserRestriction.active.is_(True)
    )
    if capability:
        stmt = stmt.where(UserRestriction.capability == capability)
    rows = list(db.execute(stmt).scalars().all())
    return [r for r in rows if r.is_active()]


def require_capability(capability: str) -> Callable[..., User]:
    """Blocks an action while a moderation restriction is active for the user.

    Used for write paths (post, comment, upload). Restriction is a moderation
    outcome, so the error explains the restriction without leaking moderator
    identity.
    """

    def _dependency(user: CurrentUser, db: DbSession) -> User:
        restrictions = active_restrictions(db, user.id, capability)
        if restrictions:
            until = max((r.expires_at for r in restrictions if r.expires_at), default=None)
            raise PermissionDeniedError(
                "Your account is temporarily restricted from this action.",
                details={
                    "capability": capability,
                    "restricted_until": until.isoformat() if until else None,
                    "reason": restrictions[0].reason,
                },
            )
        if user.status != UserStatus.ACTIVE:
            raise AccountDisabledError("Your account is not active. Please contact support.")
        return user

    return _dependency


def current_session_id(
    payload: Annotated[dict[str, object], Depends(get_token_payload)],
) -> uuid.UUID | None:
    raw = payload.get("sid")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def client_metadata(request: Request) -> dict[str, str | None]:
    """Coarse client metadata for session records (no precise device fingerprint)."""
    forwarded = request.headers.get("x-forwarded-for")
    ip = (forwarded.split(",")[0].strip() if forwarded else None) or (
        request.client.host if request.client else None
    )
    return {
        "ip_address": ip,
        "user_agent": request.headers.get("user-agent"),
        "device_label": request.headers.get("x-device-label"),
    }


def raise_if_inactive(user: User) -> None:
    if user.status in (UserStatus.SUSPENDED, UserStatus.DISABLED):
        raise AccountDisabledError()


def ensure_self_or_staff(actor: User, owner_id: uuid.UUID) -> None:
    """Owner-or-staff guard for object-level actions.

    A non-owner gets the same 404 they would get for a row that does not exist:
    answering 403 here would confirm that somebody else's content exists.
    """
    if actor.id == owner_id or actor.has_role(Role.MODERATOR, Role.ADMIN):
        return
    not_found()


__all__ = [
    "AdminUser",
    "CurrentUser",
    "DbSession",
    "ExpertUser",
    "OptionalUser",
    "StaffUser",
    "TokenError",
    "active_restrictions",
    "bearer_scheme",
    "client_metadata",
    "current_session_id",
    "get_current_user",
    "get_optional_user",
    "get_token_payload",
    "require_admin",
    "require_capability",
    "require_expert",
    "require_roles",
    "require_staff",
]
