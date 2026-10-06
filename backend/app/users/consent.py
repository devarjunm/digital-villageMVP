"""Per-purpose consent: recording, checking and enforcing.

This module is the single place that answers the question "may we do X with this
user's data?". Three rules the rest of the codebase must respect:

1. **Never assume consent.** A purpose with no recorded decision is *not*
   granted. `has_consent()` returns False and `require()` raises, so a missing
   migration or a new client cannot silently opt a user in.
2. **Consent is versioned.** A decision applies to a specific
   `policy_version`. When the platform's privacy text changes, bump
   `POLICY_VERSION`; every user is then out of consent for that purpose until
   they decide again, and `pending_user_ids()` finds them.
3. **Revocation is recorded, not deleted.** Audit needs the history; the
   training/analytics pipelines only look at rows where `granted` is true and
   `revoked_at` is null.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import ConsentKind, ConsentSource, UserStatus
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.database.base import utcnow
from app.users.models import User, UserConsent

logger = get_logger(__name__)


def policy_version() -> str:
    """The version of the privacy/consent text that decisions refer to.

    Read from settings (`CONSENT_POLICY_VERSION`) on every call rather than
    frozen at import, so a policy change is a configuration change and tests can
    exercise the "user answered an older version" path.
    """
    return settings.consent_policy_version


#: Convenience constant for callers that only need the current value at import
#: time (documentation, seeds). Prefer `policy_version()` in request handling.
POLICY_VERSION = settings.consent_policy_version

#: Purposes that are answered by the platform's own terms acceptance flow and
#: therefore have to be granted for an account to be fully usable.
#: (Analytics, training, marketing and research are explicitly *not* here.)
REQUIRED_KINDS: frozenset[ConsentKind] = frozenset()

#: Human-readable explanation of each purpose, surfaced to the app so the
#: consent screen never has to invent its own wording.
PURPOSE_DESCRIPTIONS: dict[ConsentKind, dict[str, str]] = {
    ConsentKind.ANALYTICS: {
        "title": "Product analytics",
        "description": (
            "Counts which screens and features are used, so the app can be improved. Events are "
            "allow-listed (no free text, no location history, no contacts) and can be exported or "
            "deleted on request. Turning this off does not disable security and error logging."
        ),
        "required": "no",
    },
    ConsentKind.MODEL_TRAINING: {
        "title": "Using your content to train models",
        "description": (
            "Allows your public posts, photos and feedback to be included in datasets that train or "
            "evaluate the platform's agricultural models. Content stays attributable to you, you can "
            "withdraw at any time, and withdrawal is honoured for datasets built after that date."
        ),
        "required": "no",
    },
    ConsentKind.RESEARCH: {
        "title": "Aggregate research and reporting",
        "description": (
            "Allows your anonymised, aggregated data to be used for reports about crop problems and "
            "advisory coverage. Individual farms are never identifiable in published output."
        ),
        "required": "no",
    },
    ConsentKind.PERSONALISATION: {
        "title": "Personalised recommendations",
        "description": (
            "Allows the platform to use your farms, crops and past activity to rank content, schemes and "
            "advisories for you. Turning it off leaves you with the same features, in a non-personalised order."
        ),
        "required": "no",
    },
    ConsentKind.MARKETING: {
        "title": "Product and partner messages",
        "description": (
            "Allows promotional notifications and partner offers. Service messages (security alerts, "
            "moderation outcomes, scheme deadlines you asked about) are unaffected."
        ),
        "required": "no",
    },
    ConsentKind.LOCATION: {
        "title": "Precise location",
        "description": (
            "Allows the app to attach your device location to weather and market requests instead of the "
            "village you selected. Location is used for the request and is not stored as a movement history."
        ),
        "required": "no",
    },
}


class ConsentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ reads
    def current(self, user_id: uuid.UUID, kind: ConsentKind) -> UserConsent | None:
        return (
            self.db.execute(
                select(UserConsent)
                .where(
                    UserConsent.user_id == user_id,
                    UserConsent.kind == kind,
                    UserConsent.policy_version == policy_version(),
                )
                .order_by(UserConsent.decided_at.desc())
            )
            .scalars()
            .first()
        )

    def has_consent(self, user_id: uuid.UUID | None, kind: ConsentKind) -> bool:
        """False when the user is unknown, has no record, or has revoked it."""
        if user_id is None:
            return False
        decision = self.current(user_id, kind)
        return bool(decision and decision.granted and decision.revoked_at is None)

    def require(self, user_id: uuid.UUID | None, kind: ConsentKind, *, action: str) -> None:
        if not self.has_consent(user_id, kind):
            raise ValidationError(
                f"{action} needs your permission for “{PURPOSE_DESCRIPTIONS[kind]['title']}”.",
                details={
                    "consent_kind": kind.value,
                    "policy_version": policy_version(),
                    "how_to_grant": "PATCH /api/v1/users/me/consents",
                },
            )

    def overview(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Everything the consent screen needs in one call."""
        rows = {
            row.kind: row
            for row in self.db.execute(
                select(UserConsent).where(
                    UserConsent.user_id == user_id, UserConsent.policy_version == policy_version()
                )
            ).scalars()
        }
        items = []
        for kind, description in PURPOSE_DESCRIPTIONS.items():
            row = rows.get(kind)
            items.append(
                {
                    "kind": kind.value,
                    "title": description["title"],
                    "description": description["description"],
                    "required": description["required"] == "yes",
                    "granted": bool(row and row.granted and row.revoked_at is None),
                    "decided_at": row.decided_at if row else None,
                    "revoked_at": row.revoked_at if row else None,
                    "source": row.source.value if row else None,
                }
            )
        return {
            "policy_version": policy_version(),
            "items": items,
            "note": (
                "A purpose with no recorded decision counts as refused. Revoking takes effect immediately "
                "for new processing; data already used to train an earlier model version cannot be removed "
                "from that artefact retroactively."
            ),
        }

    # ----------------------------------------------------------------- writes
    def record(
        self,
        *,
        user_id: uuid.UUID,
        kind: ConsentKind,
        granted: bool,
        source: ConsentSource = ConsentSource.MOBILE_APP,
        ip_address: str | None = None,
        app_version: str | None = None,
        note: str | None = None,
    ) -> UserConsent:
        row = self.current(user_id, kind)
        now = utcnow()
        if row is None:
            row = UserConsent(
                user_id=user_id,
                kind=kind,
                granted=granted,
                policy_version=policy_version(),
                decided_at=now,
                source=source,
                ip_address=ip_address,
                app_version=app_version,
                note=note,
                revoked_at=None if granted else now,
            )
            self.db.add(row)
        else:
            row.granted = granted
            row.decided_at = now
            row.source = source
            row.ip_address = ip_address
            row.app_version = app_version
            row.note = note
            row.revoked_at = None if granted else now
        self.db.commit()
        logger.info(
            "consent_recorded",
            extra={
                "extra_fields": {
                    "user_id": str(user_id),
                    "kind": kind.value,
                    "granted": granted,
                    "policy_version": policy_version(),
                    "source": source.value,
                }
            },
        )
        return row

    def record_many(
        self,
        *,
        user_id: uuid.UUID,
        decisions: dict[ConsentKind, bool],
        source: ConsentSource = ConsentSource.MOBILE_APP,
        ip_address: str | None = None,
        app_version: str | None = None,
    ) -> dict[str, Any]:
        for kind, granted in decisions.items():
            self.record(
                user_id=user_id,
                kind=kind,
                granted=granted,
                source=source,
                ip_address=ip_address,
                app_version=app_version,
            )
        return self.overview(user_id)

    # ---------------------------------------------------------- data pipelines
    def training_allowed_user_ids(self, *, only_active: bool = True) -> list[uuid.UUID]:
        """Users whose content may be used to build a training dataset.

        Called by the dataset export tooling (`mlops/datasets`). It is intentionally
        an allow-list computed from recorded consent, not a deny-list, so a user who
        never opened the consent screen is excluded.
        """
        stmt = (
            select(UserConsent.user_id)
            .where(
                UserConsent.kind == ConsentKind.MODEL_TRAINING,
                UserConsent.granted.is_(True),
                UserConsent.revoked_at.is_(None),
                UserConsent.policy_version == policy_version(),
            )
            .distinct()
        )
        if only_active:
            stmt = stmt.join(User, User.id == UserConsent.user_id).where(
                User.status == UserStatus.ACTIVE
            )
        return list(self.db.execute(stmt).scalars())

    def consent_stats(self) -> dict[str, Any]:
        """Aggregate view for the admin privacy panel (counts only, no identities)."""
        stats: dict[str, Any] = {"policy_version": policy_version(), "purposes": {}}
        for kind in ConsentKind:
            granted = self.db.execute(
                select(UserConsent.user_id).where(
                    UserConsent.kind == kind,
                    UserConsent.granted.is_(True),
                    UserConsent.revoked_at.is_(None),
                    UserConsent.policy_version == policy_version(),
                )
            ).scalars()
            decided = self.db.execute(
                select(UserConsent.user_id).where(
                    UserConsent.kind == kind, UserConsent.policy_version == policy_version()
                )
            ).scalars()
            granted_ids = set(granted)
            decided_ids = set(decided)
            stats["purposes"][kind.value] = {
                "granted": len(granted_ids),
                "decided": len(decided_ids),
                "refused_or_revoked": len(decided_ids - granted_ids),
                "never_asked": max(0, self._active_user_count() - len(decided_ids)),
            }
        return stats

    def _active_user_count(self) -> int:
        from sqlalchemy import func

        return int(
            self.db.execute(
                select(func.count()).select_from(User).where(User.status == UserStatus.ACTIVE)
            ).scalar_one()
        )

    @staticmethod
    def describe_purposes() -> dict[str, Any]:
        return {
            "policy_version": policy_version(),
            "purposes": [
                {
                    "kind": kind.value,
                    "title": PURPOSE_DESCRIPTIONS[kind]["title"],
                    "description": PURPOSE_DESCRIPTIONS[kind]["description"],
                    "required": PURPOSE_DESCRIPTIONS[kind]["required"] == "yes",
                }
                for kind in ConsentKind
            ],
        }

    @staticmethod
    def decided_at() -> datetime:
        return utcnow()
