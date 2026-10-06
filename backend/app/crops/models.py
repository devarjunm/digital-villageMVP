"""Crop catalog and planted crops.

`CropCatalog` replaces a hard-coded crop list: it carries the multilingual names,
the expected season and, optionally, the class labels the disease model was
trained on (`disease_model_labels`), so the API can tell the client *which*
crops the vision model actually supports instead of pretending to diagnose all.
"""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AreaUnit,
    CropEventType,
    CropStage,
    CropStatus,
    IrrigationType,
    Season,
    enum_col,
)
from app.database.base import (
    Base,
    DemoFlagMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    json_document,
)


class CropCatalog(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "crops_catalog"
    __table_args__ = (sa.UniqueConstraint("code", name="uq_crops_catalog_code"),)

    code: Mapped[str] = mapped_column(sa.String(48), nullable=False, index=True)
    name_en: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    name_mr: Mapped[str | None] = mapped_column(sa.String(120))
    name_hi: Mapped[str | None] = mapped_column(sa.String(120))
    category: Mapped[str | None] = mapped_column(sa.String(48))
    season: Mapped[Season] = mapped_column(
        enum_col(Season, "season"), default=Season.ANY, nullable=False
    )
    default_area_unit: Mapped[AreaUnit] = mapped_column(
        enum_col(AreaUnit, "area_unit"), default=AreaUnit.ACRE, nullable=False
    )
    # Class labels the shipped disease model was trained on for this crop
    # (empty ⇒ the vision model has no trained classes for it).
    disease_model_labels: Mapped[list[str]] = mapped_column(
        json_document(), default=list, nullable=False
    )
    typical_yield_per_hectare: Mapped[float | None] = mapped_column(
        sa.Numeric(12, 3),
        comment="Reference figure with the source recorded in data/datasets/README.md; used only as a "
        "documented baseline, never as a prediction.",
    )
    reference_source: Mapped[str | None] = mapped_column(sa.String(255))
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)


class Crop(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, DemoFlagMixin):
    __tablename__ = "crops"
    __table_args__ = (
        sa.CheckConstraint("area_value IS NULL OR area_value > 0", name="area_positive"),
        sa.CheckConstraint(
            "expected_harvest_date IS NULL OR sowing_date IS NULL OR expected_harvest_date >= sowing_date",
            name="harvest_after_sowing",
        ),
    )

    farm_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    crop_code: Mapped[str] = mapped_column(sa.String(48), nullable=False, index=True)
    variety: Mapped[str | None] = mapped_column(sa.String(120))
    season: Mapped[Season] = mapped_column(
        enum_col(Season, "season"), default=Season.ANY, nullable=False
    )
    sowing_date: Mapped[date | None] = mapped_column(sa.Date)
    expected_harvest_date: Mapped[date | None] = mapped_column(sa.Date)
    area_value: Mapped[float | None] = mapped_column(sa.Numeric(12, 4))
    area_unit: Mapped[AreaUnit] = mapped_column(
        enum_col(AreaUnit, "area_unit"), default=AreaUnit.ACRE, nullable=False
    )
    stage: Mapped[CropStage] = mapped_column(
        enum_col(CropStage, "crop_stage"), default=CropStage.PLANNED, nullable=False, index=True
    )
    status: Mapped[CropStatus] = mapped_column(
        enum_col(CropStatus, "crop_status"), default=CropStatus.ACTIVE, nullable=False, index=True
    )
    irrigation_method: Mapped[IrrigationType | None] = mapped_column(
        enum_col(IrrigationType, "irrigation_type")
    )
    seed_source: Mapped[str | None] = mapped_column(sa.String(160))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    farm: Mapped[Farm] = relationship(back_populates="crops")  # noqa: F821
    events: Mapped[list[CropEvent]] = relationship(
        back_populates="crop", cascade="all, delete-orphan", lazy="selectin"
    )


class CropEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A dated activity on a crop (sowing, irrigation, fertiliser, observation…).

    This is the farmer's own log — it is user content, not model output, and is
    the only yield-history input the prediction service accepts.
    """

    __tablename__ = "crop_events"
    __table_args__ = (
        sa.CheckConstraint("cost IS NULL OR cost >= 0", name="cost_non_negative"),
        sa.CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
    )

    crop_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("crops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[CropEventType] = mapped_column(
        enum_col(CropEventType, "crop_event_type"), nullable=False
    )
    event_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    quantity: Mapped[float | None] = mapped_column(sa.Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(sa.String(32))
    cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )

    crop: Mapped[Crop] = relationship(back_populates="events")
