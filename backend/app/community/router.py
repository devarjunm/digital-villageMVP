"""Community endpoints: feed, posts, replies, reactions, saves, follows, reports.

Every mutation is authorised against the acting user, every response carries a
trust label and an explanation of the feed ordering, and reporting opens a real
moderation case (see /moderation). Nothing here silently hides content: only a
human moderator can change a post's visibility.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.auth.dependencies import CurrentUser, DbSession, OptionalUser
from app.community.schemas import (
    CommentCreate,
    CommentOut,
    FeedResponse,
    PostCreate,
    PostDetail,
    PostOut,
    PostUpdate,
    ReactionRequest,
    ReportAck,
    ReportRequest,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from app.community.service import CommunityService
from app.community.trust import (
    TRUST_LABEL_DESCRIPTIONS,
    detect_conflicting_replies,
    disagreement_flag,
)
from app.core.enums import PostCategory
from app.core.errors import ValidationError
from app.core.pagination import PageParams, page_params
from app.core.ratelimit import enforce_rate_limit

router = APIRouter()

PageDep = Annotated[PageParams, Depends(page_params)]


@router.get("/meta", summary="Community categories, trust labels and ranking method")
def community_meta() -> dict:
    """Self-describing metadata so the mobile client never hard-codes taxonomy."""
    from app.community.ranking import explanation
    from app.core.enums import ReactionKind, ReportReason

    return {
        "categories": [
            {
                "value": item.value,
                "label_en": item.value.replace("_", " ").title(),
                "description": _CATEGORY_DESCRIPTIONS.get(item.value, ""),
            }
            for item in PostCategory
        ],
        "reaction_kinds": [item.value for item in ReactionKind],
        "report_reasons": [item.value for item in ReportReason],
        "trust_labels": [
            {"value": key, "description": value} for key, value in TRUST_LABEL_DESCRIPTIONS.items()
        ],
        "what_trust_labels_mean": (
            "Trust labels describe where a statement comes from, not how popular it is. A post with many likes "
            "is still labelled 'Farmer experience' unless it carries expert review or an official source."
        ),
        "ranking": explanation(),
        "notes": [
            "Reporting content opens a moderation case; it never auto-hides the post.",
        ],
    }


@router.get("/feed", response_model=FeedResponse, summary="Ranked community feed")
def feed(
    db: DbSession,
    request: Request,
    user: OptionalUser,
    params: PageDep,
    category: Annotated[PostCategory | None, Query()] = None,
    crop: Annotated[str | None, Query(max_length=48)] = None,
    state: Annotated[str | None, Query(max_length=120)] = None,
    district: Annotated[str | None, Query(max_length=120)] = None,
    author_id: Annotated[uuid.UUID | None, Query()] = None,
    following_only: bool = False,
    saved_only: bool = False,
    unanswered_only: bool = False,
    sort: Annotated[str, Query(pattern="^(relevance|recent|popular)$")] = "relevance",
    q: Annotated[str | None, Query(max_length=120)] = None,
    include_demo: bool = True,
) -> dict:
    enforce_rate_limit(request, "read")
    if saved_only and user is None:
        raise ValidationError("Sign in to view your saved posts.")
    return CommunityService(db).feed(
        params=params,
        viewer=user,
        category=category,
        crop_code=crop,
        state=state,
        district=district,
        author_id=author_id,
        following_only=following_only,
        saved_only=saved_only,
        query=q,
        unanswered_only=unanswered_only,
        sort=sort,
        include_demo=include_demo,
    )


@router.post(
    "/posts",
    response_model=PostOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a post (question, update, alert, success story)",
)
def create_post(payload: PostCreate, user: CurrentUser, db: DbSession, request: Request) -> PostOut:
    enforce_rate_limit(request, "write")
    return CommunityService(db).create_post(payload=payload, user=user)


@router.get("/posts/{post_id}", response_model=PostDetail, summary="Post detail with replies")
def get_post(post_id: uuid.UUID, db: DbSession, user: OptionalUser, request: Request) -> PostDetail:
    enforce_rate_limit(request, "read")
    service = CommunityService(db)
    post = service.get_post(post_id=post_id, viewer=user)
    from app.community.repository import PostRepository

    raw = PostRepository(db).get(post_id)
    comments = service.list_comments(post_id=post_id, viewer=user)
    similar, method = service.similar_posts(post=raw)
    return PostDetail(post=post, comments=comments, similar_posts=similar, similar_method=method)


@router.patch("/posts/{post_id}", response_model=PostOut, summary="Edit your post")
def update_post(
    post_id: uuid.UUID, payload: PostUpdate, user: CurrentUser, db: DbSession, request: Request
) -> PostOut:
    enforce_rate_limit(request, "write")
    return CommunityService(db).update_post(post_id=post_id, payload=payload, user=user)


@router.delete(
    "/posts/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete your post",
)
def delete_post(post_id: uuid.UUID, user: CurrentUser, db: DbSession, request: Request) -> None:
    enforce_rate_limit(request, "write")
    CommunityService(db).delete_post(post_id=post_id, user=user)


@router.get("/posts/{post_id}/comments", summary="Replies to a post (with disagreement notice)")
def list_comments(post_id: uuid.UUID, db: DbSession, user: OptionalUser, request: Request) -> dict:
    enforce_rate_limit(request, "read")
    comments = CommunityService(db).list_comments(post_id=post_id, viewer=user)
    bodies = [item.body for item in comments]
    bodies += [reply.body for item in comments for reply in item.replies]
    flag = disagreement_flag(has_conflicting_replies=detect_conflicting_replies(bodies))
    return {
        "items": comments,
        "total": len(comments),
        "disagreement": flag,
        "trust_note": (
            "Labels show the source of a statement. Conflicting advice is surfaced rather than hidden; "
            "ask an expert or your local KVK before changing a treatment."
        ),
    }


@router.post(
    "/posts/{post_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reply to a post",
)
def add_comment(
    post_id: uuid.UUID, payload: CommentCreate, user: CurrentUser, db: DbSession, request: Request
) -> CommentOut:
    enforce_rate_limit(request, "write")
    return CommunityService(db).add_comment(post_id=post_id, payload=payload, user=user)


@router.patch("/comments/{comment_id}", response_model=CommentOut, summary="Edit your reply")
def update_comment(
    comment_id: uuid.UUID,
    body: Annotated[str, Query(min_length=1, max_length=4000)],
    user: CurrentUser,
    db: DbSession,
    request: Request,
) -> CommentOut:
    enforce_rate_limit(request, "write")
    return CommunityService(db).update_comment(comment_id=comment_id, body=body, user=user)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete your reply",
)
def delete_comment(
    comment_id: uuid.UUID, user: CurrentUser, db: DbSession, request: Request
) -> None:
    enforce_rate_limit(request, "write")
    CommunityService(db).delete_comment(comment_id=comment_id, user=user)


@router.post("/posts/{post_id}/reactions", summary="React to a post (support / helpful / thanks)")
def react_post(
    post_id: uuid.UUID, payload: ReactionRequest, user: CurrentUser, db: DbSession, request: Request
) -> dict:
    enforce_rate_limit(request, "write")
    return CommunityService(db).react_to_post(post_id=post_id, kind=payload.kind, user=user)


@router.delete("/posts/{post_id}/reactions", summary="Remove your reaction from a post")
def unreact_post(post_id: uuid.UUID, user: CurrentUser, db: DbSession, request: Request) -> dict:
    enforce_rate_limit(request, "write")
    return CommunityService(db).unreact_post(post_id=post_id, user=user)


@router.post("/comments/{comment_id}/reactions", summary="React to a reply")
def react_comment(
    comment_id: uuid.UUID,
    payload: ReactionRequest,
    user: CurrentUser,
    db: DbSession,
    request: Request,
) -> dict:
    enforce_rate_limit(request, "write")
    return CommunityService(db).react_to_comment(
        comment_id=comment_id, kind=payload.kind, user=user
    )


@router.post("/posts/{post_id}/save", summary="Save or unsave a post")
def toggle_save(post_id: uuid.UUID, user: CurrentUser, db: DbSession, request: Request) -> dict:
    enforce_rate_limit(request, "write")
    return CommunityService(db).toggle_save(post_id=post_id, user=user)


@router.get("/me/saved", response_model=FeedResponse, summary="Your saved posts")
def saved_posts(db: DbSession, user: CurrentUser, params: PageDep, request: Request) -> dict:
    enforce_rate_limit(request, "read")
    return CommunityService(db).saved_posts(user=user, params=params)


@router.get("/me/following", summary="Accounts you follow")
def following(db: DbSession, user: CurrentUser, request: Request) -> dict:
    enforce_rate_limit(request, "read")
    from app.community.repository import PostRepository
    from app.users.models import User as UserModel

    ids = PostRepository(db).following_ids(user.id)
    items = []
    for value in ids:
        account = db.get(UserModel, uuid.UUID(value))
        if account is None:
            continue
        profile = account.profile
        items.append(
            {
                "user_id": str(account.id),
                "display_name": (profile.display_name if profile else None) or account.full_name,
                "primary_role": account.primary_role.value,
                "state": profile.state if profile else None,
                "district": profile.district if profile else None,
                "verified_expert": account.has_role("expert"),
            }
        )
    return {"items": items, "total": len(items)}


@router.post("/users/{user_id}/follow", summary="Follow a farmer or expert")
def follow_user(user_id: uuid.UUID, user: CurrentUser, db: DbSession, request: Request) -> dict:
    enforce_rate_limit(request, "write")
    return CommunityService(db).follow(followee_id=user_id, user=user)


@router.delete("/users/{user_id}/follow", summary="Unfollow")
def unfollow_user(user_id: uuid.UUID, user: CurrentUser, db: DbSession, request: Request) -> dict:
    enforce_rate_limit(request, "write")
    return CommunityService(db).unfollow(followee_id=user_id, user=user)


@router.post("/reports", response_model=ReportAck, summary="Report a post, reply or member")
def report_content(
    payload: ReportRequest, user: CurrentUser, db: DbSession, request: Request
) -> ReportAck:
    enforce_rate_limit(request, "write")
    result = CommunityService(db).report(
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason,
        details=payload.details,
        user=user,
    )
    return ReportAck(**result)


@router.post(
    "/search/semantic",
    response_model=SemanticSearchResponse,
    summary="Meaning-based community search (pgvector)",
)
def semantic_search(
    payload: SemanticSearchRequest, db: DbSession, request: Request, user: OptionalUser
) -> SemanticSearchResponse:
    enforce_rate_limit(request, "search")
    result = CommunityService(db).search_semantic(
        query=payload.query,
        category=payload.category,
        crop_code=payload.crop_code,
        state=payload.state,
        top_k=payload.top_k,
    )
    return SemanticSearchResponse(**result)


_CATEGORY_DESCRIPTIONS = {
    "crop_problem": "Ask for help with a specific crop problem or decision.",
    "disease": "Possible disease observations. Photos and the crop stage help others answer.",
    "pest": "Possible pest observations. Say what you saw, where, and how many plants are affected.",
    "irrigation": "Water management: scheduling, methods, drainage and water availability.",
    "soil": "Soil health, soil tests, pH and organic matter.",
    "fertilizer": "Nutrient management. Say what you applied, how much and when.",
    "weather": "Local weather observations and how they affected your fields.",
    "market": "Prices or mandi observations — say which market and when you saw them.",
    "machinery": "Equipment, tools and mechanisation questions.",
    "government_scheme": "Scheme information. Cite the official notification or portal so others can verify.",
    "farming_technique": "Techniques, results worth repeating — include the conditions and the season.",
    "general": "Anything else that belongs in the community.",
}
