"""User-related queries (counts, search)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.community.models import Follow, Post
from app.core.enums import ContentStatus, Role, UserStatus
from app.farmers.models import FarmerProfile
from app.users.models import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def post_count(self, user_id: uuid.UUID) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(Post)
                .where(
                    Post.author_id == user_id,
                    Post.status == ContentStatus.PUBLISHED,
                    Post.deleted_at.is_(None),
                )
            ).scalar_one()
        )

    def follower_counts(self, user_id: uuid.UUID) -> tuple[int, int]:
        followers = int(
            self.db.execute(
                select(func.count()).select_from(Follow).where(Follow.followee_id == user_id)
            ).scalar_one()
        )
        following = int(
            self.db.execute(
                select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
            ).scalar_one()
        )
        return followers, following

    def is_following(self, follower_id: uuid.UUID | None, followee_id: uuid.UUID) -> bool:
        if follower_id is None or follower_id == followee_id:
            return False
        return (
            self.db.execute(
                select(Follow.id).where(
                    Follow.follower_id == follower_id, Follow.followee_id == followee_id
                )
            ).scalar_one_or_none()
            is not None
        )

    def search(
        self, *, query: str, limit: int = 20, exclude_id: uuid.UUID | None = None
    ) -> list[tuple[User, FarmerProfile | None]]:
        pattern = f"%{query.strip()}%"
        stmt = (
            select(User, FarmerProfile)
            .outerjoin(FarmerProfile, FarmerProfile.user_id == User.id)
            .where(
                User.status == UserStatus.ACTIVE,
                or_(
                    User.full_name.ilike(pattern),
                    FarmerProfile.display_name.ilike(pattern),
                    FarmerProfile.village.ilike(pattern),
                    FarmerProfile.district.ilike(pattern),
                ),
            )
            .order_by(User.full_name)
            .limit(limit)
        )
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return [(row[0], row[1]) for row in self.db.execute(stmt).all()]

    def experts(
        self, *, crop: str | None = None, limit: int = 20
    ) -> list[tuple[User, FarmerProfile | None]]:
        stmt = (
            select(User, FarmerProfile)
            .outerjoin(FarmerProfile, FarmerProfile.user_id == User.id)
            .where(
                User.status == UserStatus.ACTIVE,
                User.primary_role.in_([Role.EXPERT, Role.MODERATOR, Role.ADMIN]),
            )
            .order_by(User.full_name)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in self.db.execute(stmt).all()]
