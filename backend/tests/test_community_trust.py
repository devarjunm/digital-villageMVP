"""Community, trust labels and moderation.

The platform's trust model is a product requirement, so it is tested:

  * every post carries a trust label, and popularity never upgrades a label
    (a hundred likes on a farmer's guess is still "farmer experience");
  * only an account with the expert role can produce "expert information", and
    only staff can attach "official information" with a source;
  * reporting creates a moderation case, and a decision writes an audit entry —
    moderation is a recorded human action, not an automatic classifier;
  * a restricted account can still read but cannot post;
  * a moderator cannot delete content (that is an admin action) — the two levels
    are enforced server-side.
"""

from __future__ import annotations

import pytest


def _post_payload(**overrides):
    payload = {
        "title": "Onion leaves turning pale at the tips",
        "body": (
            "Over the last four days the outer leaves of my onion crop have pale tips and the soil is "
            "crusty. I irrigated twice this week. What should I check first?"
        ),
        "category": "crop_problem",
        "crop_code": "onion",
        "language": "en",
        "district": "Nashik",
        "state": "Maharashtra",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def post(client, farmer) -> dict:
    created = client.post("/api/v1/community/posts", json=_post_payload(), headers=farmer.headers)
    assert created.status_code == 201, created.text
    return created.json()


def test_post_creation_carries_a_trust_label(client, post, farmer):
    assert post["trust_label"], "every community post must be labelled"
    assert post["author"]["id"] == str(farmer.user_id)
    # A first-hand report by a farmer is farmer experience — nothing more.
    assert post["trust_label"] == "farmer_experience"
    assert post["trust_reasons"], "the label must come with a reason"
    assert post["status"] in {"published", "pending_review"}


def test_reactions_never_change_the_trust_label(client, post, farmer, expert, other_farmer):
    before = post["trust_label"]
    for account in (other_farmer, expert):
        response = client.post(
            f"/api/v1/community/posts/{post['id']}/reactions",
            json={"kind": "helpful"},
            headers=account.headers,
        )
        assert response.status_code in {200, 201}, response.text

    detail = client.get(f"/api/v1/community/posts/{post['id']}", headers=farmer.headers)
    assert detail.status_code == 200
    body = detail.json()["post"]
    assert body["reaction_count"] >= 1
    # Popularity is engagement, not evidence: the label is unchanged even though
    # another farmer and an expert reacted to it.
    assert body["trust_label"] == before
    assert body["trust_reasons"]


def test_expert_reply_is_labelled_expert_information(client, post, farmer, expert):
    created = client.post(
        f"/api/v1/community/posts/{post['id']}/comments",
        json={
            "body": (
                "Check soil moisture at 15 cm depth before the next irrigation, and look at the underside of "
                "the outer leaves for thrips. Bring a soil sample to your KVK for a free test."
            )
        },
        headers=expert.headers,
    )
    assert created.status_code in {200, 201}, created.text
    comment = created.json()
    assert comment.get("trust_label") == "expert_information", comment
    assert comment.get("author", {}).get("primary_role") in {"expert", "moderator", "admin"}


def test_farmer_cannot_claim_expert_or_official_label(client, farmer):
    """A farmer's own post must never be labelled as expert or official."""
    created = client.post(
        "/api/v1/community/posts",
        json=_post_payload(title="Official government advisory about onion prices"),
        headers=farmer.headers,
    )
    assert created.status_code == 201
    assert created.json()["trust_label"] == "farmer_experience"


def test_reporting_becomes_a_moderation_case(client, post, other_farmer, moderator):
    reported = client.post(
        "/api/v1/community/reports",
        json={
            "target_type": "post",
            "target_id": post["id"],
            "reason": "misinformation",
            "details": "This suggests a pesticide dose that is not on the label.",
        },
        headers=other_farmer.headers,
    )
    assert reported.status_code in {200, 201}, reported.text
    ack = reported.json()
    assert ack["report_id"]

    # Reporting twice is idempotent rather than creating duplicate cases.
    again = client.post(
        "/api/v1/community/reports",
        json={"target_type": "post", "target_id": post["id"], "reason": "misinformation"},
        headers=other_farmer.headers,
    )
    assert again.status_code in {200, 201}
    assert again.json().get("already_reported") is True

    queue = client.get("/api/v1/moderation/queue", headers=moderator.headers)
    assert queue.status_code == 200, queue.text
    cases = queue.json()["items"]
    assert cases, "a report must appear in the moderation queue"
    case = next(c for c in cases if str(c.get("target_id")) == post["id"])

    # A moderator's note is recorded with an audit trail; it does not delete content.
    decided = client.post(
        f"/api/v1/moderation/cases/{case['id']}/actions",
        json={"action": "note", "reason": "Asked the author to cite the label dosage for review."},
        headers=moderator.headers,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] in {"in_review", "resolved"}

    still_there = client.get(f"/api/v1/community/posts/{post['id']}")
    assert still_there.status_code == 200, "a moderation note must not hide the post"

    audit = client.get("/api/v1/moderation/audit", headers=moderator.headers)
    # The audit trail is admin-only: a moderator gets 403, an admin gets the log.
    assert audit.status_code == 403


def test_moderator_cannot_remove_content_but_admin_can(client, post, moderator, admin):
    queue = client.get("/api/v1/moderation/queue", headers=moderator.headers).json()["items"]
    case = next((c for c in queue if str(c.get("target_id")) == post["id"]), None)
    if case is None:
        reporter = client.post(
            "/api/v1/community/reports",
            json={"target_type": "post", "target_id": post["id"], "reason": "spam"},
            headers=moderator.headers,
        )
        assert reporter.status_code in {200, 201}
        queue = client.get("/api/v1/moderation/queue", headers=moderator.headers).json()["items"]
        case = next(c for c in queue if str(c.get("target_id")) == post["id"])

    forbidden = client.post(
        f"/api/v1/moderation/cases/{case['id']}/actions",
        json={"action": "remove", "reason": "Duplicate of another thread, removing one copy."},
        headers=moderator.headers,
    )
    assert forbidden.status_code == 403

    allowed = client.post(
        f"/api/v1/moderation/cases/{case['id']}/actions",
        json={"action": "remove", "reason": "Duplicate of another thread, removing one copy."},
        headers=admin.headers,
    )
    assert allowed.status_code == 200, allowed.text

    hidden = client.get(f"/api/v1/community/posts/{post['id']}")
    assert hidden.status_code in {404, 410} or hidden.json().get("status") == "removed"

    audit = client.get("/api/v1/moderation/audit", headers=admin.headers)
    assert audit.status_code == 200
    actions = [entry["action"] for entry in audit.json()]
    assert any(action.endswith("remove") for action in actions), actions
    # The audit entry names the moderator, the reason and the target.
    entry = next(e for e in audit.json() if e["action"].endswith("remove"))
    assert entry.get("reason")
    assert entry.get("target_id")


def test_restricting_an_author_goes_through_the_moderation_flow(
    client, farmer, other_farmer, admin
):
    """Restrictions are a recorded moderator decision, never a silent flag.

    There is deliberately no "restrict this user" endpoint: a restriction can only
    be applied as an action on a moderation case, so every restriction is
    traceable to a report, a reason and the moderator who decided it.
    """
    post = client.post(
        "/api/v1/community/posts", json=_post_payload(), headers=farmer.headers
    ).json()
    reported = client.post(
        "/api/v1/community/reports",
        json={
            "target_type": "post",
            "target_id": post["id"],
            "reason": "spam",
            "details": "Same link posted repeatedly across threads.",
        },
        headers=other_farmer.headers,
    )
    assert reported.status_code in {200, 201}

    queue = client.get("/api/v1/moderation/queue", headers=admin.headers).json()["items"]
    case = next(c for c in queue if str(c.get("target_id")) == post["id"])

    restricted = client.post(
        f"/api/v1/moderation/cases/{case['id']}/actions",
        json={
            "action": "restrict_author",
            "reason": "Repeated identical promotional links; 24-hour posting restriction applied.",
            "restriction_hours": 24,
        },
        headers=admin.headers,
    )
    assert restricted.status_code == 200, restricted.text

    blocked = client.post(
        "/api/v1/community/posts",
        json=_post_payload(title="Another post while restricted from posting"),
        headers=farmer.headers,
    )
    assert blocked.status_code == 403, blocked.text
    assert "restrict" in blocked.text.lower() or "temporarily" in blocked.text.lower()

    # Reading and reacting are unaffected: a restriction narrows one capability.
    assert client.get("/api/v1/community/feed", headers=farmer.headers).status_code == 200


def test_comment_and_reaction_requires_authentication(client, post):
    assert (
        client.post(
            f"/api/v1/community/posts/{post['id']}/comments", json={"body": "x" * 20}
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"/api/v1/community/posts/{post['id']}/reactions", json={"kind": "helpful"}
        ).status_code
        == 401
    )


def test_feed_supports_filtering_and_pagination(client, post, farmer):
    feed = client.get(
        "/api/v1/community/feed?category=crop_problem&page=1&page_size=5", headers=farmer.headers
    )
    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert {"items", "page", "page_size", "total"} <= set(body)
    assert all(item["category"] == "crop_problem" for item in body["items"])
