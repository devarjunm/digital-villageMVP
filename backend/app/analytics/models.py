"""Analytics models.

Two tables, both first-party and privacy-bounded:

  * `product_events` — allow-listed in-app events (see AnalyticsService). Property
    keys are filtered against an allow-list before insert, so a client bug cannot
    push personal data into analytics. Demo traffic is flagged `is_demo`.
  * `search_events` — what was searched, in which mode, and how many results came
    back. Used to prioritise what farmers cannot find. The query text is stored
    because it is the signal that makes coverage work; it is capped and never
    joined to an external identity.

Columns here mirror the initial migration exactly (`e1d0628ce86d`); the migration,
not the ORM, is what has been applied to the database.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SearchMode, enum_col
from app.database.base import Base, DemoFlagMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ProductEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "product_events"
    __table_args__ = (
        sa.Index("ix_product_events_user_created", "user_id", "created_at"),
        sa.Index("ix_product_events_name_created", "name", "created_at"),
    )

    name: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    anonymous_id: Mapped[str | None] = mapped_column(sa.String(64))
    session_id: Mapped[str | None] = mapped_column(sa.String(64))
    platform: Mapped[str] = mapped_column(sa.String(24), default="android", nullable=False)
    app_version: Mapped[str | None] = mapped_column(sa.String(24))
    props: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)


class SearchEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "search_events"
    __table_args__ = (sa.Index("ix_search_events_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    query: Mapped[str] = mapped_column(sa.String(400), nullable=False)
    mode: Mapped[SearchMode] = mapped_column(enum_col(SearchMode, "search_mode"), nullable=False)
    scope: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    result_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    clicked_target_type: Mapped[str | None] = mapped_column(sa.String(32))
    clicked_target_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True))
    language: Mapped[str | None] = mapped_column(sa.String(8))
