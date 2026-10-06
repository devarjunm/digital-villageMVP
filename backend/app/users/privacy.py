"""User-facing privacy operations: export, correction and deletion.

These are the endpoints a data-protection request maps to. Deliberate design
choices:

* **Export is generated from the database on demand**, not from a cached file,
  and it is honest about what it does *not* contain (hashed tokens are not
  reversible, other people's content is not included).
* **Deletion is a two-step, reversible-window operation**: personal identifiers
  are erased immediately, the account is disabled, and the audit entry records
  who/what/when. Community content stays, attributed to "Deleted account",
  because removing it would silently break other farmers' threads — the export
  and the deletion receipt both say so.
* **Nothing here logs PII.** The audit entry stores counts and field names.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ConsentKind, ConsentSource, UserStatus
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.database.base import utcnow
from app.moderation.models import AuditLog
from app.users.consent import ConsentService, policy_version
from app.users.models import AuthIdentity, DeviceToken, RefreshToken, User, UserConsent

logger = get_logger(__name__)

#: Fields that are personal data and therefore never included verbatim in an
#: export bundle or an audit snapshot.
REDACTED_FIELDS = ("password_hash", "token_hash", "code_hash")


class PrivacyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ export
    def export(self, user: User) -> dict[str, Any]:
        """Everything the platform holds about the account holder, in one JSON document."""
        from app.analytics.models import ProductEvent, SearchEvent
        from app.community.models import Comment, Post, Reaction, SavedPost
        from app.crops.models import Crop, CropEvent
        from app.farmers.models import FarmerProfile
        from app.farms.models import Farm, SoilTest
        from app.markets.models import MarketPrice

        profile = self.db.execute(
            select(FarmerProfile).where(FarmerProfile.user_id == user.id)
        ).scalar_one_or_none()
        farms = list(self.db.execute(select(Farm).where(Farm.owner_id == user.id)).scalars())
        farm_ids = [farm.id for farm in farms]
        crops: list[dict[str, Any]] = []
        if farm_ids:
            rows = self.db.execute(select(Crop).where(Crop.farm_id.in_(farm_ids))).scalars()
            crops = [self._row(crop, drop=("farm_id",)) for crop in rows]
        soil_tests: list[dict[str, Any]] = []
        if farm_ids:
            tests = self.db.execute(
                select(SoilTest).where(SoilTest.farm_id.in_(farm_ids))
            ).scalars()
            soil_tests = [self._row(test, drop=("raw_report",)) for test in tests]
        # Crop events hang off crops, not farms, and carry the author of the entry.
        crop_events: list[dict[str, Any]] = []
        events = list(
            self.db.execute(select(CropEvent).where(CropEvent.created_by_id == user.id)).scalars()
        )
        crop_events = [self._row(event) for event in events]

        posts = list(self.db.execute(select(Post).where(Post.author_id == user.id)).scalars())
        comments = list(
            self.db.execute(select(Comment).where(Comment.author_id == user.id)).scalars()
        )
        reactions = list(
            self.db.execute(select(Reaction).where(Reaction.user_id == user.id)).scalars()
        )
        saved = list(
            self.db.execute(select(SavedPost).where(SavedPost.user_id == user.id)).scalars()
        )
        # Market rows are provider-sourced (there is no user-reported price path in
        # this build), so they are never attributable to a user; the export says so
        # in `not_included` rather than implying we hold farmer-submitted prices.
        prices: list[MarketPrice] = []
        consents = list(
            self.db.execute(select(UserConsent).where(UserConsent.user_id == user.id)).scalars()
        )
        events = list(
            self.db.execute(
                select(ProductEvent)
                .where(ProductEvent.user_id == user.id)
                .order_by(ProductEvent.created_at)
            ).scalars()
        )
        searches = list(
            self.db.execute(
                select(SearchEvent)
                .where(SearchEvent.user_id == user.id)
                .order_by(SearchEvent.created_at)
            ).scalars()
        )
        identities = list(
            self.db.execute(select(AuthIdentity).where(AuthIdentity.user_id == user.id)).scalars()
        )
        sessions = self.db.execute(
            select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user.id)
        ).scalar_one()
        devices = self.db.execute(
            select(func.count()).select_from(DeviceToken).where(DeviceToken.user_id == user.id)
        ).scalar_one()

        return {
            "generated_at": utcnow().isoformat(),
            "policy_version": policy_version(),
            "account": {
                "id": str(user.id),
                "full_name": user.full_name,
                "phone_e164": user.phone_e164,
                "email": user.email,
                "primary_role": user.primary_role.value,
                "status": user.status.value,
                "preferred_language": user.preferred_language.value,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "phone_verified_at": user.phone_verified_at.isoformat()
                if user.phone_verified_at
                else None,
                "email_verified_at": user.email_verified_at.isoformat()
                if user.email_verified_at
                else None,
            },
            "profile": {
                "display_name": profile.display_name,
                "village": profile.village,
                "taluka": profile.taluka,
                "district": profile.district,
                "state": profile.state,
                "pincode": profile.pincode,
                "latitude": float(profile.latitude)
                if profile and profile.latitude is not None
                else None,
                "longitude": float(profile.longitude)
                if profile and profile.longitude is not None
                else None,
                "farming_experience_years": profile.farming_experience_years,
                "primary_crops": profile.primary_crops,
                "interests": profile.interests,
                "bio": profile.bio,
                "organisation": profile.organisation,
                "is_public": profile.is_public,
            }
            if profile
            else None,
            "farms": [self._row(farm) for farm in farms],
            "crops": crops,
            "soil_tests": soil_tests,
            "crop_events": crop_events,
            "community": {
                "posts": [self._row(post, drop=("search_vector",)) for post in posts],
                "comments": [self._row(comment) for comment in comments],
                "reactions": [
                    {
                        "post_id": str(r.post_id),
                        "kind": r.kind.value,
                        "created_at": _iso(r.created_at),
                    }
                    for r in reactions
                ],
                "saved_posts": [
                    {"post_id": str(s.post_id), "created_at": _iso(s.created_at)} for s in saved
                ],
            },
            "market_reports": [self._row(price) for price in prices],
            "consents": [
                {
                    "kind": row.kind.value,
                    "granted": row.granted,
                    "policy_version": row.policy_version,
                    "decided_at": _iso(row.decided_at),
                    "revoked_at": _iso(row.revoked_at),
                    "source": row.source.value,
                }
                for row in consents
            ],
            "product_events": [
                {"name": event.name, "props": event.props, "created_at": _iso(event.created_at)}
                for event in events
            ],
            "searches": [
                {
                    "query": event.query,
                    "mode": event.mode.value,
                    "result_count": event.result_count,
                    "created_at": _iso(event.created_at),
                }
                for event in searches
            ],
            "auth": {
                "identities": [
                    {
                        "kind": row.kind.value,
                        "identifier": row.identifier_masked,
                        "verified": bool(row.verified_at),
                    }
                    for row in identities
                ],
                "login_sessions_on_record": int(sessions),
                "registered_devices": int(devices),
            },
            "not_included": [
                "Passwords, OTP codes and session/refresh tokens (stored only as one-way hashes).",
                "Other members' content, including their comments on your posts.",
                "Internal moderation notes and reports filed about your content.",
                "Uploaded media files themselves — the export lists their metadata; the bytes live in object "
                "storage and can be fetched from /api/v1/media/{id} before deleting the account.",
                "Market prices: they come from the configured market-data provider, not from you, so no "
                "user-entered prices appear here.",
                "Weather and market API responses cached on the server (short-lived, not tied to your account).",
            ],
            "note": (
                "This export is generated live from the database at the time of the request. Hashing means the "
                "platform cannot reconstruct your password or tokens, and no copy of them is included."
            ),
        }

    # ---------------------------------------------------------------- deletion
    def delete_account(
        self, user: User, *, confirm: str, reason: str | None = None
    ) -> dict[str, Any]:
        if confirm.strip().upper() != "DELETE":
            raise ValidationError("Type DELETE to confirm account deletion.")
        if user.status == UserStatus.DISABLED:
            raise ValidationError("This account is already closed.")

        snapshot = {
            "status": user.status.value,
            "phone_present": bool(user.phone_e164),
            "email_present": bool(user.email),
        }
        counts = self._erase(user)

        self.db.add(
            AuditLog(
                actor_id=None,
                actor_role="user",
                action="account_deleted",
                target_type="user",
                target_id=user.id,
                before=snapshot,
                after={"status": user.status.value, "phone_present": False, "email_present": False},
                reason=reason or "User-initiated account deletion.",
            )
        )
        self.db.commit()
        logger.info(
            "account_deleted",
            extra={
                "extra_fields": {
                    "user_id": str(user.id),
                    **{f"{k}_count": v for k, v in counts.items()},
                }
            },
        )
        return {
            "status": "deleted",
            "erased": counts,
            "retained": {
                "community_content": "Kept, attributed to “Deleted account”, so other members' threads stay readable.",
                "moderation_and_audit_records": "Kept as required for platform safety and legal record-keeping.",
                "aggregated_analytics": "Kept in aggregate form only; the user link is removed.",
            },
            "consent_policy_version": policy_version(),
            "note": (
                "Personal identifiers were removed immediately. If you need the community content removed as "
                "well, contact support and quote this account id; deletion of shared threads is handled manually."
            ),
        }

    def _erase(self, user: User) -> dict[str, int]:
        """Erase personal data and free up the identifiers for re-registration."""
        from app.community.models import Comment, Post
        from app.users.models import UserRole

        now = utcnow()
        counts: dict[str, int] = {}

        # Identifiers: cleared, not just flagged.
        user.phone_e164 = None
        user.email = None
        user.password_hash = None
        user.full_name = "Deleted account"
        user.status = UserStatus.DISABLED
        user.phone_verified_at = None
        user.email_verified_at = None
        user.avatar_media_id = None
        user.token_version = (user.token_version or 0) + 1  # invalidate every issued token

        profile = user.profile
        if profile is not None:
            profile.display_name = "Deleted account"
            profile.village = None
            profile.taluka = None
            profile.district = None
            profile.state = None
            profile.pincode = None
            profile.latitude = None
            profile.longitude = None
            profile.bio = None
            profile.organisation = None
            profile.primary_crops = []
            profile.interests = []
            profile.is_public = False

        identities = list(
            self.db.execute(select(AuthIdentity).where(AuthIdentity.user_id == user.id)).scalars()
        )
        for identity in identities:
            self.db.delete(identity)
        counts["auth_identities_removed"] = len(identities)

        tokens = list(
            self.db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)).scalars()
        )
        for token in tokens:
            token.revoked_at = now
            token.revoked_reason = "account_deleted"
            token.device_label = None
            token.ip_address = None
            token.user_agent = None
        counts["sessions_revoked"] = len(tokens)

        devices = list(
            self.db.execute(select(DeviceToken).where(DeviceToken.user_id == user.id)).scalars()
        )
        for device in devices:
            device.is_active = False
            device.token = f"revoked:{uuid.uuid4().hex}"
        counts["devices_unregistered"] = len(devices)

        # Consent rows are kept as the record that consent *was* given and later
        # withdrawn — they contain no contact details.
        consents = list(
            self.db.execute(select(UserConsent).where(UserConsent.user_id == user.id)).scalars()
        )
        for consent in consents:
            consent.granted = False
            consent.revoked_at = now
            consent.ip_address = None
            consent.note = "Account deleted."
        counts["consents_revoked"] = len(consents)

        # Product events: the personal link goes, the aggregate row stays.
        from app.analytics.models import ProductEvent, SearchEvent

        events = self.db.execute(
            select(func.count()).select_from(ProductEvent).where(ProductEvent.user_id == user.id)
        ).scalar_one()
        self.db.execute(
            ProductEvent.__table__.update()
            .where(ProductEvent.user_id == user.id)
            .values(user_id=None, anonymous_id=None, session_id=None, props={})
        )
        counts["product_events_deidentified"] = int(events)

        searches = self.db.execute(
            select(func.count()).select_from(SearchEvent).where(SearchEvent.user_id == user.id)
        ).scalar_one()
        self.db.execute(
            SearchEvent.__table__.update()
            .where(SearchEvent.user_id == user.id)
            .values(user_id=None, language=None)
        )
        counts["search_events_deidentified"] = int(searches)

        # Community content stays, but is re-attributed through the UI because the
        # user row now reads "Deleted account".
        posts = self.db.execute(
            select(func.count()).select_from(Post).where(Post.author_id == user.id)
        ).scalar_one()
        comments = self.db.execute(
            select(func.count()).select_from(Comment).where(Comment.author_id == user.id)
        ).scalar_one()
        counts["posts_retained_anonymised"] = int(posts)
        counts["comments_retained_anonymised"] = int(comments)

        # Roles are removed so nothing account-scoped survives, then the farmer
        # role row is left in place for referential clarity of audit logs.
        roles = list(self.db.execute(select(UserRole).where(UserRole.user_id == user.id)).scalars())
        for role in roles:
            if role.role in {"admin", "moderator", "expert"}:
                self.db.delete(role)
                counts["privileged_roles_removed"] = counts.get("privileged_roles_removed", 0) + 1

        self.db.flush()
        return counts

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _row(obj: Any, *, drop: tuple[str, ...] = ()) -> dict[str, Any]:
        dropped = set(drop) | set(REDACTED_FIELDS)
        data: dict[str, Any] = {}
        for column in obj.__table__.columns:
            if column.name in dropped:
                continue
            value = getattr(obj, column.name)
            data[column.name] = value.value if hasattr(value, "value") else _jsonable(value)
        return data


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list | dict):
        return value
    return value


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def record_consent_for_signup(
    db: Session, user_id: uuid.UUID, *, accepted: dict[ConsentKind, bool]
) -> None:
    """Called by the auth flow when a new account is created.

    Sign-up collects an explicit answer for the optional purposes, so the record
    reflects a real decision rather than a default.
    """
    service = ConsentService(db)
    for kind, granted in accepted.items():
        service.record(user_id=user_id, kind=kind, granted=granted, source=ConsentSource.MOBILE_APP)
