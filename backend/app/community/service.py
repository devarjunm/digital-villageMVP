"""Community business logic.

Responsibilities:
  * posts, comments, reactions, saves, follows, reports (with moderation cases);
  * trust labels via app.community.trust (never derived from popularity);
  * feed ranking via app.community.ranking (deterministic, explained in the response);
  * embedding lifecycle: creating/updating a post enqueues an embedding job so
    semantic search works without blocking the request;
  * notification fan-out for replies (deduplicated, respecting preferences).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.community.models import Post, PostEmbedding, PostMedia, Reaction, SavedPost
from app.community.ranking import RankingContext, explanation, rank_posts
from app.community.repository import PostRepository
from app.community.schemas import (
    AuthorBrief,
    CommentCreate,
    CommentOut,
    MediaBrief,
    PostCreate,
    PostOut,
    PostUpdate,
)
from app.community.trust import assess, engagement_note
from app.core.enums import (
    ContentStatus,
    NotificationType,
    PostCategory,
    ReactionKind,
    ReportReason,
    ReportTargetType,
)
from app.core.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
    not_found,
)
from app.core.logging import get_logger
from app.core.pagination import PageParams
from app.media.models import MediaAsset
from app.users.models import User

logger = get_logger(__name__)


class CommunityService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PostRepository(db)

    # ------------------------------------------------------------------ feed
    def _author_brief(
        self, author: User, *, viewer: User | None, following: set[str]
    ) -> AuthorBrief:
        profile = author.profile
        return AuthorBrief(
            id=author.id,
            display_name=(profile.display_name if profile else None) or author.full_name,
            primary_role=author.primary_role.value,
            village=profile.village if profile else None,
            district=profile.district if profile else None,
            state=profile.state if profile else None,
            verified_expert=author.has_role("expert"),
            is_following=str(author.id) in following,
        )

    def _to_out(
        self,
        post: Post,
        *,
        viewer: User | None,
        following: set[str],
        reactions: dict[str, str],
        saved: set[str],
        components: dict[str, float] | None = None,
    ) -> PostOut:
        author = self.db.get(User, post.author_id)
        assert author is not None  # FK guarantees existence
        media = [
            MediaBrief(
                id=item.media_id,
                url=(
                    asset.public_url if (asset := self.db.get(MediaAsset, item.media_id)) else None
                ),
                width=asset.width if asset else None,
                height=asset.height if asset else None,
                mime_type=asset.mime_type if asset else "image/jpeg",
            )
            for item in sorted(post.media, key=lambda m: m.position)
        ]
        assessment = assess(
            author_roles=author.role_names,
            category=post.category.value if hasattr(post.category, "value") else str(post.category),
            source_urls=(post.body and _extract_urls(post.body)) or [],
        )
        attached_farm = None
        if post.farm_id:
            from app.farms.models import Farm

            farm = self.db.get(Farm, post.farm_id)
            if farm is not None:
                attached_farm = {
                    "farm_id": str(farm.id),
                    "name": farm.name,
                    "area_value": float(farm.area_value),
                    "area_unit": farm.area_unit.value,
                    "soil_type": farm.soil_type.value,
                    "irrigation_type": farm.irrigation_type.value,
                    "note": "Farm context was shared voluntarily by the author.",
                }
        return PostOut(
            id=post.id,
            title=post.title,
            body=post.body,
            category=post.category,
            crop_code=post.crop_code,
            language=post.language,
            state=post.state,
            district=post.district,
            village=post.village,
            author=self._author_brief(author, viewer=viewer, following=following),
            media=media,
            source_urls=_extract_urls(post.body),
            trust_label=assessment.label,
            trust_reasons=assessment.reasons,
            engagement={
                "reaction_count": post.reaction_count,
                "comment_count": post.comment_count,
                "save_count": post.save_count,
                "view_count": post.view_count,
                "note": engagement_note(
                    reaction_count=post.reaction_count, comment_count=post.comment_count
                ),
            },
            status=post.status,
            reaction_count=post.reaction_count,
            comment_count=post.comment_count,
            save_count=post.save_count,
            view_count=post.view_count,
            report_count=post.report_count,
            my_reaction=reactions.get(str(post.id)),
            is_saved=str(post.id) in saved,
            attached_farm=attached_farm,
            created_at=post.created_at,
            updated_at=post.updated_at,
            edited_at=post.edited_at,
            is_demo=post.is_demo,
            ranking=components,
        )

    def ranking_context(self, viewer: User | None) -> RankingContext:
        if viewer is None:
            return RankingContext()
        profile = viewer.profile
        from app.crops.models import Crop
        from app.farms.models import Farm

        crops = set(
            self.db.execute(
                select(Crop.crop_code)
                .join(Farm, Farm.id == Crop.farm_id)
                .where(Farm.owner_id == viewer.id)
            ).scalars()
        )
        interacted: dict[str, int] = {}
        for (category,) in self.db.execute(
            select(Post.category).where(Post.author_id == viewer.id).limit(50)
        ).all():
            value = category.value if hasattr(category, "value") else str(category)
            interacted[value] = interacted.get(value, 0) + 1
        return RankingContext(
            viewer_id=str(viewer.id),
            preferred_crop_codes=crops | set(profile.primary_crops if profile else []),
            home_state=profile.state if profile else None,
            home_district=profile.district if profile else None,
            followed_user_ids=self.repo.following_ids(viewer.id),
            interacted_categories=interacted,
        )

    def feed(
        self,
        *,
        params: PageParams,
        viewer: User | None = None,
        category: PostCategory | None = None,
        crop_code: str | None = None,
        state: str | None = None,
        district: str | None = None,
        author_id: uuid.UUID | None = None,
        following_only: bool = False,
        saved_only: bool = False,
        query: str | None = None,
        unanswered_only: bool = False,
        sort: str = "relevance",
        include_demo: bool = True,
    ) -> dict:
        if saved_only and viewer is None:
            raise ValidationError("Sign in to view your saved posts.")
        stmt = self.repo.query_posts(
            category=category,
            crop_code=crop_code,
            state=state,
            district=district,
            author_id=author_id,
            following_of=viewer.id if (following_only and viewer) else None,
            saved_by=viewer.id if (saved_only and viewer) else None,
            query=query,
            include_demo=include_demo,
            only_unanswered=unanswered_only,
        )
        total = self.repo.count(stmt)
        ctx = self.ranking_context(viewer)
        following = ctx.followed_user_ids
        reactions: dict[str, str] = {}
        saved: set[str] = set()

        if sort == "recent":
            rows = list(
                self.db.execute(
                    stmt.order_by(Post.created_at.desc()).limit(params.limit).offset(params.offset)
                ).scalars()
            )
            ranked = rank_posts(rows, context=ctx, include_components=False)
        elif sort == "popular":
            rows = list(
                self.db.execute(
                    stmt.order_by(
                        (Post.reaction_count + Post.comment_count).desc(), Post.created_at.desc()
                    )
                    .limit(params.limit)
                    .offset(params.offset)
                ).scalars()
            )
            ranked = rank_posts(rows, context=ctx, include_components=False)
        else:
            # Rank a bounded candidate window, then paginate within it, so the
            # deterministic ranker sees a comparable pool regardless of page size.
            window = min(400, max(params.offset + params.limit * 4, 120))
            candidates = list(
                self.db.execute(stmt.order_by(Post.created_at.desc()).limit(window)).scalars()
            )
            ranked = rank_posts(candidates, context=ctx)
            ranked = ranked[params.offset : params.offset + params.limit]

        post_ids = [item.post.id for item in ranked]
        if viewer is not None:
            reactions = self.repo.reactions_for_posts(user_id=viewer.id, post_ids=post_ids)
            saved = self.repo.saved_post_ids(user_id=viewer.id, post_ids=post_ids)

        items = [
            self._to_out(
                item.post,
                viewer=viewer,
                following=following,
                reactions=reactions,
                saved=saved,
                components=item.components or None,
            )
            for item in ranked
        ]
        from app.core.pagination import paginate

        payload = paginate(items, params, total)
        payload["ranking"] = explanation(ctx)
        payload["filters"] = {
            "category": category.value if category else None,
            "crop_code": crop_code,
            "state": state,
            "district": district,
            "following_only": following_only,
            "saved_only": saved_only,
            "query": query,
            "unanswered_only": unanswered_only,
            "sort": sort,
        }
        return payload

    # ------------------------------------------------------------------ posts
    def create_post(self, *, payload: PostCreate, user: User) -> PostOut:
        # Moderation restriction check first: a restricted account must be told
        # before anything is validated or written.
        from app.moderation.service import ModerationService

        ModerationService(self.db).assert_capability(user, "post")
        if payload.crop_code:
            from app.crops.service import CropService

            CropService(self.db).get_catalog_entry(payload.crop_code)
        if payload.farm_id:
            from app.farms.repository import FarmRepository

            farm = FarmRepository(self.db).get(payload.farm_id)
            if farm is None or farm.owner_id != user.id:
                not_found()
        if payload.crop_id:
            from app.crops.models import Crop

            crop = self.db.get(Crop, payload.crop_id)
            if crop is None or crop.farm_id != payload.farm_id:
                raise ValidationError("That crop does not belong to the selected farm.")
        for media_id in payload.media_ids:
            asset = self.db.get(MediaAsset, media_id)
            if asset is None:
                raise NotFoundError("One of the attached images was not found.")
            if (
                asset.owner_id is not None
                and asset.owner_id != user.id
                and not user.has_role("moderator", "admin")
            ):
                not_found()

        assessment = assess(
            author_roles=user.role_names,
            category=payload.category.value,
            source_urls=payload.source_urls,
        )
        body = payload.body
        if payload.source_urls:
            references = "\n".join(f"Reference: {url}" for url in payload.source_urls if url)
            body = f"{body}\n\n{references}"

        profile = user.profile
        post = self.repo.create(
            author_id=user.id,
            title=payload.title.strip(),
            body=body,
            category=payload.category,
            crop_code=payload.crop_code,
            language=payload.language,
            state=payload.state or (profile.state if profile else None),
            district=payload.district or (profile.district if profile else None),
            village=payload.village or (profile.village if profile else None),
            farm_id=payload.farm_id,
            crop_id=payload.crop_id,
            trust_label=assessment.label,
            is_demo=user.is_demo,
        )
        for position, media_id in enumerate(payload.media_ids):
            self.db.add(PostMedia(post_id=post.id, media_id=media_id, position=position))
        self.db.commit()
        self.db.refresh(post)

        self._enqueue_embedding(post)
        if payload.crop_code:
            self._notify_crop_followers(post)
        return self._to_out(
            post, viewer=user, following=self.repo.following_ids(user.id), reactions={}, saved=set()
        )

    def update_post(self, *, post_id: uuid.UUID, payload: PostUpdate, user: User) -> PostOut:
        post = self.repo.get(post_id)
        if post.author_id != user.id and not user.has_role("moderator", "admin"):
            not_found()
        data = payload.model_dump(exclude_unset=True)
        media_ids = data.pop("media_ids", None)
        source_urls = data.pop("source_urls", None)
        for field, value in data.items():
            if value is not None:
                setattr(post, field, value)
        if source_urls is not None:
            post.body = _replace_reference_block(post.body, source_urls)
        if media_ids is not None:
            for existing in list(post.media):
                self.db.delete(existing)
            self.db.flush()
            for position, media_id in enumerate(media_ids):
                asset = self.db.get(MediaAsset, media_id)
                if asset is None:
                    raise NotFoundError("One of the attached images was not found.")
                if (
                    asset.owner_id is not None
                    and asset.owner_id != user.id
                    and not user.has_role("moderator", "admin")
                ):
                    not_found()
                self.db.add(PostMedia(post_id=post.id, media_id=media_id, position=position))
        post.edited_at = datetime.now(UTC)
        assessment = assess(
            author_roles=user.role_names,
            category=post.category.value if hasattr(post.category, "value") else str(post.category),
            source_urls=_extract_urls(post.body),
        )
        post.trust_label = assessment.label
        self.db.commit()
        self.db.refresh(post)
        self._enqueue_embedding(post, force=True)
        return self._to_out(post, viewer=user, following=set(), reactions={}, saved=set())

    def delete_post(self, *, post_id: uuid.UUID, user: User) -> None:
        post = self.repo.get(post_id)
        if post.author_id != user.id and not user.has_role("moderator", "admin"):
            not_found()
        self.repo.soft_delete(post)
        self.db.commit()

    def get_post(
        self, *, post_id: uuid.UUID, viewer: User | None, count_view: bool = True
    ) -> PostOut:
        post = self.repo.get(post_id)
        if post.status in (ContentStatus.REMOVED, ContentStatus.HIDDEN) and (
            viewer is None
            or (viewer.id != post.author_id and not viewer.has_role("moderator", "admin"))
        ):
            raise NotFoundError("That post could not be found.")
        if count_view:
            self.db.execute(
                update(Post).where(Post.id == post.id).values(view_count=Post.view_count + 1)
            )
            self.db.commit()
            self.db.refresh(post)
        reactions = (
            self.repo.reactions_for_posts(user_id=viewer.id, post_ids=[post.id]) if viewer else {}
        )
        saved = self.repo.saved_post_ids(user_id=viewer.id, post_ids=[post.id]) if viewer else set()
        return self._to_out(
            post,
            viewer=viewer,
            following=self.repo.following_ids(viewer.id) if viewer else set(),
            reactions=reactions,
            saved=saved,
        )

    # --------------------------------------------------------------- comments
    def add_comment(self, *, post_id: uuid.UUID, payload: CommentCreate, user: User) -> CommentOut:
        from app.moderation.service import ModerationService

        # A restriction can target replies independently of new posts.
        ModerationService(self.db).assert_capability(user, "comment")
        post = self.repo.get(post_id)
        if post.status != ContentStatus.PUBLISHED:
            raise ConflictError("This post is not open for replies.")
        parent = None
        if payload.parent_id:
            parent = self.repo.get_comment(payload.parent_id)
            if parent.post_id != post.id:
                raise ValidationError("That reply belongs to a different post.")
        body = payload.body
        if payload.source_urls:
            body = f"{body}\n\n" + "\n".join(
                f"Reference: {url}" for url in payload.source_urls if url
            )
        assessment = assess(
            author_roles=user.role_names,
            category=None,
            source_urls=payload.source_urls,
        )
        comment = self.repo.add_comment(
            post_id=post.id,
            parent_id=parent.id if parent else None,
            author_id=user.id,
            body=body,
            trust_label=assessment.label,
            is_demo=user.is_demo,
        )
        self.repo.increment(post, "comment_count", 1)
        self.db.commit()
        self.db.refresh(comment)

        self._notify_reply(post=post, comment=comment, author=user, parent=parent)
        return self._comment_out(comment, viewer=user)

    def list_comments(self, *, post_id: uuid.UUID, viewer: User | None) -> list[CommentOut]:
        post = self.repo.get(post_id)
        comments = self.repo.comments_for(post.id)
        reactions: dict[str, str] = {}
        if viewer is not None:
            rows = self.db.execute(
                select(Reaction.comment_id, Reaction.kind).where(
                    Reaction.user_id == viewer.id, Reaction.comment_id.is_not(None)
                )
            ).all()
            reactions = {str(cid): kind.value for cid, kind in rows}
        by_parent: dict[str | None, list] = {}
        for comment in comments:
            by_parent.setdefault(str(comment.parent_id) if comment.parent_id else None, []).append(
                comment
            )

        def build(comment) -> CommentOut:
            out = self._comment_out(comment, viewer=viewer)
            out.my_reaction = reactions.get(str(comment.id))
            out.replies = [build(child) for child in by_parent.get(str(comment.id), [])]
            return out

        return [build(comment) for comment in by_parent.get(None, [])]

    def update_comment(self, *, comment_id: uuid.UUID, body: str, user: User) -> CommentOut:
        comment = self.repo.get_comment(comment_id)
        if comment.author_id != user.id and not user.has_role("moderator", "admin"):
            not_found()
        comment.body = body
        comment.edited_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(comment)
        return self._comment_out(comment, viewer=user)

    def delete_comment(self, *, comment_id: uuid.UUID, user: User) -> None:
        comment = self.repo.get_comment(comment_id)
        if comment.author_id != user.id and not user.has_role("moderator", "admin"):
            not_found()
        self.repo.soft_delete_comment(comment)
        post = self.db.get(Post, comment.post_id)
        if post is not None:
            self.repo.increment(post, "comment_count", -1)
        self.db.commit()

    def _comment_out(self, comment, *, viewer: User | None) -> CommentOut:
        author = self.db.get(User, comment.author_id)
        assert author is not None
        return CommentOut(
            id=comment.id,
            post_id=comment.post_id,
            parent_id=comment.parent_id,
            author=self._author_brief(author, viewer=viewer, following=set()),
            body=comment.body,
            trust_label=comment.trust_label,
            status=comment.status,
            reaction_count=comment.reaction_count,
            report_count=comment.report_count,
            created_at=comment.created_at,
            edited_at=comment.edited_at,
            is_demo=comment.is_demo,
        )

    # -------------------------------------------------------------- reactions
    def react_to_post(self, *, post_id: uuid.UUID, kind: ReactionKind, user: User) -> dict:
        post = self.repo.get(post_id)
        existing = self.repo.get_reaction(user_id=user.id, post_id=post.id)
        reaction = self.repo.add_reaction(user_id=user.id, post_id=post.id, kind=kind)
        if existing is None:
            self.repo.increment(post, "reaction_count", 1)
        self.db.commit()
        return {
            "status": "ok",
            "kind": reaction.kind.value,
            "reaction_count": post.reaction_count,
            "note": engagement_note(
                reaction_count=post.reaction_count, comment_count=post.comment_count
            ),
        }

    def unreact_post(self, *, post_id: uuid.UUID, user: User) -> dict:
        post = self.repo.get(post_id)
        removed = self.repo.remove_reaction(user_id=user.id, post_id=post.id)
        if removed:
            self.repo.increment(post, "reaction_count", -1)
        self.db.commit()
        return {"status": "ok", "reaction_count": post.reaction_count}

    def react_to_comment(self, *, comment_id: uuid.UUID, kind: ReactionKind, user: User) -> dict:
        comment = self.repo.get_comment(comment_id)
        existing = self.repo.get_reaction(user_id=user.id, comment_id=comment.id)
        reaction = self.repo.add_reaction(user_id=user.id, comment_id=comment.id, kind=kind)
        if existing is None:
            comment.reaction_count += 1
        self.db.commit()
        return {
            "status": "ok",
            "kind": reaction.kind.value,
            "reaction_count": comment.reaction_count,
        }

    # ------------------------------------------------------------------ saves
    def toggle_save(self, *, post_id: uuid.UUID, user: User) -> dict:
        post = self.repo.get(post_id)
        existing = self.db.execute(
            select(SavedPost).where(SavedPost.user_id == user.id, SavedPost.post_id == post.id)
        ).scalar_one_or_none()
        if existing:
            self.db.delete(existing)
            self.repo.increment(post, "save_count", -1)
            saved = False
        else:
            self.db.add(SavedPost(user_id=user.id, post_id=post.id))
            self.repo.increment(post, "save_count", 1)
            saved = True
        self.db.commit()
        return {"status": "ok", "saved": saved, "save_count": post.save_count}

    # ---------------------------------------------------------------- follows
    def follow(self, *, followee_id: uuid.UUID, user: User) -> dict:
        created = self.repo.follow(follower_id=user.id, followee_id=followee_id)
        self.db.commit()
        return {"status": "ok", "following": True, "new": created}

    def unfollow(self, *, followee_id: uuid.UUID, user: User) -> dict:
        removed = self.repo.unfollow(follower_id=user.id, followee_id=followee_id)
        self.db.commit()
        return {"status": "ok", "following": False, "removed": removed}

    def saved_posts(self, *, user: User, params: PageParams) -> dict:
        return self.feed(params=params, viewer=user, saved_only=True, sort="recent")

    # ---------------------------------------------------------------- reports
    def report(
        self,
        *,
        target_type: ReportTargetType,
        target_id: uuid.UUID,
        reason: ReportReason,
        details: str | None,
        user: User,
    ) -> dict:
        if target_type == ReportTargetType.POST:
            target = self.repo.get(target_id)
            author_id = target.author_id
            self.repo.increment(target, "report_count", 1)
        elif target_type == ReportTargetType.COMMENT:
            target = self.repo.get_comment(target_id)
            author_id = target.author_id
            target.report_count += 1
        else:
            from app.users.models import User as UserModel

            target = self.db.get(UserModel, target_id)
            if target is None:
                raise NotFoundError("That member could not be found.")
            author_id = target.id
        if author_id == user.id:
            raise ValidationError("You cannot report your own content.")
        if self.repo.open_report_exists(
            reporter_id=user.id, target_type=target_type, target_id=target_id
        ):
            return {
                "status": "already_reported",
                "report_id": None,
                "message": "You already reported this. Our moderators will review it.",
                "already_reported": True,
            }
        report = self.repo.create_report(
            reporter_id=user.id,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            details=details,
        )
        # A moderation case is created immediately so the queue is the single
        # source of truth for moderators (no separate "reports" inbox).
        from app.moderation.signals import heuristic_signals

        signals = heuristic_signals(self.db, target_type=target_type, target_id=target_id)
        from app.moderation.models import ModerationCase

        self.db.add(
            ModerationCase(
                report_id=report.id,
                target_type=target_type,
                target_id=target_id,
                author_id=author_id,
                reason=reason,
                ai_signals=signals,
                priority=signals.get("priority", 0),
            )
        )
        self.db.commit()
        return {
            "status": "received",
            "report_id": report.id,
            "message": (
                "Thank you. A moderator will review this. Reporting does not automatically hide the content — "
                "that decision is made by a human moderator."
            ),
            "already_reported": False,
        }

    # ------------------------------------------------------------- embeddings
    def _enqueue_embedding(self, post: Post, *, force: bool = False) -> None:
        from app.workers.queue import JobQueue

        try:
            JobQueue(self.db).enqueue(
                kind="embed_post",
                payload={"post_id": str(post.id), "force": force},
                requested_by_id=post.author_id,
                dedupe_key=None if force else f"embed_post:{post.id}",
            )
        except Exception as exc:
            logger.warning(
                "embed_enqueue_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )

    def similar_posts(self, *, post: Post, limit: int = 5) -> tuple[list[dict], str | None]:
        from genai.embeddings.provider import get_embedding_provider

        from app.database.vector_search import PostVectorIndex

        embedding_row = self.db.execute(
            select(PostEmbedding).where(PostEmbedding.post_id == post.id)
        ).scalar_one_or_none()
        if embedding_row is None:
            return [], None
        provider = get_embedding_provider()
        if embedding_row.embedding_model != provider.model:
            return [], "embedding_model_changed"
        index = PostVectorIndex(self.db)
        result = index.search(
            query_vector=list(embedding_row.embedding),
            top_k=limit + 1,
            filters={},
        )
        items = []
        for hit in result.hits:
            if hit.id == str(post.id):
                continue
            items.append(
                {
                    "post_id": hit.id,
                    "title": hit.metadata.get("title"),
                    "score": round(hit.score, 4),
                    "method": result.method,
                }
            )
        return items[:limit], result.method

    # ----------------------------------------------------------- notifications
    def _notify_reply(self, *, post: Post, comment, author: User, parent) -> None:
        from app.notifications.service import NotificationService

        service = NotificationService(self.db)
        recipients: set[uuid.UUID] = set()
        if post.author_id != author.id:
            recipients.add(post.author_id)
        if parent is not None and parent.author_id not in (author.id, None):
            recipients.add(parent.author_id)
        if not recipients:
            return
        author_name = (author.profile.display_name if author.profile else None) or author.full_name
        for recipient_id in recipients:
            try:
                service.create(
                    user_id=recipient_id,
                    type=NotificationType.COMMENT_REPLY,
                    title=f"{author_name} replied to {'your post' if recipient_id == post.author_id else 'your reply'}",
                    body=comment.body[:200],
                    subject_type="post",
                    subject_id=post.id,
                    deep_link=f"digitalvillage://community/posts/{post.id}",
                    payload={"comment_id": str(comment.id), "post_title": post.title[:80]},
                )
            except Exception as exc:
                logger.warning(
                    "notification_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
                )
        self.db.commit()

    def _notify_crop_followers(self, post: Post) -> None:
        """Notify farmers whose selected crops match a new post — capped to avoid
        spam (see NotificationService preferences and daily caps)."""
        from app.crops.models import Crop
        from app.farms.models import Farm
        from app.notifications.service import NotificationService

        rows = (
            self.db.execute(
                select(Farm.owner_id)
                .join(Crop, Crop.farm_id == Farm.id)
                .where(Crop.crop_code == post.crop_code, Farm.owner_id != post.author_id)
                .limit(25)
            )
            .scalars()
            .all()
        )
        if not rows:
            return
        service = NotificationService(self.db)
        for owner_id in set(rows):
            try:
                service.create(
                    user_id=owner_id,
                    type=NotificationType.POST_IN_FEED,
                    title=f"New {post.crop_code} discussion in the community",
                    body=post.title[:200],
                    subject_type="post",
                    subject_id=post.id,
                    deep_link=f"digitalvillage://community/posts/{post.id}",
                    payload={"reason": "crop_match", "crop_code": post.crop_code},
                )
            except Exception:
                continue
        self.db.commit()

    # ------------------------------------------------------------------ tools
    def search_semantic(
        self,
        *,
        query: str,
        category: PostCategory | None = None,
        crop_code: str | None = None,
        state: str | None = None,
        top_k: int = 10,
    ) -> dict:
        from genai.embeddings.provider import get_embedding_provider

        from app.database.vector_search import PostVectorIndex

        provider = get_embedding_provider()
        embedded = provider.embed([query], input_type="query")
        index = PostVectorIndex(self.db)
        filters = {}
        if category:
            filters["category"] = category.value
        if crop_code:
            filters["crop_code"] = crop_code
        if state:
            filters["state"] = state
        result = index.search(query_vector=embedded.vectors[0], top_k=top_k, filters=filters)
        posts = []
        for hit in result.hits:
            post = self.db.get(Post, uuid.UUID(hit.id))
            if post is None:
                continue
            posts.append(
                {
                    "post_id": hit.id,
                    "title": post.title,
                    "category": post.category.value
                    if hasattr(post.category, "value")
                    else str(post.category),
                    "crop_code": post.crop_code,
                    "state": post.state,
                    "score": round(hit.score, 4),
                    "excerpt": post.body[:240],
                    "reaction_count": post.reaction_count,
                    "comment_count": post.comment_count,
                }
            )
        notices = []
        if embedded.is_demo:
            notices.append(
                "Semantic search is running on the demo embedding provider (lexical vectors). Exact wording "
                "matches well; paraphrases may be missed until a production embedding model is configured."
            )
        return {
            "query": query,
            "results": posts,
            "method": result.method,
            "index_used": result.index_used,
            "embedding_provider": embedded.provider,
            "embedding_is_demo": embedded.is_demo,
            "notices": notices,
        }


def _extract_urls(text: str) -> list[str]:
    import re

    return re.findall(r"https?://[^\s)]+", text or "")[:5]


def _replace_reference_block(body: str, source_urls: list[str]) -> str:
    import re

    cleaned = re.sub(r"\n*Reference: https?://[^\s]+\n?", "\n", body or "").strip()
    if not source_urls:
        return cleaned
    references = "\n".join(f"Reference: {url}" for url in source_urls if url)
    return f"{cleaned}\n\n{references}".strip()
