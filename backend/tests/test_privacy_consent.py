"""Consent, data export, analytics gating and account deletion.

These tests cover the privacy promises the platform makes, and each one is
checked against behaviour rather than wording:

  * a purpose with no recorded decision is treated as *refused*;
  * product analytics for a signed-in user is dropped unless consent was given;
  * the export contains the account's own data and never a password hash;
  * deleting an account erases identifiers, revokes every session and frees the
    phone number, while saying plainly what is kept and why.
"""

from __future__ import annotations


def test_purposes_are_described_without_authentication(client):
    response = client.get("/api/v1/users/consents/purposes")
    assert response.status_code == 200
    body = response.json()
    assert body["policy_version"]
    kinds = {item["kind"] for item in body["purposes"]}
    assert {"analytics", "model_training", "marketing"} <= kinds
    for item in body["purposes"]:
        assert item["title"] and item["description"]
        assert item["required"] is False, "no optional-only purpose may be mandatory in this build"


def test_no_consent_means_no_consent(client, farmer):
    response = client.get("/api/v1/users/me/consents", headers=farmer.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["policy_version"]
    assert all(item["granted"] is False for item in body["items"])
    assert all(item["decided_at"] is None for item in body["items"])


def test_recording_consent_is_versioned_and_revocable(client, farmer):
    overview = client.get("/api/v1/users/me/consents", headers=farmer.headers).json()
    version = overview["policy_version"]
    granted = client.patch(
        "/api/v1/users/me/consents",
        json={
            "decisions": [
                {"kind": "analytics", "granted": True},
                {"kind": "model_training", "granted": False},
            ],
            "policy_version": version,
        },
        headers=farmer.headers,
    )
    assert granted.status_code == 200, granted.text
    items = {item["kind"]: item for item in granted.json()["items"]}
    assert items["analytics"]["granted"] is True
    assert items["analytics"]["decided_at"]
    assert items["model_training"]["granted"] is False
    # Nothing else was silently switched on as a side effect.
    assert items["marketing"]["granted"] is False

    revoked = client.patch(
        "/api/v1/users/me/consents",
        json={"decisions": [{"kind": "analytics", "granted": False}], "policy_version": version},
        headers=farmer.headers,
    )
    assert revoked.status_code == 200
    items = {item["kind"]: item for item in revoked.json()["items"]}
    assert items["analytics"]["granted"] is False
    assert items["analytics"]["revoked_at"]


def test_stale_policy_version_is_rejected(client, farmer):
    """A screen showing old wording must not record a decision against the new one."""
    response = client.patch(
        "/api/v1/users/me/consents",
        json={
            "decisions": [{"kind": "analytics", "granted": True}],
            "policy_version": "1999-01-01",
        },
        headers=farmer.headers,
    )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert details["current_policy_version"]


def test_analytics_events_are_not_recorded_without_consent(client, farmer, db):
    """The gate is real: no consent ⇒ the event never reaches the database."""
    from sqlalchemy import func, select

    from app.analytics.models import ProductEvent

    # An endpoint that records a product event when it runs.
    created = client.post(
        "/api/v1/farms",
        json={"name": "Consent test plot", "area_value": 1.0, "area_unit": "acre"},
        headers=farmer.headers,
    )
    assert created.status_code == 201

    count_without = db.execute(
        select(func.count()).select_from(ProductEvent).where(ProductEvent.user_id == farmer.user_id)
    ).scalar_one()
    assert count_without == 0, "signed-in analytics must be off until the purpose is granted"

    # Grant analytics, then repeat the action.
    version = client.get("/api/v1/users/me/consents", headers=farmer.headers).json()[
        "policy_version"
    ]
    client.patch(
        "/api/v1/users/me/consents",
        json={"decisions": [{"kind": "analytics", "granted": True}], "policy_version": version},
        headers=farmer.headers,
    )
    again = client.post(
        "/api/v1/farms",
        json={"name": "Consent test plot 2", "area_value": 1.0, "area_unit": "acre"},
        headers=farmer.headers,
    )
    assert again.status_code == 201
    count_with = db.execute(
        select(func.count()).select_from(ProductEvent).where(ProductEvent.user_id == farmer.user_id)
    ).scalar_one()
    assert count_with >= 1, "with consent granted the event must be recorded"


def test_analytics_preferences_endpoint_reflects_consent(client, farmer):
    preferences = client.get("/api/v1/analytics/me/preferences", headers=farmer.headers)
    assert preferences.status_code == 200
    assert preferences.json()["analytics_opt_in"] is False

    updated = client.patch(
        "/api/v1/analytics/me/preferences?analytics_opt_in=true", headers=farmer.headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["saved"] is True

    after = client.get("/api/v1/analytics/me/preferences", headers=farmer.headers)
    assert after.json()["analytics_opt_in"] is True
    # The two endpoints must not disagree: consent is the single source of truth.
    consents = client.get("/api/v1/users/me/consents", headers=farmer.headers).json()
    analytics = next(item for item in consents["items"] if item["kind"] == "analytics")
    assert analytics["granted"] is True


def test_transparency_endpoint_shows_the_users_own_events(client, farmer):
    events = client.get("/api/v1/analytics/me/events", headers=farmer.headers)
    assert events.status_code == 200
    body = events.json()
    assert "items" in body and "note" in body
    # A user can always see what is stored about them, even with analytics off.
    version = client.get("/api/v1/users/me/consents", headers=farmer.headers).json()[
        "policy_version"
    ]
    client.patch(
        "/api/v1/users/me/consents",
        json={"decisions": [{"kind": "analytics", "granted": True}], "policy_version": version},
        headers=farmer.headers,
    )
    client.post(
        "/api/v1/farms",
        json={"name": "Transparency plot", "area_value": 0.5, "area_unit": "acre"},
        headers=farmer.headers,
    )
    after = client.get("/api/v1/analytics/me/events", headers=farmer.headers).json()
    assert after["count"] >= 1
    assert all("props" in item for item in after["items"])


def test_data_export_contains_only_my_data(client, farmer, other_farmer):
    farm = client.post(
        "/api/v1/farms",
        json={"name": "Export plot", "area_value": 1.0, "area_unit": "acre", "district": "Nashik"},
        headers=farmer.headers,
    ).json()
    client.post(
        "/api/v1/farms",
        json={"name": "Someone else's plot", "area_value": 2.0, "area_unit": "acre"},
        headers=other_farmer.headers,
    ).json()

    export = client.get("/api/v1/users/me/data-export", headers=farmer.headers)
    assert export.status_code == 200, export.text
    body = export.json()

    assert body["account"]["id"] == str(farmer.user_id)
    assert body["account"]["phone_e164"] == farmer.phone
    farm_names = {item["name"] for item in body["farms"]}
    assert "Export plot" in farm_names
    assert "Someone else's plot" not in farm_names
    assert str(farm["id"]) in {item["id"] for item in body["farms"]}

    # No credentials, no hashes, and the omissions are stated explicitly.
    serialized = export.text.lower()
    for forbidden in ("password_hash", "token_hash", "code_hash", "argon2"):
        assert forbidden not in serialized
    assert body["not_included"], "the export must state what it leaves out"


def test_export_confirmation_endpoint_requires_the_word(client, farmer):
    assert (
        client.post(
            "/api/v1/users/me/data-export/request", json={"confirm": "yes"}, headers=farmer.headers
        ).status_code
        == 422
    )
    ok = client.post(
        "/api/v1/users/me/data-export/request", json={"confirm": "EXPORT"}, headers=farmer.headers
    )
    assert ok.status_code == 200
    assert ok.json()["account"]["id"] == str(farmer.user_id)


def test_account_deletion_erases_identifiers_and_revokes_sessions(client, db, farmer):
    from sqlalchemy import func, select

    from app.users.models import RefreshToken, User

    login = client.post(
        "/api/v1/auth/login", json={"identifier": farmer.phone, "password": farmer.password}
    )
    assert login.status_code == 200

    deleted = client.request(
        "DELETE", "/api/v1/users/me", json={"confirm": "DELETE"}, headers=farmer.headers
    )
    assert deleted.status_code == 202, deleted.text
    receipt = deleted.json()
    assert receipt["status"] == "deleted"
    assert receipt["receipt"]["erased"]
    assert receipt["receipt"]["retained"]

    row = db.execute(select(User).where(User.id == farmer.user_id)).scalar_one()
    assert row.phone_e164 is None
    assert row.email is None
    assert row.password_hash is None
    assert row.full_name == "Deleted account"
    assert row.status.value == "disabled"
    assert row.token_version >= 1

    live_sessions = db.execute(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == farmer.user_id, RefreshToken.revoked_at.is_(None))
    ).scalar_one()
    assert live_sessions == 0, "every session must be revoked on deletion"

    # The old token no longer works.
    assert client.get("/api/v1/users/me", headers=farmer.headers).status_code in {401, 403}

    # The phone number is free again: the farmer can register afresh.
    fresh = client.post(
        "/api/v1/auth/register",
        json={"full_name": "Same Farmer Again", "phone": farmer.phone, "password": "NewStart!2026"},
    )
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["status"] in {"pending_verification", "active"}


def test_deletion_letter_is_required(client, farmer):
    assert (
        client.request(
            "DELETE", "/api/v1/users/me", json={"confirm": "maybe"}, headers=farmer.headers
        ).status_code
        == 422
    )
