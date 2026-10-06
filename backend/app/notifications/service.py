"""Notification service.

Rules encoded here:
  * a notification is a row first (durable, auditable, deep-linkable) and a push
    message second — if push fails, the in-app record and `push_error` survive;
  * per-user preferences (weather/market/crop/community/scheme/ai), quiet hours
    and a hard daily cap are enforced before anything is created;
  * `create()` is safe to call from request handlers and workers alike and never
    raises for a suppressed notification (it returns the outcome);
  * devices are registered per user with a token, and invalid tokens returned by
    the push provider are deactivated instead of retried forever.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.enums import NotificationChannel, NotificationType
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.observability import NOTIFICATION_COUNTER
from app.notifications.models import Notification, NotificationPreference
from app.users.models import DeviceToken

logger = get_logger(__name__)

# Which preference flag gates which notification type.
PREFERENCE_BY_TYPE: dict[str, str] = {
    NotificationType.WEATHER_ALERT.value: "weather_alerts",
    NotificationType.MARKET_UPDATE.value: "market_updates",
    NotificationType.CROP_REMINDER.value: "crop_reminders",
    NotificationType.COMMENT_REPLY.value: "community_activity",
    NotificationType.MENTION.value: "community_activity",
    NotificationType.POST_IN_FEED.value: "community_activity",
    NotificationType.SCHEME_UPDATE.value: "scheme_updates",
    NotificationType.AI_JOB_COMPLETE.value: "ai_job_updates",
    NotificationType.MODERATION_ACTION.value: "in_app_enabled",
    NotificationType.SYSTEM.value: "in_app_enabled",
}
# Types that are always created: account and safety-critical messages.
ALWAYS_ON_TYPES = {NotificationType.MODERATION_ACTION.value, NotificationType.SYSTEM.value}


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ----------------------------------------------------------- preferences
    def preferences(self, user_id: uuid.UUID) -> NotificationPreference:
        pref = self.db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        ).scalar_one_or_none()
        if pref is None:
            pref = NotificationPreference(user_id=user_id)
            self.db.add(pref)
            self.db.flush()
        return pref

    def update_preferences(
        self, user_id: uuid.UUID, data: dict[str, Any]
    ) -> NotificationPreference:
        pref = self.preferences(user_id)
        allowed = {
            "in_app_enabled",
            "push_enabled",
            "weather_alerts",
            "market_updates",
            "crop_reminders",
            "community_activity",
            "scheme_updates",
            "ai_job_updates",
            "digest_only",
            "quiet_hours_start",
            "quiet_hours_end",
            "max_per_day",
        }
        for field, value in data.items():
            if field in allowed and value is not None:
                setattr(pref, field, value)
        if pref.max_per_day < 1 or pref.max_per_day > 200:
            raise ValidationError("max_per_day must be between 1 and 200.")
        self.db.commit()
        self.db.refresh(pref)
        return pref

    # -------------------------------------------------------------- creation
    def create(
        self,
        *,
        user_id: uuid.UUID,
        type: NotificationType | str,
        title: str,
        body: str,
        subject_type: str | None = None,
        subject_id: uuid.UUID | None = None,
        deep_link: str | None = None,
        payload: dict[str, Any] | None = None,
        language: str = "en",
        send_push: bool | None = None,
    ) -> dict[str, Any]:
        type_value = type.value if hasattr(type, "value") else str(type)
        pref = self.preferences(user_id)

        if not pref.in_app_enabled and type_value not in ALWAYS_ON_TYPES:
            return {"created": False, "reason": "in_app_disabled"}
        flag = PREFERENCE_BY_TYPE.get(type_value)
        if flag and flag != "in_app_enabled" and not getattr(pref, flag, True):
            return {"created": False, "reason": f"preference_disabled:{flag}"}
        if self._in_quiet_hours(pref) and type_value not in ALWAYS_ON_TYPES:
            return {"created": False, "reason": "quiet_hours"}
        if self._daily_count(user_id) >= min(pref.max_per_day, _max_per_day_setting()):
            return {"created": False, "reason": "daily_cap_reached"}

        notification = Notification(
            user_id=user_id,
            type=NotificationType(type_value),
            title=title[:200],
            body=body[:600],
            language=language,
            subject_type=subject_type,
            subject_id=subject_id,
            deep_link=deep_link,
            payload=payload or {},
        )
        self.db.add(notification)
        self.db.flush()
        NOTIFICATION_COUNTER.labels(type=type_value, channel=NotificationChannel.IN_APP.value).inc()

        should_push = pref.push_enabled if send_push is None else (send_push and pref.push_enabled)
        push_outcome: dict[str, Any] = {"attempted": False}
        if should_push:
            push_outcome = self.send_push(notification, commit=False)
        return {"created": True, "notification_id": notification.id, "push": push_outcome}

    def fan_out(self, *, user_ids: list[uuid.UUID], **kwargs: Any) -> dict[str, Any]:
        created = 0
        skipped: dict[str, int] = {}
        for user_id in set(user_ids):
            outcome = self.create(user_id=user_id, **kwargs)
            if outcome.get("created"):
                created += 1
            else:
                reason = outcome.get("reason", "unknown")
                skipped[reason] = skipped.get(reason, 0) + 1
        self.db.commit()
        return {"created": created, "skipped": skipped, "recipients": len(set(user_ids))}

    # ----------------------------------------------------------------- push
    def register_device(self, *, user_id: uuid.UUID, token: str, platform: str) -> DeviceToken:
        if platform not in {"android", "ios", "web"}:
            raise ValidationError("platform must be android, ios or web.")
        existing = self.db.execute(
            select(DeviceToken).where(DeviceToken.token == token)
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            # A device may change hands: re-point the token at the current user.
            existing.user_id = user_id
            existing.platform = platform
            existing.is_active = True
            existing.last_seen_at = now
            self.db.commit()
            self.db.refresh(existing)
            return existing
        device = DeviceToken(user_id=user_id, token=token, platform=platform, last_seen_at=now)
        self.db.add(device)
        self.db.commit()
        self.db.refresh(device)
        return device

    def unregister_device(self, *, user_id: uuid.UUID, token: str) -> bool:
        device = self.db.execute(
            select(DeviceToken).where(DeviceToken.token == token, DeviceToken.user_id == user_id)
        ).scalar_one_or_none()
        if device is None:
            return False
        device.is_active = False
        self.db.commit()
        return True

    def devices(self, user_id: uuid.UUID) -> list[DeviceToken]:
        return list(
            self.db.execute(
                select(DeviceToken).where(
                    DeviceToken.user_id == user_id, DeviceToken.is_active.is_(True)
                )
            ).scalars()
        )

    def send_push(self, notification: Notification, *, commit: bool = True) -> dict[str, Any]:
        from app.providers.push import PushMessage, PushNotConfiguredError, get_push_provider

        devices = self.devices(notification.user_id)
        if not devices:
            return {"attempted": False, "reason": "no_registered_device"}
        try:
            provider = get_push_provider()
        except PushNotConfiguredError as exc:
            notification.push_error = str(exc)[:255]
            if commit:
                self.db.commit()
            return {
                "attempted": False,
                "reason": "provider_not_configured",
                "detail": str(exc),
                "provider": None,
            }
        payload = {
            key: str(value)
            for key, value in (notification.payload or {}).items()
            if isinstance(value, str | int | float)
        }
        messages = [
            PushMessage(
                token=device.token,
                title=notification.title,
                body=notification.body,
                data={
                    "notification_id": str(notification.id),
                    "type": notification.type.value,
                    **payload,
                },
                deep_link=notification.deep_link,
            )
            for device in devices
        ]
        results = provider.send(messages)
        delivered = sum(1 for item in results if item.delivered)
        errors = [item.detail for item in results if not item.delivered and item.detail]
        for device, result in zip(devices, results, strict=False):
            if result.delivered:
                notification.push_sent_at = datetime.now(UTC)
                notification.push_error = None
                NOTIFICATION_COUNTER.labels(
                    type=notification.type.value, channel=NotificationChannel.PUSH.value
                ).inc()
            elif result.reason == "invalid_token":
                device.is_active = False
                errors.append(f"deactivated stale token …{device.token[-6:]}")
        if not delivered and errors:
            notification.push_error = "; ".join(errors)[:255]
        if commit:
            self.db.commit()
        return {
            "attempted": True,
            "provider": provider.name,
            "is_demo": provider.is_demo,
            "delivered": delivered,
            "devices": len(devices),
            "not_delivered": len(messages) - delivered,
            "detail": None if delivered else notification.push_error,
        }

    # ------------------------------------------------------------------ read
    def list(
        self,
        *,
        user_id: uuid.UUID,
        unread_only: bool = False,
        type_filter: NotificationType | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        count_stmt = (
            select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
            count_stmt = count_stmt.where(Notification.read_at.is_(None))
        if type_filter is not None:
            stmt = stmt.where(Notification.type == type_filter)
            count_stmt = count_stmt.where(Notification.type == type_filter)
        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(
                stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )
        return rows, total

    def unread_count(self, user_id: uuid.UUID) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            ).scalar_one()
        )

    def mark_read(self, *, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
        notification = self.db.get(Notification, notification_id)
        if notification is None or notification.user_id != user_id:
            raise NotFoundError("Notification not found.")
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(notification)
        return notification

    def mark_all_read(self, user_id: uuid.UUID) -> int:
        result = self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now(UTC))
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def delete(self, *, user_id: uuid.UUID, notification_id: uuid.UUID) -> None:
        notification = self.db.get(Notification, notification_id)
        if notification is None or notification.user_id != user_id:
            raise NotFoundError("Notification not found.")
        self.db.delete(notification)
        self.db.commit()

    # ---------------------------------------------------------------- helper
    def _daily_count(self, user_id: uuid.UUID) -> int:
        since = datetime.now(UTC) - timedelta(hours=24)
        return int(
            self.db.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.created_at >= since)
            ).scalar_one()
        )

    def _in_quiet_hours(self, pref: NotificationPreference) -> bool:
        if not pref.quiet_hours_start or not pref.quiet_hours_end:
            return False
        now = datetime.now(UTC).time()
        start, end = pref.quiet_hours_start, pref.quiet_hours_end
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end  # window crosses midnight

    def digest(self, user_id: uuid.UUID, *, hours: int = 24) -> dict[str, Any]:
        """Digest payload for the daily summary (used by the digest job and app)."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        rows = list(
            self.db.execute(
                select(Notification)
                .where(Notification.user_id == user_id, Notification.created_at >= since)
                .order_by(Notification.created_at.desc())
            ).scalars()
        )
        by_type: dict[str, int] = {}
        for row in rows:
            by_type[row.type.value] = by_type.get(row.type.value, 0) + 1
        return {
            "window_hours": hours,
            "total": len(rows),
            "by_type": by_type,
            "items": [
                {
                    "id": str(row.id),
                    "type": row.type.value,
                    "title": row.title,
                    "body": row.body,
                    "deep_link": row.deep_link,
                    "read": row.read_at is not None,
                    "created_at": row.created_at,
                }
                for row in rows[:20]
            ],
        }


def _max_per_day_setting() -> int:
    from app.core.config import settings

    return settings.notification_max_per_day
