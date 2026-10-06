"""Data access for identity/authentication tables. No business rules here."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuthIdentityKind, OTPPurpose, UserStatus
from app.database.base import utcnow
from app.users.models import AuthIdentity, OTPChallenge, RefreshToken, User, UserRole


class AuthRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ users
    def get_user(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def get_user_by_phone(self, phone_e164: str) -> User | None:
        return self.db.execute(
            select(User).where(User.phone_e164 == phone_e164)
        ).scalar_one_or_none()

    def get_user_by_email(self, email: str) -> User | None:
        return self.db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()

    def get_user_by_identifier(self, identifier: str) -> User | None:
        if "@" in identifier:
            return self.get_user_by_email(identifier)
        return self.get_user_by_phone(identifier)

    def find_identifier_owner(self, kind: AuthIdentityKind, value: str) -> User | None:
        identity = self.db.execute(
            select(AuthIdentity).where(AuthIdentity.kind == kind, AuthIdentity.value == value)
        ).scalar_one_or_none()
        if identity:
            return self.db.get(User, identity.user_id)
        return self.get_user_by_identifier(value)

    def create_user(self, **fields: object) -> User:
        user = User(**fields)
        self.db.add(user)
        self.db.flush()
        return user

    def add_role(
        self, user_id: uuid.UUID, role, *, granted_by_id: uuid.UUID | None = None
    ) -> UserRole:
        existing = self.db.execute(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role == role)
        ).scalar_one_or_none()
        if existing:
            return existing
        row = UserRole(user_id=user_id, role=role, granted_by_id=granted_by_id)
        self.db.add(row)
        self.db.flush()
        return row

    def link_identity(
        self, user_id: uuid.UUID, kind: AuthIdentityKind, value: str, *, verified: bool = False
    ) -> AuthIdentity:
        row = AuthIdentity(
            user_id=user_id,
            kind=kind,
            value=value,
            is_primary=True,
            verified_at=utcnow() if verified else None,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def mark_identifier_verified(self, user: User, kind: AuthIdentityKind) -> None:
        now = utcnow()
        if kind == AuthIdentityKind.PHONE:
            user.phone_verified_at = now
        else:
            user.email_verified_at = now
        identity = self.db.execute(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user.id,
                AuthIdentity.kind == kind,
            )
        ).scalar_one_or_none()
        if identity:
            identity.verified_at = now
        self.db.flush()

    def set_status(self, user: User, status: UserStatus) -> None:
        user.status = status
        self.db.flush()

    # -------------------------------------------------------------------- OTP
    def create_otp(
        self,
        *,
        user_id: uuid.UUID | None,
        identifier: str,
        channel: str,
        purpose: OTPPurpose,
        code_hash: str,
        expires_at: datetime,
        max_attempts: int,
        request_ip: str | None,
    ) -> OTPChallenge:
        challenge = OTPChallenge(
            user_id=user_id,
            identifier=identifier,
            channel=channel,
            purpose=purpose,
            code_hash=code_hash,
            expires_at=expires_at,
            max_attempts=max_attempts,
            request_ip=request_ip,
        )
        self.db.add(challenge)
        self.db.flush()
        return challenge

    def latest_open_otp(self, identifier: str, purpose: OTPPurpose) -> OTPChallenge | None:
        return (
            self.db.execute(
                select(OTPChallenge)
                .where(
                    OTPChallenge.identifier == identifier,
                    OTPChallenge.purpose == purpose,
                    OTPChallenge.consumed_at.is_(None),
                )
                .order_by(OTPChallenge.created_at.desc())
            )
            .scalars()
            .first()
        )

    def invalidate_open_otps(self, identifier: str, purpose: OTPPurpose) -> int:
        rows = (
            self.db.execute(
                select(OTPChallenge).where(
                    OTPChallenge.identifier == identifier,
                    OTPChallenge.purpose == purpose,
                    OTPChallenge.consumed_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        now = utcnow()
        for row in rows:
            row.consumed_at = now
        self.db.flush()
        return len(rows)

    def count_recent_otps(self, identifier: str, since: datetime) -> int:
        rows = (
            self.db.execute(
                select(OTPChallenge).where(
                    OTPChallenge.identifier == identifier, OTPChallenge.created_at >= since
                )
            )
            .scalars()
            .all()
        )
        return len(rows)

    # ---------------------------------------------------------------- sessions
    def create_refresh_token(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
        device_label: str | None,
    ) -> RefreshToken:
        row = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            device_label=device_label,
            last_used_at=utcnow(),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()

    def active_sessions(self, user_id: uuid.UUID) -> list[RefreshToken]:
        return list(
            self.db.execute(
                select(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > utcnow(),
                )
                .order_by(RefreshToken.created_at.desc())
            )
            .scalars()
            .all()
        )

    def revoke_all_sessions(self, user_id: uuid.UUID, reason: str) -> int:
        rows = (
            self.db.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                )
            )
            .scalars()
            .all()
        )
        now = utcnow()
        for row in rows:
            row.revoked_at = now
            row.revoked_reason = reason
        self.db.flush()
        return len(rows)
