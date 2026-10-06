"""Account-level operations and public profile projection."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.enums import Role, UserStatus
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.logging import get_logger
from app.moderation.models import AuditLog
from app.users.models import User
from app.users.repository import UserRepository
from app.users.schemas import UserPublicProfile, UserSearchResult

logger = get_logger(__name__)


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = UserRepository(db)

    # ------------------------------------------------------------- profiles
    def public_profile(
        self, user_id: uuid.UUID, *, viewer: User | None = None
    ) -> UserPublicProfile:
        user = self.repo.get(user_id)
        if user is None or user.status == UserStatus.DISABLED:
            raise NotFoundError("That member could not be found.")
        profile = user.profile
        if (
            profile is not None
            and not profile.is_public
            and (viewer is None or viewer.id != user.id)
            and not user.has_role(Role.MODERATOR, Role.ADMIN)
        ):
            raise NotFoundError("That member could not be found.")
        followers, following = self.repo.follower_counts(user.id)
        return UserPublicProfile(
            id=user.id,
            full_name=user.full_name,
            primary_role=user.primary_role,
            display_name=profile.display_name if profile else None,
            village=profile.village if profile else None,
            taluka=profile.taluka if profile else None,
            district=profile.district if profile else None,
            state=profile.state if profile else None,
            primary_crops=profile.primary_crops if profile else [],
            interests=profile.interests if profile else [],
            farming_experience_years=profile.farming_experience_years if profile else None,
            organisation=profile.organisation if profile else None,
            bio=profile.bio if profile else None,
            verified_expert=user.has_role(Role.EXPERT),
            post_count=self.repo.post_count(user.id),
            follower_count=followers,
            following_count=following,
            is_following=self.repo.is_following(viewer.id if viewer else None, user.id),
            member_since=user.created_at,
        )

    def search(
        self, *, query: str, limit: int = 20, viewer: User | None = None
    ) -> list[UserSearchResult]:
        if len(query.strip()) < 2:
            raise ValidationError("Please type at least two characters to search.")
        rows = self.repo.search(query=query, limit=limit, exclude_id=viewer.id if viewer else None)
        results: list[UserSearchResult] = []
        for user, profile in rows:
            if profile is not None and not profile.is_public:
                continue
            results.append(
                UserSearchResult(
                    id=user.id,
                    display_name=(profile.display_name if profile else None) or user.full_name,
                    primary_role=user.primary_role,
                    village=profile.village if profile else None,
                    district=profile.district if profile else None,
                    state=profile.state if profile else None,
                    primary_crops=profile.primary_crops if profile else [],
                )
            )
        return results

    # ------------------------------------------------------------ mutation
    def update_account(
        self, user: User, *, full_name: str | None, preferred_language, avatar_media_id, email
    ) -> User:
        if full_name:
            user.full_name = full_name.strip()
        if preferred_language:
            user.preferred_language = preferred_language
        if avatar_media_id is not None:
            from app.media.models import MediaAsset

            asset = self.db.get(MediaAsset, avatar_media_id)
            if asset is None or (asset.owner_id is not None and asset.owner_id != user.id):
                raise NotFoundError("That image was not found in your uploads.")
            user.avatar_media_id = asset.id
        if email and email.lower() != (user.email or ""):
            from sqlalchemy import select

            existing = self.db.execute(
                select(User).where(User.email == email.lower())
            ).scalar_one_or_none()
            if existing and existing.id != user.id:
                raise ConflictError("That email is already in use.")
            user.email = email.lower()
            user.email_verified_at = None
            user.status = user.status  # email change requires re-verification in production
        self.db.commit()
        self.db.refresh(user)
        return user

    def admin_update(
        self,
        *,
        actor: User,
        target: User,
        status=None,
        primary_role=None,
        add_role=None,
        remove_role=None,
        reason: str | None = None,
        ip_address: str | None = None,
    ) -> User:
        if target.id == actor.id and (
            status in (UserStatus.DISABLED, UserStatus.SUSPENDED) or add_role or remove_role
        ):
            raise PermissionDeniedError("You cannot change your own roles or status.")
        before = {
            "status": target.status.value,
            "primary_role": target.primary_role.value,
            "roles": target.role_names,
        }
        if status:
            target.status = status
        if add_role:
            from app.users.models import UserRole

            self.db.add(UserRole(user_id=target.id, role=add_role, granted_by_id=actor.id))
        if remove_role:
            from sqlalchemy import delete

            from app.users.models import UserRole

            self.db.execute(
                delete(UserRole).where(UserRole.user_id == target.id, UserRole.role == remove_role)
            )
        if primary_role:
            target.primary_role = primary_role
            self.db.add(UserRole(user_id=target.id, role=primary_role, granted_by_id=actor.id))
        self.db.flush()
        self.db.refresh(target)
        self.db.add(
            AuditLog(
                actor_id=actor.id,
                actor_role=actor.primary_role.value,
                action="user.update",
                target_type="user",
                target_id=target.id,
                before=before,
                after={
                    "status": target.status.value,
                    "primary_role": target.primary_role.value,
                    "roles": target.role_names,
                },
                reason=reason,
                ip_address=ip_address,
            )
        )
        self.db.commit()
        self.db.refresh(target)
        logger.info(
            "admin_user_updated",
            extra={"extra_fields": {"actor": str(actor.id), "target": str(target.id), **before}},
        )
        return target
