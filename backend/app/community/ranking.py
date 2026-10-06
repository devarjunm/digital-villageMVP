"""Deterministic feed ranking.

This is **not** a trained recommender, and the API says so
(`ranking.explanation` names the rule and its components). It is an explicit,
tunable, fully explainable scoring function that gives a useful default order
while the platform accumulates the interaction data a learned model would need.

score = base_quality
      + recency_decay
      + engagement_prior
      + personalisation
      − penalties

Every component is capped, so a single term (e.g. a very popular old post)
cannot dominate, and every contribution is returned so a moderator or engineer
can explain exactly why a post appeared where it did.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.enums import PostCategory

# Weights are configuration, not magic numbers: they are echoed in the response.
RECENCY_HALF_LIFE_HOURS = 36.0
DEFAULT_WEIGHTS: dict[str, float] = {
    "recency": 1.0,
    "engagement": 0.8,
    "personalisation": 0.9,
    "trust": 0.35,
    "penalty_report": 0.6,
    "penalty_answered": 0.15,
}
ENGAGEMENT_LOG_CAP = 4.0  # log1p scale saturates around ~55 interactions


@dataclass(slots=True)
class RankingContext:
    """Viewer-specific signals. All optional — anonymous viewers get the same
    deterministic order minus the personalisation term."""

    viewer_id: str | None = None
    preferred_crop_codes: set[str] = field(default_factory=set)
    home_state: str | None = None
    home_district: str | None = None
    followed_user_ids: set[str] = field(default_factory=set)
    recently_viewed_post_ids: set[str] = field(default_factory=set)
    saved_crop_codes: set[str] = field(default_factory=set)
    interacted_categories: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class RankedPost:
    post: Any
    score: float
    components: dict[str, float]


def _recency(post_created_at: datetime) -> float:
    if post_created_at.tzinfo is None:
        post_created_at = post_created_at.replace(tzinfo=UTC)
    age_hours = max(0.0, (datetime.now(UTC) - post_created_at).total_seconds() / 3600.0)
    return math.exp(-age_hours / RECENCY_HALF_LIFE_HOURS)


def _engagement(post: Any) -> float:
    raw = (
        float(getattr(post, "reaction_count", 0) or 0)
        + 2.0 * float(getattr(post, "comment_count", 0) or 0)
        + 1.5 * float(getattr(post, "save_count", 0) or 0)
        + 0.02 * float(getattr(post, "view_count", 0) or 0)
    )
    if raw <= 0:
        return 0.0
    return min(ENGAGEMENT_LOG_CAP, math.log1p(raw) / 2.0)


def _personalisation(post: Any, ctx: RankingContext) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if ctx.viewer_id and str(post.author_id) in ctx.followed_user_ids:
        score += 0.5
        reasons.append("from a farmer you follow")
    if post.crop_code and post.crop_code in ctx.preferred_crop_codes:
        score += 0.35
        reasons.append("matches your crops")
    if post.crop_code and post.crop_code in ctx.saved_crop_codes:
        score += 0.1
        reasons.append("similar to posts you saved")
    if ctx.home_district and post.district and post.district.lower() == ctx.home_district.lower():
        score += 0.3
        reasons.append("from your district")
    elif ctx.home_state and post.state and post.state.lower() == ctx.home_state.lower():
        score += 0.15
        reasons.append("from your state")
    category = getattr(post.category, "value", str(post.category))
    if ctx.interacted_categories.get(category):
        score += min(0.2, 0.05 * ctx.interacted_categories[category])
        reasons.append("category you interact with")
    if ctx.viewer_id and str(post.id) in ctx.recently_viewed_post_ids:
        score -= 0.25
        reasons.append("already viewed (down-ranked)")
    return score, reasons


def _trust(post: Any) -> float:
    label = getattr(post.trust_label, "value", str(post.trust_label))
    return {
        "official_information": 1.0,
        "expert_information": 0.8,
        "community_supported": 0.5,
        "farmer_experience": 0.3,
        "ai_prediction": 0.0,
    }.get(label, 0.2)


def rank_posts(
    posts: list[Any],
    *,
    context: RankingContext | None = None,
    weights: dict[str, float] | None = None,
    include_components: bool = True,
) -> list[RankedPost]:
    ctx = context or RankingContext()
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    ranked: list[RankedPost] = []
    for post in posts:
        recency = _recency(post.created_at)
        engagement = _engagement(post)
        personalisation, _reasons = _personalisation(post, ctx)
        trust = _trust(post)
        penalties = w["penalty_report"] * min(
            1.0, float(getattr(post, "report_count", 0) or 0) / 3.0
        )
        # A crop-problem post that already has several replies is slightly less
        # urgent to surface than an unanswered question (community benefit).
        if getattr(post, "comment_count", 0) >= 4 and getattr(post, "report_count", 0) == 0:
            penalties += w["penalty_answered"]
        score = (
            w["recency"] * recency
            + w["engagement"] * engagement
            + w["personalisation"] * personalisation
            + w["trust"] * trust
            - penalties
        )
        components = (
            {
                "recency": round(recency, 4),
                "engagement": round(engagement, 4),
                "personalisation": round(personalisation, 4),
                "trust": round(trust, 4),
                "penalties": round(-penalties, 4),
            }
            if include_components
            else {}
        )
        ranked.append(RankedPost(post=post, score=round(score, 6), components=components))
    ranked.sort(key=lambda item: (-item.score, str(item.post.id)))
    return ranked


def explanation(context: RankingContext | None = None) -> dict[str, Any]:
    """Machine-readable statement of how the feed was ordered (returned in the
    response so the ordering is never a mystery)."""
    ctx = context or RankingContext()
    active = ["recency", "engagement", "trust"]
    if ctx.viewer_id:
        active.append("personalisation")
    return {
        "method": "deterministic_rule_based",
        "is_ml_model": False,
        "active_terms": active,
        "weights": DEFAULT_WEIGHTS,
        "recency_half_life_hours": RECENCY_HALF_LIFE_HOURS,
        "personalisation_signals": {
            "followed_users": len(ctx.followed_user_ids),
            "preferred_crops": sorted(ctx.preferred_crop_codes),
            "home_state": ctx.home_state,
            "home_district": ctx.home_district,
            "viewed_posts": len(ctx.recently_viewed_post_ids),
        },
        "note": (
            "Ranking is a fixed scoring rule (documented weights), not a trained recommendation model. "
            "A learned ranker will be introduced only once interaction data and offline evaluation exist."
        ),
        "categories": [c.value for c in PostCategory],
    }
