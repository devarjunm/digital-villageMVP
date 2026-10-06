"""Identity, authentication and access-control tables."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AuthIdentityKind,
    ConsentKind,
    ConsentSource,
    Language,
    OTPPurpose,
    Role,
    UserStatus,
    enum_col,
)
from app.database.base import (
    Base,
    DemoFlagMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utcnow,
)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "users"

    phone_e164: Mapped[str | None] = mapped_column(sa.String(20), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(sa.String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(sa.String(255))
    full_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    primary_role: Mapped[Role] = mapped_column(
        enum_col(Role, "role"), default=Role.FARMER, nullable=False, index=True
    )
    preferred_language: Mapped[Language] = mapped_column(
        enum_col(Language, "language"), default=Language.EN, nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        enum_col(UserStatus, "user_status"), default=UserStatus.ACTIVE, nullable=False, index=True
    )
    # `use_alter` breaks the users ⇄ media_assets circular FK so Alembic can
    # create the tables in any order (the constraint is added afterwards).
    avatar_media_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "media_assets.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_users_avatar_media_id_media_assets",
        ),
    )
    phone_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Bumped on password change / forced logout: invalidates outstanding access tokens.
    token_version: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    # `UserRole` has two FKs to users (user_id and granted_by_id), so the join
    # column must be stated explicitly.
    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="UserRole.user_id",
    )
    identities: Mapped[list[AuthIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    profile: Mapped[FarmerProfile | None] = relationship(  # noqa: F821
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def role_names(self) -> list[str]:
        return sorted({r.role.value for r in self.roles} | {self.primary_role.value})

    def has_role(self, *roles: Role | str) -> bool:
        wanted = {r.value if isinstance(r, Role) else str(r) for r in roles}
        return bool(wanted & set(self.role_names))

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    def is_locked(self, now: datetime | None = None) -> bool:
        if self.locked_until is None:
            return False
        return self.locked_until > (now or utcnow())


class UserRole(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_roles"
    __table_args__ = (sa.UniqueConstraint("user_id", "role", name="uq_user_roles_user_id_role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[Role] = mapped_column(enum_col(Role, "role"), nullable=False, index=True)
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])


class AuthIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A verified login identifier (phone or email) attached to a user."""

    __tablename__ = "auth_identities"
    __table_args__ = (sa.UniqueConstraint("kind", "value", name="uq_auth_identities_kind_value"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[AuthIdentityKind] = mapped_column(
        enum_col(AuthIdentityKind, "auth_identity_kind"), nullable=False
    )
    value: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="identities")


class OTPChallenge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One-time codes. Only the Argon2id hash is persisted."""

    __tablename__ = "otp_challenges"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    identifier: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(sa.String(16), default="sms", nullable=False)
    purpose: Mapped[OTPPurpose] = mapped_column(enum_col(OTPPurpose, "otp_purpose"), nullable=False)
    code_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(sa.Integer, default=5, nullable=False)
    request_ip: Mapped[str | None] = mapped_column(sa.String(64))

    @property
    def is_usable(self) -> bool:
        return (
            self.consumed_at is None
            and self.expires_at > utcnow()
            and self.attempt_count < self.max_attempts
        )


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Opaque refresh tokens, stored as SHA-256 hashes with rotation + reuse
    detection."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(sa.String(64))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True))
    device_label: Mapped[str | None] = mapped_column(sa.String(120))
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    user_agent: Mapped[str | None] = mapped_column(sa.String(255))
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and self.expires_at > utcnow()


class DeviceToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Push notification registration (FCM/APNs token)."""

    __tablename__ = "device_tokens"
    __table_args__ = (sa.UniqueConstraint("token", name="uq_device_tokens_token"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    platform: Mapped[str] = mapped_column(sa.String(16), default="android", nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class UserConsent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One recorded consent decision, per purpose and per policy version.

    Why a table instead of boolean columns on the profile:

      * consent must be *auditable* — who decided what, when, from which client
        and against which version of the policy text;
      * purposes are independent, so a user can allow analytics while refusing
        model training;
      * research/training pipelines can query this table to exclude everyone who
        has not granted the matching purpose (see
        `app.users.consent.ConsentService.training_allowed_user_ids`).

    The row is never mutated into a false history: revoking appends/updates the
    current row and stamps `revoked_at`, and a new policy version creates a new
    row because the previous decision applied to a different document.
    """

    __tablename__ = "user_consents"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "kind", "policy_version", name="uq_user_consents_user_kind_version"
        ),
        sa.Index("ix_user_consents_user_kind", "user_id", "kind"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kind: Mapped[ConsentKind] = mapped_column(
        enum_col(ConsentKind, "consent_kind"), nullable=False, index=True
    )
    granted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    # Both a Python-side default (used by the ORM) and a server default (so a
    # manual/import insert can never produce a row with no decision timestamp).
    decided_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utcnow,
        server_default=sa.text("now()"),
        nullable=False,
    )
    source: Mapped[ConsentSource] = mapped_column(
        enum_col(ConsentSource, "consent_source"), default=ConsentSource.MOBILE_APP, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    app_version: Mapped[str | None] = mapped_column(sa.String(24))
    note: Mapped[str | None] = mapped_column(sa.String(400))

    @property
    def is_active(self) -> bool:
        return self.granted and self.revoked_at is None
