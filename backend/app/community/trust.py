"""Community trust labelling.

Rules (deliberately simple, deterministic and explainable):

  * The label describes *who* is speaking, never whether the content is true:
      - moderator/admin content that quotes an official source → official_information
      - expert (agronomist/VLE/KVK-verified) authors            → expert_information
      - a farmer post with a linked official/knowledge source    → community_supported
      - anything else                                            → farmer_experience
  * Popularity (likes/comments) never upgrades a label. The API returns
    `engagement` separately and the UI shows "many farmers found this useful",
    which is not a truth claim.
  * Model output is always tagged `ai_prediction` and is never merged into a
    farmer's statement.
  * Moderation can attach verification flags (e.g. `expert_verified`) through
    `post_verifications`, which is separate from the author's role.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.contracts import TrustLabel
from app.core.enums import Role

OFFICIAL_SOURCE_HINTS = (
    "icar.org.in",
    "agricoop.nic.in",
    "krishi.gov.in",
    "kisan.gov.in",
    "pmkisan.gov.in",
    "agmarknet.gov.in",
    "data.gov.in",
    "imd.gov.in",
    "india.gov.in",
    "kvk.icar.gov.in",
    "nrsc.gov.in",
    "apeda.gov.in",
)

EXPERT_AUTHOR_ROLES = (Role.EXPERT, Role.MODERATOR, Role.ADMIN)

# Published in /community/meta so the UI never invents its own wording.
TRUST_LABEL_DESCRIPTIONS: dict[str, str] = {
    "farmer_experience": (
        "Shared by a farmer from their own field. Useful peer experience — not verified agronomic guidance."
    ),
    "community_supported": (
        "Backed by another farmer or a linked source that others can check. Still not an official position."
    ),
    "expert_information": (
        "Provided or reviewed by an account with the expert role. Follows the platform's expert content rules."
    ),
    "official_information": (
        "Platform staff citing an official government or institutional source. The link is shown with the post."
    ),
    "ai_prediction": (
        "Produced by a model, not by a person. Always shown with the model name, version and confidence caveat."
    ),
}

# Phrases that, when one reply contains the positive form and another the negated
# form, indicate the community disagrees. Deliberately small and transparent: this
# only decides whether to *show* a "farmers report different results" banner, it
# never judges which reply is right.
_CONFLICT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("should", "should not"),
    ("should", "shouldn't"),
    ("do ", "do not"),
    ("is safe", "is not safe"),
    ("will help", "will not help"),
    ("works", "does not work"),
    ("works", "doesn't work"),
    ("spray", "do not spray"),
    ("फवारणी", "फवारणी करू नका"),
    ("छिड़काव", "छिड़काव न करें"),
)


def detect_conflicting_replies(bodies: list[str]) -> bool:
    """True when two replies appear to contradict each other.

    Conservative on purpose: a false negative just means no banner, which is
    safer than telling farmers the community disputes settled guidance.
    """
    joined = [body.lower() for body in bodies if body]
    if len(joined) < 2:
        return False
    for positive, negative in _CONFLICT_PATTERNS:
        has_positive = any(positive in body and negative not in body for body in joined)
        has_negative = any(negative in body for body in joined)
        if has_positive and has_negative:
            return True
    return False


@dataclass(slots=True)
class TrustAssessment:
    label: TrustLabel
    reasons: list[str] = field(default_factory=list)
    is_verified: bool = False
    verification_note: str | None = None


def assess(
    *,
    author_roles: list[str],
    category: str | None = None,
    source_urls: list[str] | None = None,
    expert_verified: bool = False,
) -> TrustAssessment:
    roles = {str(role).lower() for role in author_roles}
    urls = [u for u in (source_urls or []) if u]
    official_links = [u for u in urls if any(hint in u.lower() for hint in OFFICIAL_SOURCE_HINTS)]

    if expert_verified:
        return TrustAssessment(
            label=TrustLabel.EXPERT_INFORMATION,
            reasons=["A verified expert reviewed this post."],
            is_verified=True,
            verification_note="Expert-reviewed content.",
        )
    if roles & {Role.EXPERT.value}:
        return TrustAssessment(
            label=TrustLabel.EXPERT_INFORMATION,
            reasons=["Posted by an account with the expert role."],
            is_verified=True,
        )
    if roles & {Role.MODERATOR.value, Role.ADMIN.value} and official_links:
        return TrustAssessment(
            label=TrustLabel.OFFICIAL_INFORMATION,
            reasons=["Posted by platform staff and links to an official government source."],
            is_verified=True,
        )
    if official_links:
        return TrustAssessment(
            label=TrustLabel.COMMUNITY_SUPPORTED,
            reasons=["Includes a link to an official source, which other farmers can verify."],
        )
    if category in ("government_scheme", "market") and urls:
        return TrustAssessment(
            label=TrustLabel.COMMUNITY_SUPPORTED,
            reasons=["Includes an external reference link for this topic."],
        )
    return TrustAssessment(
        label=TrustLabel.FARMER_EXPERIENCE,
        reasons=["This is a farmer's own experience, not verified agronomic guidance."],
    )


def engagement_note(*, reaction_count: int, comment_count: int) -> str:
    """Explicit, non-truth-claiming wording for popularity."""
    if reaction_count + comment_count == 0:
        return "No engagement yet."
    return (
        f"{reaction_count} farmer(s) found this helpful and {comment_count} replied. "
        "Popularity is not evidence that the advice is scientifically correct — check the source labels."
    )


def disagreement_flag(*, has_conflicting_replies: bool) -> str | None:
    if has_conflicting_replies:
        return (
            "Other farmers reported different results for this issue. Treat the replies as experiences of "
            "different fields, seasons and varieties rather than as a settled answer."
        )
    return None
