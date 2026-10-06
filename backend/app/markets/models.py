"""Market data.

Two facts are encoded structurally, not by convention:
  * every price row names its `source` (provider) and carries `is_estimate`;
    actual market observations and model estimates can never be confused;
  * `retrieved_at` is distinct from `price_date` so a cached observation is not
    presented as a fresh live quote.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import (
    Base,
    DemoFlagMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Market(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, DemoFlagMixin):
    __tablename__ = "markets"
    __table_args__ = (
        sa.UniqueConstraint("code", name="uq_markets_code"),
        sa.CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="latitude_range"
        ),
    )

    code: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    name_local: Mapped[str | None] = mapped_column(sa.String(160))
    state: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    district: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    market_type: Mapped[str] = mapped_column(
        sa.String(32), default="regulated_mandi", nullable=False
    )
    latitude: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    source_name: Mapped[str | None] = mapped_column(sa.String(160))
    source_url: Mapped[str | None] = mapped_column(sa.String(1024))
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)


class MarketPrice(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "market_prices"
    __table_args__ = (
        sa.UniqueConstraint(
            "market_id",
            "crop_code",
            "price_date",
            "source",
            "is_estimate",
            name="uq_market_prices_market_crop_date_source_kind",
        ),
        sa.CheckConstraint(
            "min_price IS NULL OR max_price IS NULL OR max_price >= min_price", name="price_range"
        ),
        sa.CheckConstraint(
            "modal_price IS NULL OR modal_price >= 0", name="modal_price_non_negative"
        ),
        sa.Index("ix_market_prices_lookup", "crop_code", "market_id", "price_date"),
        sa.Index("ix_market_prices_date", "price_date"),
    )

    market_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("markets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    crop_code: Mapped[str] = mapped_column(sa.String(48), nullable=False, index=True)
    crop_name: Mapped[str | None] = mapped_column(sa.String(120))
    price_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    min_price: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    max_price: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    modal_price: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    unit: Mapped[str] = mapped_column(sa.String(24), default="INR_per_quintal", nullable=False)
    arrivals_tonnes: Mapped[float | None] = mapped_column(sa.Numeric(12, 3))
    source: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(sa.String(1024))
    is_estimate: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False, index=True)
    model_name: Mapped[str | None] = mapped_column(sa.String(96))
    model_version: Mapped[str | None] = mapped_column(sa.String(64))
    retrieved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)


class MarketCrop(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    """Mapping between our crop catalog codes and the provider's crop names."""

    __tablename__ = "market_crops"
    __table_args__ = (
        sa.UniqueConstraint("crop_code", "source", name="uq_market_crops_crop_code_source"),
    )

    crop_code: Mapped[str] = mapped_column(sa.String(48), nullable=False, index=True)
    source: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    provider_crop_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    default_unit: Mapped[str] = mapped_column(
        sa.String(24), default="INR_per_quintal", nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
