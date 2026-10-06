"""Product-event ingestion."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.analytics.service import AnalyticsService
from app.auth.dependencies import DbSession, OptionalUser
from app.core.context import current_user_id

router = APIRouter()


class EventIn(BaseModel):
    name: str = Field(min_length=3, max_length=64)
    props: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=64)
    anonymous_id: str | None = Field(default=None, max_length=64)
    platform: str = Field(default="android", max_length=24)
    app_version: str | None = Field(default=None, max_length=24)


class EventBatch(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=50)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED, summary="Record product events")
def record_events(
    payload: EventBatch, db: DbSession, user: OptionalUser, request: Request
) -> dict[str, object]:
    service = AnalyticsService(db)
    accepted = 0
    rejected: list[str] = []
    for event in payload.events:
        try:
            service.record_event(
                name=event.name,
                user_id=user.id if user else None,
                props=event.props,
                session_id=event.session_id,
                anonymous_id=event.anonymous_id,
                platform=event.platform,
                app_version=event.app_version,
                commit=False,
            )
            accepted += 1
        except Exception:
            rejected.append(event.name)
    db.commit()
    return {
        "accepted": accepted,
        "rejected": rejected,
        "user_id": current_user_id(),
        "note": "Only allow-listed event names and property keys are stored; values are never used to identify a person.",
    }
