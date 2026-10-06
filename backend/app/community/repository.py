"""Community persistence queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.community.models import Comment, Follow, Post, Reaction, Report, SavedPost
from app.core.enums import ContentStatus, PostCategory, ReactionKind, ReportStatus, ReportTargetType
from app.core.errors import NotFoundError, ValidationError


class PostRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------- read
    def query_posts(
        self,
        *,
        category: PostCategory | None = None,
        crop_code: str | None = None,
        state: str | None = None,
        district: str | None = None,
        author_id: uuid.UUID | None = None,
        following_of: uuid.UUID | None = None,
        saved_by: uuid.UUID | None = None,
        query: str | None = None,
        include_demo: bool = True,
        only_unanswered: bool = False,
        statuses: tuple[ContentStatus, ...] = (ContentStatus.PUBLISHED,),
    ) -> Select:
        stmt = (
            select(Post)
            .where(Post.deleted_at.is_(None), Post.status.in_(statuses))
            .options(selectinload(Post.media))
        )
        if not include_demo:
            stmt = stmt.where(Post.is_demo.is_(False))
        if category:
            stmt = stmt.where(Post.category == category)
        if crop_code:
            stmt = stmt.where(Post.crop_code == crop_code)
        if state:
            stmt = stmt.where(Post.state == state)
        if district:
            stmt = stmt.where(Post.district == district)
        if author_id:
            stmt = stmt.where(Post.author_id == author_id)
        if only_unanswered:
            stmt = stmt.where(Post.comment_count == 0)
        if following_of:
            stmt = stmt.where(
                Post.author_id.in_(
                    select(Follow.followee_id).where(Follow.follower_id == following_of)
                )
            )
        if saved_by:
            stmt = stmt.where(
                Post.id.in_(select(SavedPost.post_id).where(SavedPost.user_id == saved_by))
            )
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(or_(Post.title.ilike(pattern), Post.body.ilike(pattern)))
        return stmt

    def count(self, stmt: Select) -> int:
        subquery = stmt.order_by(None).options().subquery()
        return int(self.db.execute(select(func.count()).select_from(subquery)).scalar_one())

    def get(self, post_id: uuid.UUID, *, include_removed: bool = False) -> Post:
        post = self.db.get(Post, post_id)
        if post is None or (post.deleted_at is not None and not include_removed):
            raise NotFoundError("That post could not be found.")
        return post

    def author_recent_post_ids(self, author_id: uuid.UUID, *, limit: int = 50) -> list[str]:
        rows = self.db.execute(
            select(Post.id)
            .where(Post.author_id == author_id, Post.deleted_at.is_(None))
            .order_by(Post.created_at.desc())
            .limit(limit)
        ).scalars()
        return [str(row) for row in rows]

    # ------------------------------------------------------------------ write
    def create(self, **fields) -> Post:
        post = Post(**fields)
        self.db.add(post)
        self.db.flush()
        return post

    def increment(self, post: Post, field: str, delta: int = 1) -> None:
        current = getattr(post, field, 0) or 0
        setattr(post, field, max(0, current + delta))

    def soft_delete(self, post: Post) -> None:
        from app.database.base import utcnow

        post.deleted_at = utcnow()
        self.db.flush()

    # -------------------------------------------------------------- reactions
    def get_reaction(
        self,
        *,
        user_id: uuid.UUID,
        post_id: uuid.UUID | None = None,
        comment_id: uuid.UUID | None = None,
    ) -> Reaction | None:
        stmt = select(Reaction).where(Reaction.user_id == user_id)
        stmt = (
            stmt.where(Reaction.post_id == post_id)
            if post_id
            else stmt.where(Reaction.comment_id == comment_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def reactions_for_posts(
        self, *, user_id: uuid.UUID, post_ids: list[uuid.UUID]
    ) -> dict[str, str]:
        if not post_ids:
            return {}
        rows = self.db.execute(
            select(Reaction.post_id, Reaction.kind).where(
                Reaction.user_id == user_id, Reaction.post_id.in_(post_ids)
            )
        ).all()
        return {
            str(post_id): kind.value if hasattr(kind, "value") else str(kind)
            for post_id, kind in rows
        }

    def saved_post_ids(self, *, user_id: uuid.UUID, post_ids: list[uuid.UUID]) -> set[str]:
        if not post_ids:
            return set()
        rows = self.db.execute(
            select(SavedPost.post_id).where(
                SavedPost.user_id == user_id, SavedPost.post_id.in_(post_ids)
            )
        ).scalars()
        return {str(row) for row in rows}

    def add_reaction(
        self,
        *,
        user_id: uuid.UUID,
        kind: ReactionKind,
        post_id: uuid.UUID | None = None,
        comment_id: uuid.UUID | None = None,
    ) -> Reaction:
        if (post_id is None) == (comment_id is None):
            raise ValidationError("A reaction targets exactly one post or comment.")
        existing = self.get_reaction(user_id=user_id, post_id=post_id, comment_id=comment_id)
        if existing:
            existing.kind = kind
            self.db.flush()
            return existing
        reaction = Reaction(user_id=user_id, kind=kind, post_id=post_id, comment_id=comment_id)
        self.db.add(reaction)
        self.db.flush()
        return reaction

    def remove_reaction(
        self,
        *,
        user_id: uuid.UUID,
        post_id: uuid.UUID | None = None,
        comment_id: uuid.UUID | None = None,
    ) -> bool:
        reaction = self.get_reaction(user_id=user_id, post_id=post_id, comment_id=comment_id)
        if reaction is None:
            return False
        self.db.delete(reaction)
        self.db.flush()
        return True

    # --------------------------------------------------------------- comments
    def comment_query(self, post_id: uuid.UUID, *, statuses=(ContentStatus.PUBLISHED,)) -> Select:
        return (
            select(Comment)
            .where(
                Comment.post_id == post_id,
                Comment.deleted_at.is_(None),
                Comment.status.in_(statuses),
            )
            .order_by(Comment.created_at.asc())
        )

    def comments_for(self, post_id: uuid.UUID) -> list[Comment]:
        return list(self.db.execute(self.comment_query(post_id)).scalars())

    def get_comment(self, comment_id: uuid.UUID) -> Comment:
        comment = self.db.get(Comment, comment_id)
        if comment is None or comment.deleted_at is not None:
            raise NotFoundError("That reply could not be found.")
        return comment

    def add_comment(self, **fields) -> Comment:
        comment = Comment(**fields)
        self.db.add(comment)
        self.db.flush()
        return comment

    def soft_delete_comment(self, comment: Comment) -> None:
        from app.database.base import utcnow

        comment.deleted_at = utcnow()
        self.db.flush()

    # ---------------------------------------------------------------- follows
    def follow(self, *, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
        if follower_id == followee_id:
            raise ValidationError("You cannot follow your own account.")
        from app.users.models import User

        if self.db.get(User, followee_id) is None:
            raise NotFoundError("That member could not be found.")
        existing = self.db.execute(
            select(Follow).where(
                Follow.follower_id == follower_id, Follow.followee_id == followee_id
            )
        ).scalar_one_or_none()
        if existing:
            return False
        self.db.add(Follow(follower_id=follower_id, followee_id=followee_id))
        self.db.flush()
        return True

    def unfollow(self, *, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
        result = self.db.execute(
            delete(Follow).where(
                Follow.follower_id == follower_id, Follow.followee_id == followee_id
            )
        )
        self.db.flush()
        return bool(result.rowcount)

    def following_ids(self, user_id: uuid.UUID) -> set[str]:
        rows = self.db.execute(
            select(Follow.followee_id).where(Follow.follower_id == user_id)
        ).scalars()
        return {str(row) for row in rows}

    def follower_count(self, user_id: uuid.UUID) -> int:
        return int(
            self.db.execute(
                select(func.count()).select_from(Follow).where(Follow.followee_id == user_id)
            ).scalar_one()
        )

    # ---------------------------------------------------------------- reports
    def open_report_exists(
        self, *, reporter_id: uuid.UUID, target_type: ReportTargetType, target_id: uuid.UUID
    ) -> bool:
        return (
            self.db.execute(
                select(Report.id).where(
                    Report.reporter_id == reporter_id,
                    Report.target_type == target_type,
                    Report.target_id == target_id,
                )
            ).scalar_one_or_none()
            is not None
        )

    def create_report(self, **fields) -> Report:
        report = Report(**fields)
        self.db.add(report)
        self.db.flush()
        return report

    def reports_for_target(
        self, *, target_type: ReportTargetType, target_id: uuid.UUID
    ) -> list[Report]:
        return list(
            self.db.execute(
                select(Report).where(
                    Report.target_type == target_type, Report.target_id == target_id
                )
            ).scalars()
        )

    def open_report_count(self, *, target_type: ReportTargetType, target_id: uuid.UUID) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(Report)
                .where(
                    Report.target_type == target_type,
                    Report.target_id == target_id,
                    Report.status == ReportStatus.OPEN,
                )
            ).scalar_one()
        )

    # ------------------------------------------------------------- statistics
    def trending_crop_codes(self, *, days: int = 14, limit: int = 8) -> list[tuple[str, int]]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(
            select(Post.crop_code, func.count())
            .where(Post.created_at >= since, Post.crop_code.is_not(None), Post.deleted_at.is_(None))
            .group_by(Post.crop_code)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
        return [(code, int(count)) for code, count in rows]
