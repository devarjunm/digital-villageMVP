"""Account and public-profile endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.auth.dependencies import CurrentUser, DbSession, OptionalUser
from app.auth.schemas import PublicUser
from app.auth.service import AuthService
from app.core.enums import ConsentSource
from app.core.errors import ValidationError
from app.core.ratelimit import enforce_rate_limit
from app.users.consent import ConsentService, policy_version
from app.users.privacy import PrivacyService
from app.users.schemas import (
    ConsentOverview,
    ConsentUpdateRequest,
    DataExportRequest,
    DeleteAccountRequest,
    UpdateAccountRequest,
    UserPublicProfile,
    UserSearchResult,
)
from app.users.service import UserService

router = APIRouter()


@router.get("/me", response_model=PublicUser, summary="My account settings")
def my_account(user: CurrentUser, db: DbSession) -> PublicUser:
    return AuthService(db).to_public_user(user)


@router.patch("/me", response_model=PublicUser, summary="Update account settings")
def update_account(payload: UpdateAccountRequest, user: CurrentUser, db: DbSession) -> PublicUser:
    updated = UserService(db).update_account(
        user,
        full_name=payload.full_name,
        preferred_language=payload.preferred_language,
        avatar_media_id=payload.avatar_media_id,
        email=payload.email,
    )
    return AuthService(db).to_public_user(updated)


@router.delete("/me", status_code=status.HTTP_202_ACCEPTED, summary="Delete my account")
def delete_account(payload: DeleteAccountRequest, user: CurrentUser, db: DbSession) -> dict:
    """Erase personal data, close the account and return a receipt of what was kept."""
    receipt = AuthService(db).delete_account(user, confirm=payload.confirm)
    return {
        "status": "deleted",
        "message": (
            "Your personal information was removed, every session was revoked and the account is closed. "
            "Community posts remain attributed to 'Deleted account' so other members' threads stay readable."
        ),
        "receipt": receipt,
    }


@router.get("/search", response_model=list[UserSearchResult], summary="Search members")
def search_members(
    db: DbSession,
    viewer: OptionalUser,
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[UserSearchResult]:
    enforce_rate_limit(request, "search")
    return UserService(db).search(query=q, limit=limit, viewer=viewer)


@router.get(
    "/consents/purposes",
    summary="What each consent purpose means (no authentication required)",
)
def consent_purposes() -> dict:
    """Static copy for the consent screen.

    Public on purpose: the wording must be readable *before* an account exists,
    and the app must never invent its own explanation of what a purpose covers.
    """
    return ConsentService.describe_purposes()


@router.get("/me/consents", response_model=ConsentOverview, summary="My consent decisions")
def my_consents(user: CurrentUser, db: DbSession) -> ConsentOverview:
    return ConsentOverview.model_validate(ConsentService(db).overview(user.id))


@router.patch("/me/consents", response_model=ConsentOverview, summary="Record consent decisions")
def update_consents(
    payload: ConsentUpdateRequest, user: CurrentUser, db: DbSession, request: Request
) -> ConsentOverview:
    """Record a batch of consent decisions for the signed-in user.

    Sending a decision for a purpose the user did not actually see is the kind of
    mistake this endpoint cannot detect, so the server refuses decisions that
    were taken against a different policy version than the one it is serving.
    """
    enforce_rate_limit(request, "write")
    service = ConsentService(db)
    if payload.policy_version is not None and payload.policy_version != policy_version():
        raise ValidationError(
            "The consent text has changed since this screen was loaded. Please reload it before deciding.",
            details={"current_policy_version": policy_version()},
        )
    decisions = {item.kind: item.granted for item in payload.decisions}
    return ConsentOverview.model_validate(
        service.record_many(
            user_id=user.id,
            decisions=decisions,
            source=ConsentSource.MOBILE_APP,
            ip_address=request.client.host if request.client else None,
            app_version=payload.app_version,
        )
    )


@router.get(
    "/me/data-export",
    summary="Download everything the platform stores about me",
)
def export_my_data(user: CurrentUser, db: DbSession, request: Request) -> dict:
    enforce_rate_limit(request, "read")
    return PrivacyService(db).export(user)


@router.post(
    "/me/data-export/request",
    status_code=status.HTTP_200_OK,
    summary="Confirm and fetch my data export",
)
def request_data_export(
    payload: DataExportRequest, user: CurrentUser, db: DbSession, request: Request
) -> dict:
    """POST twin of the GET export, for clients that prefer an explicit confirmation.

    The confirmation string exists so that an accidental tap cannot produce a file
    containing the user's personal data.
    """
    enforce_rate_limit(request, "read")
    _ = payload  # validated by the schema (must equal EXPORT)
    return PrivacyService(db).export(user)


@router.get("/{user_id}", response_model=UserPublicProfile, summary="Public profile of a member")
def public_profile(
    user_id: uuid.UUID, db: DbSession, viewer: OptionalUser, request: Request
) -> UserPublicProfile:
    enforce_rate_limit(request, "read")
    return UserService(db).public_profile(user_id, viewer=viewer)
