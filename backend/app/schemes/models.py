"""Government schemes and their structured eligibility rules.

A scheme row is only ever created from a named, linkable source
(`official_source_name` + `official_source_url`) and carries
`last_verified_on`. Seed rows that ship with the repository are flagged
`is_demo=True` and are clearly development placeholders whose fields must be
replaced with verified content before any production use.
"""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import VerificationStatus, enum_col
from app.database.base import (
    Base,
    DemoFlagMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    json_document,
)


class Scheme(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, DemoFlagMixin):
    __tablename__ = "schemes"
    __table_args__ = (
        sa.UniqueConstraint("slug", name="uq_schemes_slug"),
        sa.CheckConstraint("length(name_en) >= 3", name="name_length"),
    )

    slug: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    name_en: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    name_mr: Mapped[str | None] = mapped_column(sa.String(300))
    name_hi: Mapped[str | None] = mapped_column(sa.String(300))
    description_en: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description_mr: Mapped[str | None] = mapped_column(sa.Text)
    description_hi: Mapped[str | None] = mapped_column(sa.Text)
    benefits_en: Mapped[str | None] = mapped_column(sa.Text)
    benefits_mr: Mapped[str | None] = mapped_column(sa.Text)
    benefits_hi: Mapped[str | None] = mapped_column(sa.Text)
    eligibility_summary_en: Mapped[str | None] = mapped_column(sa.Text)
    eligibility_summary_mr: Mapped[str | None] = mapped_column(sa.Text)
    eligibility_summary_hi: Mapped[str | None] = mapped_column(sa.Text)
    application_process_en: Mapped[str | None] = mapped_column(sa.Text)
    application_process_mr: Mapped[str | None] = mapped_column(sa.Text)
    application_process_hi: Mapped[str | None] = mapped_column(sa.Text)
    documents_required: Mapped[list[str]] = mapped_column(sa.JSON, default=list, nullable=False)
    category: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    level: Mapped[str] = mapped_column(sa.String(16), default="state", nullable=False)
    state_codes: Mapped[list[str]] = mapped_column(json_document(), default=list, nullable=False)
    crop_codes: Mapped[list[str]] = mapped_column(json_document(), default=list, nullable=False)
    official_source_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    official_source_url: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    application_url: Mapped[str | None] = mapped_column(sa.String(1024))
    helpline: Mapped[str | None] = mapped_column(sa.String(64))
    last_verified_on: Mapped[date | None] = mapped_column(sa.Date)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_col(VerificationStatus, "verification_status"),
        default=VerificationStatus.UNVERIFIED,
        nullable=False,
        index=True,
    )
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    eligibility_rules: Mapped[list[SchemeEligibilityRule]] = relationship(
        back_populates="scheme", cascade="all, delete-orphan", lazy="selectin"
    )


class SchemeEligibilityRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single deterministic rule, e.g. field='land_holding_hectares', operator='<=', value=2.0.

    `field` is resolved against a fixed vocabulary (see
    app/schemes/eligibility.py) so rules remain data, never executable code.
    `is_hard_requirement=False` means failing the rule reduces suitability but
    does not disqualify, and `unknown` handling is explicit in the evaluator.
    """

    __tablename__ = "scheme_eligibility_rules"
    __table_args__ = (
        sa.CheckConstraint(
            "operator IN ('<=','<','>=','>','==','!=','in','not_in','contains','is_true','is_false')",
            name="operator_supported",
        ),
    )

    scheme_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("schemes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    operator: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    value: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    is_hard_requirement: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    note_en: Mapped[str | None] = mapped_column(sa.String(400))
    source_reference: Mapped[str | None] = mapped_column(sa.String(400))

    scheme: Mapped[Scheme] = relationship(back_populates="eligibility_rules")
