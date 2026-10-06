"""Farms and soil tests."""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AreaUnit, IrrigationType, OwnershipType, SoilType, enum_col
from app.database.base import (
    Base,
    DemoFlagMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Farm(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, DemoFlagMixin):
    __tablename__ = "farms"
    __table_args__ = (
        sa.CheckConstraint("area_value > 0", name="area_positive"),
        sa.CheckConstraint(
            "soil_ph IS NULL OR (soil_ph >= 0 AND soil_ph <= 14)", name="soil_ph_range"
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="latitude_range"
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", name="longitude_range"
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    area_value: Mapped[float] = mapped_column(sa.Numeric(12, 4), nullable=False)
    area_unit: Mapped[AreaUnit] = mapped_column(enum_col(AreaUnit, "area_unit"), nullable=False)
    village: Mapped[str | None] = mapped_column(sa.String(120))
    taluka: Mapped[str | None] = mapped_column(sa.String(120))
    district: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    state: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    pincode: Mapped[str | None] = mapped_column(sa.String(10))
    latitude: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    soil_type: Mapped[SoilType] = mapped_column(
        enum_col(SoilType, "soil_type"), default=SoilType.UNKNOWN, nullable=False
    )
    soil_ph: Mapped[float | None] = mapped_column(sa.Numeric(3, 1))
    irrigation_type: Mapped[IrrigationType] = mapped_column(
        enum_col(IrrigationType, "irrigation_type"), default=IrrigationType.RAINFED, nullable=False
    )
    ownership_type: Mapped[OwnershipType] = mapped_column(
        enum_col(OwnershipType, "ownership_type"), default=OwnershipType.OWNED, nullable=False
    )
    water_source_notes: Mapped[str | None] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    crops: Mapped[list[Crop]] = relationship(  # noqa: F821
        back_populates="farm", cascade="all, delete-orphan", lazy="selectin"
    )
    soil_tests: Mapped[list[SoilTest]] = relationship(
        back_populates="farm", cascade="all, delete-orphan", lazy="selectin"
    )


class SoilTest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "soil_tests"
    __table_args__ = (
        sa.CheckConstraint("ph IS NULL OR (ph >= 0 AND ph <= 14)", name="soil_test_ph_range"),
        sa.CheckConstraint(
            "nitrogen_kg_per_ha IS NULL OR nitrogen_kg_per_ha >= 0", name="nitrogen_non_negative"
        ),
    )

    farm_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tested_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    ph: Mapped[float | None] = mapped_column(sa.Numeric(3, 1))
    nitrogen_kg_per_ha: Mapped[float | None] = mapped_column(sa.Numeric(8, 2))
    phosphorus_kg_per_ha: Mapped[float | None] = mapped_column(sa.Numeric(8, 2))
    potassium_kg_per_ha: Mapped[float | None] = mapped_column(sa.Numeric(8, 2))
    organic_carbon_percent: Mapped[float | None] = mapped_column(sa.Numeric(5, 3))
    electrical_conductivity: Mapped[float | None] = mapped_column(sa.Numeric(6, 3))
    lab_name: Mapped[str | None] = mapped_column(sa.String(160))
    report_media_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(sa.Text)

    farm: Mapped[Farm] = relationship(back_populates="soil_tests")
