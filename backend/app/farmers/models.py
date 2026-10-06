"""Farmer profile — the agricultural context of a user.

Privacy: the public projection of this model exposes name, village, district,
state, role and crops only. Phone/email never leave `User` and are only returned
to the owner or an admin.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AreaUnit, enum_col
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, json_document


class FarmerProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "farmer_profiles"
    __table_args__ = (
        sa.UniqueConstraint("user_id", name="uq_farmer_profiles_user_id"),
        sa.CheckConstraint(
            "farming_experience_years IS NULL OR (farming_experience_years >= 0 AND farming_experience_years <= 100)",
            name="farming_experience_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    village: Mapped[str | None] = mapped_column(sa.String(120))
    taluka: Mapped[str | None] = mapped_column(sa.String(120))
    district: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    state: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    pincode: Mapped[str | None] = mapped_column(sa.String(10))
    latitude: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    farming_experience_years: Mapped[int | None] = mapped_column(sa.Integer)
    primary_crops: Mapped[list[str]] = mapped_column(json_document(), default=list, nullable=False)
    interests: Mapped[list[str]] = mapped_column(json_document(), default=list, nullable=False)
    total_land_area: Mapped[float | None] = mapped_column(sa.Numeric(12, 4))
    total_land_unit: Mapped[AreaUnit | None] = mapped_column(enum_col(AreaUnit, "area_unit"))
    bio: Mapped[str | None] = mapped_column(sa.Text)
    organisation: Mapped[str | None] = mapped_column(sa.String(160))
    # Farmer opt-in for appearing in people search / expert directory.
    is_public: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")  # noqa: F821
