"""Advisory signals for the moderation queue.

Design constraints (from the specification):

  * an automated signal may rank a case for human review, but it must never
    decide that an agricultural claim is false, and it must never hide content by
    itself — only `ModerationService.apply_action` (a human action, audited) can
    change visibility;
  * every signal is explainable: the queue shows *why* a case was prioritised
    (matched keywords, link count, duplicate similarity, account age), never a
    bare "AI score";
  * the phrase lists are publicly documented here so the behaviour is auditable
    and can be tuned by the moderation team.

`heuristic_signals()` is deliberately rule based (no model). When a moderation
classifier is trained later, it plugs in here as an additional advisory signal
and reviews the same fields.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ReportTargetType

# Contact/marketplace spam: pushing users to off-platform contact or sales.
CONTACT_SPAM_PATTERNS: tuple[str, ...] = (
    r"whats\s*app",
    r"whatsapp\s*(number|no\.?|pe)\b",
    r"telegram\s*(id|link|group)?",
    r"\bcall\s*(me|now)\b",
    r"\bdm\s+me\b",
    r"\bmy\s+number\b",
    r"\+\d{10,13}\b",
    r"\d{10}\b",
    r"upi\s*[:\-]?\s*[\w.\-]+@\w+",
    r"google\s*pay|phone\s*pe|paytm",
)
# Commercial pushing / guaranteed-outcome claims.
MARKETING_PATTERNS: tuple[str, ...] = (
    r"\b(guarantee|guaranteed|100\s*%\s*(result|yield|profit))\b",
    r"\b(best\s+in\s+market|cheapest|limited\s+offer|order\s+now|buy\s+now)\b",
    r"\b(combo\s*offer|discount\s+code|coupon)\b",
)
# Unverified chemical/medicine instructions (dosage claims need expert or
# official sourcing; flag for human review, never auto-judge correctness).
CHEMICAL_PATTERNS: tuple[str, ...] = (
    r"\b(monocrotophos|endosulfan|paraquat|phorate|methyl\s+parathion|carbofuran)\b",
    r"\b(ml|gram|gm|kg)\s*(per|/)\s*(litre|liter|l|acre|hectare|pump)\b",
    r"\b(antibiotic|streptomycin|oxytetracycline)\b",
)
# Requests for money or personal documents → high-priority review.
FRAUD_PATTERNS: tuple[str, ...] = (
    r"\b(send\s+money|advance\s+payment|registration\s+fee|processing\s+fee)\b",
    r"\b(aadhaar|aadhar|pan|otp|passbook|bank\s+details)\b",
    r"\b(subside|subsidised|subsidize).{0,20}(pay|fee|amount)\b",
)
LINK_PATTERN = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
OFFICIAL_DOMAINS = ("gov.in", "nic.in", "icar.org.in", "ac.in")


def _count_matches(text: str, patterns: Iterable[str]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        for match in compiled.finditer(text):
            found.append(match.group(0).strip())
            if len(found) >= 6:
                return found
    return found


def analyse_text(text: str) -> dict[str, Any]:
    """Pure-text signal extraction (unit-testable, no database access)."""
    body = text or ""
    lowered = body.lower()
    links = LINK_PATTERN.findall(body)
    official_links = [
        link for link in links if any(domain in link.lower() for domain in OFFICIAL_DOMAINS)
    ]
    contact = _count_matches(body, CONTACT_SPAM_PATTERNS)
    marketing = _count_matches(body, MARKETING_PATTERNS)
    chemical = _count_matches(body, CHEMICAL_PATTERNS)
    fraud = _count_matches(body, FRAUD_PATTERNS)

    flags: list[str] = []
    if contact:
        flags.append("contact_solicitation")
    if marketing:
        flags.append("marketing_language")
    if chemical:
        flags.append("chemical_or_dosage_claim")
    if fraud:
        flags.append("payment_or_document_request")
    if len(links) >= 4 and len(official_links) == 0:
        flags.append("link_heavy_without_official_source")
    if lowered.count("!!!") >= 2 or (len(body) > 120 and body.isupper()):
        flags.append("shouting")

    score = 0
    score += 25 * len(contact)
    score += 15 * len(marketing)
    score += 30 * len(chemical)
    score += 40 * len(fraud)
    if "link_heavy_without_official_source" in flags:
        score += 20
    if "shouting" in flags:
        score += 5
    return {
        "flags": flags,
        "matches": {
            "contact_solicitation": contact,
            "marketing_language": marketing,
            "chemical_or_dosage_claim": chemical,
            "payment_or_document_request": fraud,
        },
        "link_count": len(links),
        "official_link_count": len(official_links),
        "raw_score": min(100, score),
        "advisory_only": True,
    }


def heuristic_signals(
    db: Session, *, target_type: ReportTargetType, target_id: uuid.UUID
) -> dict[str, Any]:
    """Signals for a report: text analysis, author history and duplicate check."""
    from app.community.models import Comment, Post
    from app.core.enums import ContentStatus, ModerationActionType

    text = ""
    author_id: uuid.UUID | None = None
    media_count = 0
    if target_type == ReportTargetType.POST:
        post = db.get(Post, target_id)
        if post is not None:
            text = f"{post.title}\n{post.body}"
            author_id = post.author_id
            media_count = len(post.media)
    elif target_type == ReportTargetType.COMMENT:
        comment = db.get(Comment, target_id)
        if comment is not None:
            text = comment.body
            author_id = comment.author_id
    else:
        from app.users.models import User

        user = db.get(User, target_id)
        if user is not None:
            text = f"{user.full_name} {user.profile.bio if user.profile else ''}"
            author_id = user.id

    signals = analyse_text(text)
    signals["target_type"] = target_type.value
    signals["media_count"] = media_count
    signals["author_id"] = str(author_id) if author_id else None

    if author_id is not None:
        from app.moderation.models import ModerationAction

        prior_actions = int(
            db.execute(
                select(func.count())
                .select_from(ModerationAction)
                .where(
                    ModerationAction.target_type == "user",
                    ModerationAction.target_id == author_id,
                    ModerationAction.action.in_(
                        [
                            ModerationActionType.REMOVE.value,
                            ModerationActionType.HIDE.value,
                            ModerationActionType.RESTRICT_AUTHOR.value,
                        ]
                    ),
                )
            ).scalar_one()
        )
        signals["author_prior_actions"] = prior_actions
        if prior_actions:
            signals["raw_score"] = min(100, signals["raw_score"] + 20)

        since = datetime.now(UTC) - timedelta(days=7)
        recent_open = (
            int(
                db.execute(
                    select(func.count())
                    .select_from(Post)
                    .where(Post.author_id == author_id, Post.created_at >= since)
                ).scalar_one()
            )
            if target_type == ReportTargetType.POST
            else 0
        )
        signals["author_posts_last_7d"] = recent_open
        if recent_open >= 20:
            signals["flags"] = [*signals["flags"], "high_volume_posting"]
            signals["raw_score"] = min(100, signals["raw_score"] + 10)

    # Duplicate/near-duplicate text by the same author is a common spam pattern.
    if target_type == ReportTargetType.POST and text:
        from app.community.models import Post

        snippet = text.strip()[:80].lower()
        duplicates = int(
            db.execute(
                select(func.count())
                .select_from(Post)
                .where(
                    func.lower(func.substr(Post.body, 1, 80)) == snippet,
                    Post.deleted_at.is_(None),
                    Post.status == ContentStatus.PUBLISHED,
                )
            ).scalar_one()
        )
        signals["duplicate_posts"] = max(0, duplicates - 1)
        if signals["duplicate_posts"]:
            signals["flags"] = [*signals["flags"], "duplicate_content"]
            signals["raw_score"] = min(100, signals["raw_score"] + 15)

    signals["priority"] = _priority(signals)
    signals["explanation"] = _explain(signals)
    return signals


def _priority(signals: dict[str, Any]) -> int:
    """Case priority (0-100). Priority is about queue ordering, not correctness."""
    score = int(signals.get("raw_score", 0))
    if "payment_or_document_request" in signals.get("flags", []):
        score = max(score, 80)
    if "contact_solicitation" in signals.get("flags", []):
        score = max(score, 55)
    return max(0, min(100, score))


def _explain(signals: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    matches = signals.get("matches", {})
    if matches.get("contact_solicitation"):
        notes.append("Contains what looks like an attempt to move the conversation off-platform.")
    if matches.get("payment_or_document_request"):
        notes.append("Mentions payments, identity documents or OTPs — treat as high priority.")
    if matches.get("chemical_or_dosage_claim"):
        notes.append(
            "States a pesticide/medicine dosage: needs expert or official sourcing before it stands."
        )
    if matches.get("marketing_language"):
        notes.append("Marketing/guarantee language detected.")
    if signals.get("duplicate_posts"):
        notes.append(
            f"Same opening text appears in {signals['duplicate_posts']} other published post(s)."
        )
    if signals.get("author_prior_actions"):
        notes.append(f"Author has {signals['author_prior_actions']} previous moderation action(s).")
    if not notes:
        notes.append(
            "No automated signal fired; this case is queued purely on the reporter's report."
        )
    notes.append(
        "These are advisory signals for the moderator. They are not evidence that the content is false or "
        "harmful, and the system never hides content automatically."
    )
    return notes
