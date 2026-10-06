"""Weather, market, scheme, search and notification contracts.

The rule tested here is provenance: anything the app shows that comes from
outside the platform must say **where it came from** and whether it is a
development stand-in. A response that quietly returns mock weather as if it were
a live forecast is the failure mode this file exists to prevent.
"""

from __future__ import annotations

from datetime import date, timedelta


# --------------------------------------------------------------------- weather
def test_weather_reports_provider_and_labels_demo_data(client, farmer):
    response = client.get(
        "/api/v1/weather/current?latitude=19.9975&longitude=73.7898", headers=farmer.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"], "every weather response must name its provider"
    assert body["source"]
    assert body["observed_at"]
    if body["provider"] == "mock":
        assert body["is_demo"] is True
        assert body["demo_notice"], "a demo provider must say so in the payload itself"


def test_weather_forecast_is_labelled_and_bounded(client, farmer):
    response = client.get(
        "/api/v1/weather/forecast?latitude=19.9975&longitude=73.7898&days=3", headers=farmer.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"]
    assert len(body["days"]) == 3
    for day in body["days"]:
        assert day["forecast_for"], "each forecast day must carry its own date"
        assert day["condition_text"]
    # Advisories are derived from screening thresholds and must say so.
    assert body["advisories_data_class"] == "derived"
    if body["is_demo"]:
        assert body["demo_notice"]


def test_weather_rejects_impossible_coordinates(client, farmer):
    assert (
        client.get(
            "/api/v1/weather/current?latitude=120&longitude=73", headers=farmer.headers
        ).status_code
        == 422
    )


def test_weather_alerts_state_absence_of_feed(client, farmer):
    response = client.get("/api/v1/weather/alerts?state=Maharashtra", headers=farmer.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    if body.get("supported") is False:
        # Absence of a feed must not be reported as "no warnings in your area".
        assert body["notice"]
        assert "not a statement" in body["notice"].lower() or "no alerts" in body["notice"].lower()


def test_weather_provider_endpoint_is_explicit(client, farmer):
    body = client.get("/api/v1/weather/provider", headers=farmer.headers).json()
    assert "provider" in body
    assert "is_demo" in body


# --------------------------------------------------------------------- markets
def test_market_prices_carry_source_and_demo_flag(client, farmer):
    today = date.today()
    response = client.get(
        "/api/v1/markets/prices"
        f"?crop=onion&state=Maharashtra"
        f"&from_date={(today - timedelta(days=7)).isoformat()}&to_date={today.isoformat()}",
        headers=farmer.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] and body["source"]
    assert body["disclaimer"]
    assert body["count"] == len(body["items"])
    for row in body["items"]:
        # Modelled prices must be distinguishable from reported ones.
        assert "is_estimate" in row
        assert row["price_date"]
        assert row["modal_price"] is not None
    if body["is_demo"]:
        assert body["notices"], "demo market data must carry a notice"


def test_market_rejects_unknown_crop(client, farmer):
    response = client.get("/api/v1/markets/prices?crop=unobtainium", headers=farmer.headers)
    assert response.status_code == 422
    # The error must name the supported crops rather than just "invalid".
    assert response.json()["error"]["details"]["supported"]


def test_market_provider_endpoint_describes_configuration(client, farmer):
    response = client.get("/api/v1/markets/provider", headers=farmer.headers)
    assert response.status_code == 200
    body = response.json()
    assert "provider" in body


# --------------------------------------------------------------------- schemes
def test_scheme_list_labels_demo_records(client, farmer):
    response = client.get("/api/v1/schemes", headers=farmer.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" in body and "total" in body
    for item in body["items"]:
        assert item["official_source_url"], "a scheme must always carry its official source"
        assert item["verification_status"]
        if item["is_demo"]:
            # Demo scheme rows must be visibly marked as placeholders.
            assert item["content_notice"] or item["is_demo"] is True
            assert (
                "demo" in (item["content_notice"] or "").lower()
                or "placeholder" in (item["content_notice"] or "").lower()
            )


def test_scheme_eligibility_reads_the_rule_values_that_are_actually_stored(
    client, db, farmer, other_farmer
):
    """Both stored spellings of a rule value must decide the outcome.

    Regression test: rules stored as {"threshold": 2.0} / {"options": [...]} were
    read as `value["value"]` (None), so a hard `state in [...]` rule always
    "failed" and every numeric rule silently became "unknown".
    """
    from app.core.enums import VerificationStatus
    from app.schemes.models import Scheme, SchemeEligibilityRule

    scheme = Scheme(
        slug="test-screening-scheme",
        name_en="Test screening scheme",
        description_en="Fixture scheme used to exercise the rule evaluator.",
        category="income_support",
        level="state",
        state_codes=["Maharashtra"],
        crop_codes=["onion"],
        official_source_name="Test source",
        official_source_url="https://example.gov.in/test-scheme",
        verification_status=VerificationStatus.UNVERIFIED,
        is_demo=True,
    )
    db.add(scheme)
    db.flush()
    db.add_all(
        [
            # hard, numeric, stored under "threshold"
            SchemeEligibilityRule(
                scheme_id=scheme.id,
                field="land_holding_hectares",
                operator="<=",
                value={"threshold": 2.0},
                is_hard_requirement=True,
                source_reference="clause 2.1",
            ),
            # hard, set membership, stored under "options"
            SchemeEligibilityRule(
                scheme_id=scheme.id,
                field="state",
                operator="in",
                value={"options": ["Maharashtra"]},
                is_hard_requirement=True,
            ),
            # soft, needs information the farmer has not given
            SchemeEligibilityRule(
                scheme_id=scheme.id,
                field="has_kcc",
                operator="is_true",
                value={},
                is_hard_requirement=False,
            ),
        ]
    )
    db.flush()

    farm = client.post(
        "/api/v1/farms",
        json={
            "name": "Screening plot",
            "area_value": 1.0,
            "area_unit": "acre",
            "state": "Maharashtra",
            "district": "Nashik",
            "ownership_type": "owned",
        },
        headers=farmer.headers,
    )
    assert farm.status_code == 201, farm.text

    response = client.post(
        "/api/v1/schemes/test-screening-scheme/eligibility-check",
        json={"has_kcc": True},
        headers=farmer.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # Every rule must be judged on its real value, so nothing is "unknown".
    assert body["unknown"] == [], f"rules were not evaluated: {body['unknown']}"
    assert body["configuration_warnings"] == []
    passed_fields = {outcome["field"]: outcome for outcome in body["passed"]}
    assert "land_holding_hectares" in passed_fields, body
    assert passed_fields["land_holding_hectares"]["required_value"] == 2.0
    assert passed_fields["state"]["required_value"] == ["Maharashtra"]
    assert body["missing_inputs"] == []
    assert body["status"] == "likely_eligible", body["explanation"]

    # A farmer outside the state fails the hard state rule — with the reason given.
    other = client.post(
        "/api/v1/farms",
        json={
            "name": "Out of state plot",
            "area_value": 1.0,
            "area_unit": "acre",
            "state": "Karnataka",
            "district": "Belagavi",
            "ownership_type": "owned",
        },
        headers=other_farmer.headers,
    )
    assert other.status_code == 201, other.text
    out_of_state = client.post(
        "/api/v1/schemes/test-screening-scheme/eligibility-check",
        json={"has_kcc": True},
        headers=other_farmer.headers,
    ).json()
    assert out_of_state["status"] == "likely_not_eligible"
    failed_fields = {outcome["field"] for outcome in out_of_state["failed"]}
    assert "state" in failed_fields
    assert out_of_state["official_source_url"] == "https://example.gov.in/test-scheme"
    assert out_of_state["disclaimer"]


def test_unreadable_rule_value_is_reported_not_silently_failed(client, db, farmer):
    """A rule whose stored value is unusable must not become a failed requirement."""
    from app.core.enums import VerificationStatus
    from app.schemes.models import Scheme, SchemeEligibilityRule

    scheme = Scheme(
        slug="test-broken-rule-scheme",
        name_en="Test broken-rule scheme",
        description_en="Fixture scheme with one unusable rule value.",
        category="income_support",
        level="central",
        state_codes=[],
        official_source_name="Test source",
        official_source_url="https://example.gov.in/broken-scheme",
        verification_status=VerificationStatus.UNVERIFIED,
        is_demo=True,
    )
    db.add(scheme)
    db.flush()
    db.add_all(
        [
            SchemeEligibilityRule(
                scheme_id=scheme.id,
                field="state",
                operator="in",
                value={"note": "options were lost in an import"},
                is_hard_requirement=True,
            ),
            SchemeEligibilityRule(
                scheme_id=scheme.id,
                field="land_holding_hectares",
                operator="<=",
                value={"threshold": 5.0},
                is_hard_requirement=True,
            ),
        ]
    )
    db.flush()
    client.post(
        "/api/v1/farms",
        json={
            "name": "Broken rule plot",
            "area_value": 1.0,
            "area_unit": "acre",
            "state": "Maharashtra",
        },
        headers=farmer.headers,
    )

    body = client.post(
        "/api/v1/schemes/test-broken-rule-scheme/eligibility-check", json={}, headers=farmer.headers
    ).json()

    assert body["failed"] == [], "an unreadable rule must never be reported as failed"
    unknown_fields = {outcome["field"] for outcome in body["unknown"]}
    assert unknown_fields == {"state"}
    # It is a data problem, not a missing self-reported input.
    assert body["missing_inputs"] == []
    assert body["configuration_warnings"] and "state" in body["configuration_warnings"][0]
    # And it blocks a positive verdict, because eligibility genuinely is unknown.
    assert body["status"] == "needs_more_information"
    assert "rule data is incomplete" in body["explanation"]


def test_scheme_recommendation_is_rule_based_and_disclosed(client, farmer):
    response = client.get("/api/v1/schemes/recommended", headers=farmer.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" in body
    assert "evaluated_schemes" in body or "note" in body
    for item in body["items"]:
        assert item.get("official_source_url") or item.get("source_reference")


# ---------------------------------------------------------------------- search
def test_search_returns_results_with_sources(client, farmer):
    created = client.post(
        "/api/v1/community/posts",
        json={
            "title": "Yellowing onion leaves after heavy rain",
            "body": "Three days of rain and now the oldest leaves are yellowing from the tip inwards.",
            "category": "crop_problem",
            "crop_code": "onion",
        },
        headers=farmer.headers,
    )
    assert created.status_code == 201

    response = client.get("/api/v1/search?q=yellowing%20onion%20leaves", headers=farmer.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    results = body["items"]
    assert results, "a search must find the post that was just created"
    for result in results:
        assert result["source_type"], "every hit must declare what it is"
        assert result["id"]
    # The search mode, the fusion method and any quality caveats must be disclosed.
    assert body["mode"] in {"keyword", "semantic", "hybrid"}
    assert body["method"]
    assert isinstance(body["notices"], list)


def test_search_reports_when_no_results_exist(client, farmer):
    body = client.get("/api/v1/search?q=zzqqxx-nonexistent-topic", headers=farmer.headers).json()
    assert body["items"] == []
    assert body["counts"]["total"] == 0
    # An empty result set must be explained in words, not left ambiguous.
    assert any("no results" in notice.lower() for notice in body["notices"])


# --------------------------------------------------------------- notifications
def test_notifications_require_authentication_and_are_user_scoped(client, db, farmer, other_farmer):
    assert client.get("/api/v1/notifications").status_code == 401

    from app.core.enums import NotificationType
    from app.notifications.models import Notification

    db.add(
        Notification(
            user_id=farmer.user_id,
            type=NotificationType.SYSTEM,
            title="Test notification",
            body="This notification exists to test the read path.",
        )
    )
    db.flush()

    mine = client.get("/api/v1/notifications", headers=farmer.headers)
    assert mine.status_code == 200, mine.text
    assert mine.json()["total"] >= 1

    theirs = client.get("/api/v1/notifications", headers=other_farmer.headers)
    assert theirs.status_code == 200
    assert theirs.json()["total"] == 0, "notifications must never leak across accounts"

    # Marking read is scoped to the owner as well.
    notice_id = mine.json()["items"][0]["id"]
    assert (
        client.post(
            f"/api/v1/notifications/{notice_id}/read", headers=other_farmer.headers
        ).status_code
        == 404
    )
    assert client.post(
        f"/api/v1/notifications/{notice_id}/read", headers=farmer.headers
    ).status_code in {200, 204}


def test_notification_preferences_are_stored_per_user(client, db, farmer, other_farmer):
    """A PATCH must persist, stay scoped to one account, and reject unknown keys.

    History: this test used to send `marketing_enabled`, a field that does not
    exist in `NotificationPreference` or `PreferenceUpdate`. Because the request
    schema ignored unknown keys, the API answered 200 while changing nothing —
    the test only passed because it asserted on *other* fields it never set.
    `PreferenceUpdate` is now strict, and this test exercises the real contract.
    """
    current = client.get("/api/v1/notifications/preferences", headers=farmer.headers)
    assert current.status_code == 200, current.text
    assert current.json()["market_updates"] is True  # documented default

    updated = client.patch(
        "/api/v1/notifications/preferences",
        json={"market_updates": False, "scheme_updates": True},
        headers=farmer.headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["market_updates"] is False
    assert updated.json()["scheme_updates"] is True

    # Persisted, not just echoed back from the request body.
    after = client.get("/api/v1/notifications/preferences", headers=farmer.headers).json()
    assert after["market_updates"] is False
    assert after["scheme_updates"] is True

    # Scoped: another account's preferences are untouched by my PATCH.
    theirs = client.get("/api/v1/notifications/preferences", headers=other_farmer.headers).json()
    assert theirs["market_updates"] is True
    assert theirs["scheme_updates"] is False

    # A mistyped field is now a named error instead of a silent no-op.
    typo = client.patch(
        "/api/v1/notifications/preferences",
        json={"market_updats": False},
        headers=farmer.headers,
    )
    assert typo.status_code == 422, typo.text
    assert typo.json()["error"]["code"] == "validation_error"
    field_errors = typo.json()["error"]["details"]["fields"]
    assert any("market_updats" in str(entry.get("loc", "")) for entry in field_errors)
