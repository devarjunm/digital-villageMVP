"""Notification endpoints (user) — admin broadcast lives in /admin/notifications."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.auth.dependencies import CurrentUser, DbSession
from app.core.enums import NotificationType
from app.core.pagination import PageParams, page_params
from app.core.ratelimit import enforce_rate_limit
from app.notifications.schemas import (
    DeviceOut,
    DeviceRegister,
    NotificationList,
    NotificationOut,
    PreferenceOut,
    PreferenceUpdate,
    PushHealth,
    UnreadCount,
)
from app.notifications.service import NotificationService

router = APIRouter()

PageDep = Annotated[PageParams, Depends(page_params)]


def _to_out(notification) -> NotificationOut:
    data = NotificationOut.model_validate(notification)
    data.read = notification.read_at is not None
    return data


@router.get("", response_model=NotificationList, summary="Your notifications")
def list_notifications(
    db: DbSession,
    user: CurrentUser,
    request: Request,
    params: PageDep,
    unread_only: bool = False,
    type_filter: Annotated[NotificationType | None, Query(alias="type")] = None,
) -> NotificationList:
    enforce_rate_limit(request, "read")
    service = NotificationService(db)
    rows, total = service.list(
        user_id=user.id,
        unread_only=unread_only,
        type_filter=type_filter,
        limit=params.limit,
        offset=params.offset,
    )
    total_pages = max(1, (total + params.page_size - 1) // params.page_size) if total else 0
    return NotificationList(
        items=[_to_out(row) for row in rows],
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=total_pages,
        has_next=params.page * params.page_size < total,
        unread_count=service.unread_count(user.id),
    )


@router.get("/unread-count", response_model=UnreadCount, summary="Badge count and daily cap status")
def unread_count(db: DbSession, user: CurrentUser) -> UnreadCount:
    service = NotificationService(db)
    pref = service.preferences(user.id)
    return UnreadCount(
        unread_count=service.unread_count(user.id),
        max_per_day=pref.max_per_day,
        created_last_24h=service._daily_count(user.id),
    )


@router.get("/digest", summary="Summary of the last 24 hours (used by the app's digest card)")
def digest(
    db: DbSession, user: CurrentUser, hours: Annotated[int, Query(ge=1, le=168)] = 24
) -> dict:
    return NotificationService(db).digest(user.id, hours=hours)


@router.post("/{notification_id}/read", response_model=NotificationOut, summary="Mark one as read")
def mark_read(notification_id: uuid.UUID, db: DbSession, user: CurrentUser) -> NotificationOut:
    return _to_out(
        NotificationService(db).mark_read(user_id=user.id, notification_id=notification_id)
    )


@router.post("/read-all", summary="Mark everything as read")
def mark_all_read(db: DbSession, user: CurrentUser) -> dict:
    return {"updated": NotificationService(db).mark_all_read(user.id)}


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a notification",
)
def delete_notification(notification_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    NotificationService(db).delete(user_id=user.id, notification_id=notification_id)


@router.get("/preferences", response_model=PreferenceOut, summary="Your notification preferences")
def get_preferences(db: DbSession, user: CurrentUser) -> PreferenceOut:
    return PreferenceOut.model_validate(NotificationService(db).preferences(user.id))


@router.patch("/preferences", response_model=PreferenceOut, summary="Update preferences")
def update_preferences(
    payload: PreferenceUpdate, db: DbSession, user: CurrentUser, request: Request
) -> PreferenceOut:
    enforce_rate_limit(request, "write")
    pref = NotificationService(db).update_preferences(
        user.id, payload.model_dump(exclude_unset=True)
    )
    return PreferenceOut.model_validate(pref)


@router.post(
    "/devices",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a device for push",
)
def register_device(
    payload: DeviceRegister, db: DbSession, user: CurrentUser, request: Request
) -> DeviceOut:
    enforce_rate_limit(request, "write")
    device = NotificationService(db).register_device(
        user_id=user.id, token=payload.token, platform=payload.platform
    )
    return DeviceOut(
        id=device.id,
        platform=device.platform,
        token_suffix=device.token[-6:],
        is_active=device.is_active,
        last_seen_at=device.last_seen_at,
    )


@router.delete(
    "/devices",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Unregister a device",
)
def unregister_device(
    db: DbSession, user: CurrentUser, token: Annotated[str, Query(min_length=10, max_length=255)]
) -> None:
    NotificationService(db).unregister_device(user_id=user.id, token=token)


@router.get("/push-health", response_model=PushHealth, summary="Which push provider is active")
def push_health() -> PushHealth:
    from app.core.config import settings
    from app.providers.push import PushNotConfiguredError, get_push_provider

    try:
        provider = get_push_provider()
    except PushNotConfiguredError as exc:
        return PushHealth(
            provider=settings.push_provider, is_demo=False, configured=False, note=str(exc)
        )
    return PushHealth(**provider.health())
