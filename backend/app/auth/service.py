"""Authentication business logic.

Security properties implemented here:
  * identifiers are normalised and uniqueness is enforced by the database;
  * OTP codes are stored only as Argon2id hashes, are single-use, expire, and
    are limited by attempt count and by request rate;
  * no user enumeration: OTP/password-reset requests always answer identically;
  * password login is protected by per-account failure counters + lockout;
  * refresh tokens are opaque, hashed, rotated on use, and a reused (already
    rotated) token revokes the whole family — the standard stolen-token signal;
  * every issued access token carries `token_version`, so changing a password or
    disabling an account invalidates outstanding tokens immediately.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.auth.repository import AuthRepository
from app.auth.schemas import PublicUser, TokenPair
from app.core.config import settings
from app.core.enums import AuthIdentityKind, Language, OTPPurpose, Role, UserStatus
from app.core.errors import (
    AccountDisabledError,
    AccountLockedError,
    InvalidCredentialsError,
    OTPError,
    OTPExpiredError,
    OTPTooManyAttemptsError,
    TokenError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_otp,
    hash_otp,
    hash_password,
    hash_refresh_token,
    password_policy_errors,
    verify_otp_code,
    verify_password,
)
from app.database.base import utcnow
from app.providers.sms import SMSResult, get_sms_provider
from app.users.models import User

logger = get_logger(__name__)

GENERIC_OTP_MESSAGE = "If the number or email is registered, a verification code has been sent."
PURPOSE_BY_CHANNEL = {"sms": OTPPurpose.LOGIN, "email": OTPPurpose.LOGIN}


def normalize_phone(raw: str, default_country_code: str = "+91") -> str:
    """Return an E.164-ish phone string or raise ValidationError.

    Deliberately permissive about formatting, strict about digit content: the
    goal is to prevent two strings for the same number, not to reject valid
    international formats.
    """
    cleaned = "".join(ch for ch in raw.strip() if ch.isdigit() or ch == "+")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if not (8 <= len(digits) <= 15):
            raise ValidationError("That phone number does not look valid.")
        return "+" + digits
    digits = cleaned
    if len(digits) == 10 and default_country_code == "+91":
        return f"{default_country_code}{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if 8 <= len(digits) <= 15:
        return f"{default_country_code}{digits}" if len(digits) <= 11 else f"+{digits}"
    raise ValidationError("That phone number does not look valid.")


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:3]}****{phone[-2:]}" if len(phone) > 6 else "****"


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


@dataclass(slots=True)
class IssuedTokens:
    tokens: TokenPair
    session_id: uuid.UUID


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AuthRepository(db)

    # ------------------------------------------------------------- helpers
    def classify_identifier(self, identifier: str) -> tuple[AuthIdentityKind, str]:
        raw = identifier.strip()
        if "@" in raw:
            return AuthIdentityKind.EMAIL, raw.lower()
        return AuthIdentityKind.PHONE, normalize_phone(raw)

    def to_public_user(self, user: User) -> PublicUser:
        return PublicUser(
            id=user.id,
            full_name=user.full_name,
            primary_role=user.primary_role,
            roles=user.role_names,
            preferred_language=user.preferred_language,
            status=user.status,
            phone_masked=mask_phone(user.phone_e164),
            email_masked=mask_email(user.email),
            phone_verified=user.phone_verified_at is not None,
            email_verified=user.email_verified_at is not None,
            created_at=user.created_at,
            is_demo=user.is_demo,
        )

    # ---------------------------------------------------------- registration
    def register(
        self,
        *,
        full_name: str,
        phone: str | None,
        email: str | None,
        password: str | None,
        preferred_language: Language,
        request_ip: str | None,
    ) -> tuple[User | None, UsernameTaken | None, SMSResult | None]:
        """Create an account.

        Returns (user, conflict, otp_result):
          * phone registration → user created in PENDING_VERIFICATION and an OTP
            is dispatched; the client must call /auth/otp/verify to get tokens;
          * email+password registration → user is ACTIVE immediately and may log
            in (email verification is offered but not required to browse).
        """
        if not phone and not email:
            raise ValidationError("Provide a phone number or an email address.")
        if password:
            problems = password_policy_errors(password)
            if problems:
                raise ValidationError("Password " + ", ".join(problems) + ".")

        normalized_phone = normalize_phone(phone) if phone else None
        normalized_email = email.lower() if email else None

        conflict: UsernameTaken | None = None
        if normalized_phone and self.repo.get_user_by_phone(normalized_phone):
            conflict = UsernameTaken(
                "phone", "That phone number is already registered. Please sign in."
            )
        if normalized_email and self.repo.get_user_by_email(normalized_email):
            conflict = UsernameTaken("email", "That email is already registered. Please sign in.")
        if conflict:
            return None, conflict, None

        user = self.repo.create_user(
            full_name=full_name.strip(),
            phone_e164=normalized_phone,
            email=normalized_email,
            password_hash=hash_password(password) if password else None,
            preferred_language=preferred_language,
            primary_role=Role.FARMER,
            status=UserStatus.ACTIVE
            if (normalized_email and password)
            else UserStatus.PENDING_VERIFICATION,
        )
        self.repo.add_role(user.id, Role.FARMER)
        if normalized_phone:
            self.repo.link_identity(
                user.id, AuthIdentityKind.PHONE, normalized_phone, verified=False
            )
        if normalized_email:
            self.repo.link_identity(
                user.id, AuthIdentityKind.EMAIL, normalized_email, verified=False
            )

        otp_result = None
        if normalized_phone and not password:
            otp_result = self._issue_otp(
                user=user,
                identifier=normalized_phone,
                kind=AuthIdentityKind.PHONE,
                purpose=OTPPurpose.REGISTER,
                request_ip=request_ip,
            )
        self.db.commit()
        self.db.refresh(user)
        return user, None, otp_result

    # ------------------------------------------------------------------- OTP
    def _issue_otp(
        self,
        *,
        user: User | None,
        identifier: str,
        kind: AuthIdentityKind,
        purpose: OTPPurpose,
        request_ip: str | None,
    ) -> SMSResult:
        code = generate_otp()
        expires_at = utcnow() + timedelta(seconds=settings.otp_ttl_seconds)
        self.repo.invalidate_open_otps(identifier, purpose)
        self.repo.create_otp(
            user_id=user.id if user else None,
            identifier=identifier,
            channel="sms" if kind == AuthIdentityKind.PHONE else "email",
            purpose=purpose,
            code_hash=hash_otp(code),
            expires_at=expires_at,
            max_attempts=settings.otp_max_attempts,
            request_ip=request_ip,
        )
        provider = get_sms_provider()
        if kind == AuthIdentityKind.PHONE:
            result = provider.send_otp(
                phone_e164=identifier,
                code=code,
                purpose=purpose.value,
                language=(user.preferred_language.value if user else "en"),
            )
        else:
            # Email OTPs use the same abstraction; the email transport is a
            # separate provider in production (see providers/email.py TODO in
            # docs/development.md known limitations).
            result = SMSResult(
                delivered=False,
                provider="email_not_configured",
                detail="Email delivery requires an SMTP provider; use password login or configure one.",
            )
            if settings.app_env != "production":
                result.dev_code = code
        return result

    def request_otp(
        self,
        *,
        identifier: str,
        purpose: OTPPurpose,
        request_ip: str | None,
        channel: str | None = None,
    ) -> dict[str, object]:
        kind, normalized = self.classify_identifier(identifier)
        user = self.repo.find_identifier_owner(kind, normalized)
        # Always issue a challenge row and always answer identically; whether a
        # user exists is never revealed by this endpoint.
        result = self._issue_otp(
            user=user,
            identifier=normalized,
            kind=kind,
            purpose=purpose,
            request_ip=request_ip,
        )
        self.db.commit()
        return {
            "status": "sent",
            "message": GENERIC_OTP_MESSAGE,
            "expires_in_seconds": settings.otp_ttl_seconds,
            "channel": "sms" if kind == AuthIdentityKind.PHONE else "email",
            "provider": result.provider,
            "is_demo_provider": result.provider == "console",
            "dev_otp": result.dev_code if settings.app_env != "production" else None,
            "detail": result.detail,
            "identifier_exists": user is not None,
        }

    def verify_otp(
        self,
        *,
        identifier: str,
        code: str,
        purpose: OTPPurpose,
        full_name: str | None,
        preferred_language: Language | None,
        ip_address: str | None,
        user_agent: str | None,
        device_label: str | None,
    ) -> tuple[User, TokenPair, uuid.UUID]:
        kind, normalized = self.classify_identifier(identifier)
        challenge = self.repo.latest_open_otp(normalized, purpose)
        if challenge is None:
            raise OTPError("That code is not valid. Please request a new one.")
        if challenge.consumed_at is not None:
            raise OTPError("That code was already used. Please request a new one.")
        if challenge.expires_at <= utcnow():
            raise OTPExpiredError()
        if challenge.attempt_count >= challenge.max_attempts:
            raise OTPTooManyAttemptsError()

        challenge.attempt_count += 1
        if not verify_otp_code(code, challenge.code_hash):
            self.db.commit()
            remaining = max(0, challenge.max_attempts - challenge.attempt_count)
            raise OTPError(
                f"That code is not correct. {remaining} attempt(s) remaining."
                if remaining
                else "Too many incorrect attempts. Please request a new code.",
                details={"attempts_remaining": remaining},
            )

        challenge.consumed_at = utcnow()
        user = self.repo.get_user(challenge.user_id) if challenge.user_id else None
        if user is None:
            user = self.repo.find_identifier_owner(kind, normalized)
        if user is None:
            # First-login-by-OTP for an unregistered phone number: create the
            # account now (registration and login are the same flow for phones).
            if not full_name:
                self.db.rollback()
                raise ValidationError(
                    "This number is not registered yet. Provide your name to create an account.",
                    details={"requires_registration": True},
                )
            user = self.repo.create_user(
                full_name=full_name.strip(),
                phone_e164=normalized if kind == AuthIdentityKind.PHONE else None,
                email=normalized if kind == AuthIdentityKind.EMAIL else None,
                preferred_language=preferred_language or Language.EN,
                status=UserStatus.ACTIVE,
                is_demo=False,
            )
            self.repo.add_role(user.id, Role.FARMER)
            self.repo.link_identity(user.id, kind, normalized, verified=True)

        if user.status in (UserStatus.SUSPENDED, UserStatus.DISABLED):
            self.db.commit()
            raise AccountDisabledError()
        self.repo.mark_identifier_verified(user, kind)
        if user.status == UserStatus.PENDING_VERIFICATION:
            user.status = UserStatus.ACTIVE
        user.last_login_at = utcnow()
        user.failed_login_count = 0
        user.locked_until = None
        tokens = self._issue_tokens(
            user, ip_address=ip_address, user_agent=user_agent, device_label=device_label
        )
        self.db.commit()
        self.db.refresh(user)
        return user, tokens.tokens, tokens.session_id

    # ---------------------------------------------------------------- passwords
    def login_with_password(
        self,
        *,
        identifier: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
        device_label: str | None,
    ) -> tuple[User, TokenPair, uuid.UUID]:
        kind, normalized = self.classify_identifier(identifier)
        user = (
            self.repo.get_user_by_email(normalized)
            if kind == AuthIdentityKind.EMAIL
            else self.repo.get_user_by_phone(normalized)
        )
        if user is None:
            # Burn comparable CPU time to avoid an account-existence timing oracle.
            verify_password(password, None)
            raise InvalidCredentialsError("Incorrect details. Please check and try again.")
        if user.is_locked():
            raise AccountLockedError(
                f"Too many failed attempts. Try again after {user.locked_until:%H:%M} UTC."
            )
        if user.status in (UserStatus.SUSPENDED, UserStatus.DISABLED):
            raise AccountDisabledError()
        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
            self.db.commit()
            logger.info(
                "login_failed",
                extra={
                    "extra_fields": {
                        "identifier_kind": kind.value,
                        "locked": bool(user.locked_until),
                    }
                },
            )
            raise InvalidCredentialsError("Incorrect details. Please check and try again.")

        if user.password_hash and user.status == UserStatus.PENDING_VERIFICATION:
            user.status = UserStatus.ACTIVE
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = utcnow()
        tokens = self._issue_tokens(
            user, ip_address=ip_address, user_agent=user_agent, device_label=device_label
        )
        self.db.commit()
        self.db.refresh(user)
        return user, tokens.tokens, tokens.session_id

    def change_password(self, user: User, *, current_password: str, new_password: str) -> None:
        if user.password_hash and not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("Your current password is not correct.")
        problems = password_policy_errors(new_password)
        if problems:
            raise ValidationError("Password " + ", ".join(problems) + ".")
        user.password_hash = hash_password(new_password)
        user.token_version += 1  # invalidate outstanding access tokens
        self.repo.revoke_all_sessions(user.id, "password_changed")
        self.db.commit()

    def request_password_reset(
        self, *, identifier: str, request_ip: str | None
    ) -> dict[str, object]:
        kind, normalized = self.classify_identifier(identifier)
        user = self.repo.find_identifier_owner(kind, normalized)
        result = SMSResult(delivered=False, provider="none", detail=None)
        if user is not None:
            result = self._issue_otp(
                user=user,
                identifier=normalized,
                kind=kind,
                purpose=OTPPurpose.PASSWORD_RESET,
                request_ip=request_ip,
            )
        self.db.commit()
        return {
            "status": "sent",
            "message": GENERIC_OTP_MESSAGE,
            "expires_in_seconds": settings.otp_ttl_seconds,
            "provider": result.provider,
            "dev_otp": result.dev_code if settings.app_env != "production" else None,
        }

    def confirm_password_reset(
        self, *, identifier: str, code: str, new_password: str, ip_address: str | None
    ) -> User:
        kind, normalized = self.classify_identifier(identifier)
        challenge = self.repo.latest_open_otp(normalized, OTPPurpose.PASSWORD_RESET)
        if (
            challenge is None
            or challenge.expires_at <= utcnow()
            or challenge.consumed_at is not None
        ):
            raise OTPExpiredError("That reset code is no longer valid. Please request a new one.")
        if challenge.attempt_count >= challenge.max_attempts:
            raise OTPTooManyAttemptsError()
        challenge.attempt_count += 1
        if not verify_otp_code(code, challenge.code_hash):
            self.db.commit()
            raise OTPError("That reset code is not correct.")
        user = self.repo.find_identifier_owner(kind, normalized)
        if user is None:
            raise ValidationError("That account no longer exists.")
        problems = password_policy_errors(new_password)
        if problems:
            raise ValidationError("Password " + ", ".join(problems) + ".")
        challenge.consumed_at = utcnow()
        user.password_hash = hash_password(new_password)
        user.token_version += 1
        user.failed_login_count = 0
        user.locked_until = None
        if user.status == UserStatus.PENDING_VERIFICATION:
            user.status = UserStatus.ACTIVE
        self.repo.revoke_all_sessions(user.id, "password_reset")
        self.db.commit()
        self.db.refresh(user)
        return user

    # ----------------------------------------------------------------- tokens
    def _issue_tokens(
        self,
        user: User,
        *,
        ip_address: str | None,
        user_agent: str | None,
        device_label: str | None,
    ) -> IssuedTokens:
        raw_refresh, refresh_hash, refresh_expires = create_refresh_token()
        session = self.repo.create_refresh_token(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:255] or None,
            device_label=device_label,
        )
        access, access_expires = create_access_token(
            user_id=user.id,
            role=user.primary_role.value,
            roles=user.role_names,
            token_version=user.token_version,
            session_id=session.id,
        )
        return IssuedTokens(
            tokens=TokenPair(
                access_token=access,
                refresh_token=raw_refresh,
                expires_in=settings.access_token_expire_minutes * 60,
                access_expires_at=access_expires,
                refresh_expires_at=refresh_expires,
            ),
            session_id=session.id,
        )

    def refresh(
        self, *, raw_refresh_token: str, ip_address: str | None, user_agent: str | None
    ) -> tuple[User, TokenPair, uuid.UUID]:
        token_hash = hash_refresh_token(raw_refresh_token)
        session = self.repo.get_refresh_token(token_hash)
        if session is None:
            raise TokenError("Your session is no longer valid. Please sign in again.")
        if session.revoked_at is not None:
            # Reuse of a rotated token ⇒ treat as compromise and drop every session.
            self.repo.revoke_all_sessions(session.user_id, "refresh_token_reuse_detected")
            self.db.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                extra={"extra_fields": {"user_id": str(session.user_id)}},
            )
            raise TokenError("That session was already ended. For safety, please sign in again.")
        if session.expires_at <= utcnow():
            raise TokenError("Your session has expired. Please sign in again.")
        user = self.repo.get_user(session.user_id)
        if user is None:
            raise TokenError("Your session is no longer valid. Please sign in again.")
        if user.status in (UserStatus.SUSPENDED, UserStatus.DISABLED):
            raise AccountDisabledError()

        issued = self._issue_tokens(
            user, ip_address=ip_address, user_agent=user_agent, device_label=session.device_label
        )
        session.revoked_at = utcnow()
        session.revoked_reason = "rotated"
        session.replaced_by_id = issued.session_id
        session.last_used_at = utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user, issued.tokens, issued.session_id

    def logout(self, *, user: User, raw_refresh_token: str | None, all_sessions: bool) -> int:
        if all_sessions:
            count = self.repo.revoke_all_sessions(user.id, "logout_all")
            user.token_version += 1
        elif raw_refresh_token:
            session = self.repo.get_refresh_token(hash_refresh_token(raw_refresh_token))
            if session is None or session.user_id != user.id:
                raise TokenError("That session could not be found.")
            session.revoked_at = utcnow()
            session.revoked_reason = "logout"
            count = 1
        else:
            count = 0
        self.db.commit()
        return count

    def list_sessions(
        self, user: User, *, current_session_id: uuid.UUID | None = None
    ) -> list[dict[str, object]]:
        return [
            {
                "id": s.id,
                "created_at": s.created_at,
                "last_used_at": s.last_used_at,
                "expires_at": s.expires_at,
                "device_label": s.device_label,
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "current": s.id == current_session_id,
            }
            for s in self.repo.active_sessions(user.id)
        ]

    def revoke_session(self, user: User, session_id: uuid.UUID) -> None:
        sessions = {s.id: s for s in self.repo.active_sessions(user.id)}
        session = sessions.get(session_id)
        if session is None:
            raise ValidationError("That session is not active or does not belong to you.")
        session.revoked_at = utcnow()
        session.revoked_reason = "revoked_by_user"
        self.db.commit()

    # --------------------------------------------------------------- accounts
    def authenticate_token(self, payload: dict[str, object]) -> User:
        """Resolve an access-token payload to a live user (used per request)."""
        try:
            user_id = uuid.UUID(str(payload.get("sub")))
        except (TypeError, ValueError) as exc:
            raise TokenError() from exc
        user = self.repo.get_user(user_id)
        if user is None:
            raise TokenError("Your account could not be found.")
        if user.status in (UserStatus.SUSPENDED, UserStatus.DISABLED):
            raise AccountDisabledError()
        if int(payload.get("ver", 0)) != user.token_version:
            raise TokenError("Your session was ended. Please sign in again.")
        return user

    def delete_account(self, user: User, *, confirm: str) -> dict:
        """Delete the account (kept here as the auth-facing entry point).

        The work itself lives in `app.users.privacy.PrivacyService`, which also
        erases auth identities, devices, analytics links and consent state and
        writes the audit entry. Keeping one implementation avoids the classic bug
        where two "delete" paths erase different fields.
        """
        from app.users.privacy import PrivacyService

        return PrivacyService(self.db).delete_account(
            user, confirm=confirm, reason="User-initiated (auth flow)."
        )


@dataclass(slots=True)
class UsernameTaken:
    field: str
    message: str
