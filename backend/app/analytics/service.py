"""Privacy-conscious product analytics.

* event names are allow-listed (settings.product_event_allowlist);
* property keys are allow-listed per event; unknown keys are dropped, so PII
  cannot be smuggled into the analytics table by a client bug;
* demo/seed traffic is flagged `is_demo` so dashboards can exclude it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.models import ProductEvent, SearchEvent
from app.core.config import settings
from app.core.enums import SearchMode
from app.core.errors import ValidationError

# Property keys that may be stored, per event family. Anything else is dropped.
ALLOWED_PROPS: dict[str, set[str]] = {
    "app_opened": {"version", "platform"},
    "post_created": {"category", "crop", "has_image"},
    "post_viewed": {"category", "surface"},
    "comment_created": {"is_reply"},
    "ai_request": {"kind", "model_name", "model_version", "is_demo", "latency_ms"},
    "disease_scan": {"crop", "top_label", "confidence_bucket", "model_version"},
    "recommendation_viewed": {"crop", "rule", "sort"},
    "scheme_viewed": {"scheme_slug", "state"},
    "search_performed": {"mode", "scope", "result_count"},
    "notification_interaction": {"type", "action"},
    "market_viewed": {"crop", "market", "is_estimate"},
    "weather_viewed": {"provider", "is_demo"},
    "profile_updated": {"fields"},
    "farm_created": {"area_unit", "soil_type", "irrigation_type"},
    "crop_created": {"crop", "stage", "season"},
    "assistant_message": {"language", "citations_count", "insufficient_evidence"},
    "agent_run": {"tools_used", "steps"},
    "feedback_submitted": {"verdict", "model_name"},
}
GLOBAL_ALLOWED = {"source", "screen"}


class AnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record_event(
        self,
        *,
        name: str,
        user_id: uuid.UUID | None,
        props: dict[str, Any] | None,
        session_id: str | None = None,
        anonymous_id: str | None = None,
        platform: str = "android",
        app_version: str | None = None,
        is_demo: bool = False,
        commit: bool = True,
    ) -> ProductEvent | None:
        if not settings.analytics_enabled:
            return None
        if user_id is not None and settings.analytics_requires_consent:
            # Consent gate. "No record" means "not granted" (see ConsentService),
            # so a user who never opened the consent screen is not tracked.
            from app.core.enums import ConsentKind
            from app.users.consent import ConsentService

            if not ConsentService(self.db).has_consent(user_id, ConsentKind.ANALYTICS):
                return None
        if name not in settings.analytics_event_names:
            raise ValidationError(
                "That event is not tracked.",
                details={"event": name, "tracked": sorted(settings.analytics_event_names)[:50]},
            )
        allowed = ALLOWED_PROPS.get(name, set()) | GLOBAL_ALLOWED
        clean = {k: v for k, v in (props or {}).items() if k in allowed}
        event = ProductEvent(
            name=name,
            user_id=user_id,
            props=clean,
            session_id=session_id,
            anonymous_id=anonymous_id,
            platform=platform,
            app_version=app_version,
            is_demo=is_demo,
        )
        self.db.add(event)
        if commit:
            self.db.commit()
        return event

    def record_search(
        self,
        *,
        query: str,
        user_id: uuid.UUID | None,
        mode: SearchMode,
        scope: str,
        result_count: int,
        language: str | None = None,
        commit: bool = True,
    ) -> SearchEvent:
        event = SearchEvent(
            query=query[:400],
            user_id=user_id,
            mode=mode,
            scope=scope,
            result_count=result_count,
            language=language,
        )
        self.db.add(event)
        if commit:
            self.db.commit()
        return event

    def event_counts(self, *, days: int = 30, include_demo: bool = False) -> dict[str, int]:
        from datetime import UTC, datetime, timedelta

        since = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(ProductEvent.name, func.count())
            .where(ProductEvent.created_at >= since)
            .group_by(ProductEvent.name)
        )
        if not include_demo:
            stmt = stmt.where(ProductEvent.is_demo.is_(False))
        return {name: int(count) for name, count in self.db.execute(stmt).all()}
