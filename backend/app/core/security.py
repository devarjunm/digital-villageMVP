"""Password/OTP hashing and JWT handling.

Decisions:
  * Argon2id (argon2-cffi) for passwords and OTP codes. No plaintext, ever:
    OTPs are stored only as Argon2id hashes and compared in constant time.
  * Access tokens: short-lived JWT (HS256, secret from env) carrying sub/role/ver.
  * Refresh tokens: opaque 256-bit random strings; only their SHA-256 hash is
    stored (`refresh_tokens.token_hash`), enabling revocation, rotation and
    reuse detection without keeping a usable credential in the database.
  * `token_version` on the user invalidates every issued access token when the
    password changes or an account is disabled.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import TokenError

_hasher = PasswordHasher(
    time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16
)

TOKEN_TYPE = Literal["access", "refresh"]


# --------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # Still burn comparable time to avoid a trivial timing oracle on
        # accounts that authenticate with OTP only.
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def password_policy_errors(password: str) -> list[str]:
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"must be at least {settings.password_min_length} characters")
    if password.isdigit() or password.isalpha():
        problems.append("must contain both letters and numbers")
    if password.lower() in {"password", "12345678", "qwerty123", "password1"}:
        problems.append("is too common")
    return problems


# ------------------------------------------------------------------------- OTPs
def generate_otp(length: int | None = None) -> str:
    length = length or settings.otp_length
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(code: str) -> str:
    return _hasher.hash(code)


def verify_otp_code(code: str, code_hash: str) -> bool:
    try:
        return _hasher.verify(code_hash, code)
    except (VerifyMismatchError, InvalidHashError):
        return False


# ------------------------------------------------------------------- tokens
def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    *,
    user_id: uuid.UUID | str,
    role: str,
    roles: list[str] | None = None,
    token_version: int = 0,
    session_id: uuid.UUID | str | None = None,
    expires_minutes: int | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "roles": roles or [role],
        "ver": token_version,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    return _encode(payload), expires


def create_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, sha256_hash, expires_at). The raw value is returned to
    the client exactly once and never persisted."""
    raw = secrets.token_urlsafe(48)
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    return raw, hash_refresh_token(raw), expires


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Your session has expired. Please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise TokenError() from exc
    if payload.get("type") != "access":
        raise TokenError("Wrong token type.")
    return payload


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def pseudonymize(value: str, *, namespace: str) -> str:
    """Stable, non-reversible fingerprint (used for analytics IDs and model
    monitoring input fingerprints — never for authentication)."""
    return hashlib.sha256(f"{namespace}:{value}".encode()).hexdigest()[:32]
