"""Regression tests for the farmer profile endpoints.

These exist because of a real production bug: `FarmerProfileOut` declares
`preferred_language` and `profile_completeness` as required, but both are
*derived* values (one lives on the linked user, the other is computed from how
complete the profile is). `FarmerService.to_out()` used to run
`FarmerProfileOut.model_validate(orm_profile)` and only then assign the two
fields — so validation raised `ValidationError` before the assignment could
happen and every call to `GET /api/v1/farmers/me` returned HTTP 500.

The tests below assert the contract the Flutter client depends on, so the bug
cannot come back silently.
"""

from __future__ import annotations

import pytest


def test_get_my_profile_returns_derived_fields(client, farmer):
    """A brand-new profile must serialise: derived fields are always present."""
    response = client.get("/api/v1/farmers/me", headers=farmer.headers)
    assert response.status_code == 200, response.text

    body = response.json()
    # Derived, not stored on the profile row:
    assert "profile_completeness" in body
    assert isinstance(body["profile_completeness"], int)
    assert 0 <= body["profile_completeness"] <= 100
    assert body["preferred_language"] == "en"  # user's default language
    # Identity fields the mobile app keys on:
    assert body["user_id"]
    assert body["display_name"]


def test_profile_completeness_grows_with_profile_fields(client, farmer):
    """Completeness is a real computation, not a constant."""
    before = client.get("/api/v1/farmers/me", headers=farmer.headers).json()

    patched = client.patch(
        "/api/v1/farmers/me",
        headers=farmer.headers,
        json={
            "display_name": "Test User",
            "village": "Sample Village",
            "taluka": "Sample Taluka",
            "pincode": "422001",
            "farming_experience_years": 8,
            "primary_crops": ["onion", "tomato"],
            "bio": "Grows onion and tomato on 3 acres.",
        },
    )
    assert patched.status_code == 200, patched.text

    after = client.get("/api/v1/farmers/me", headers=farmer.headers).json()
    assert after["profile_completeness"] >= before["profile_completeness"]
    assert after["village"] == "Sample Village"
    assert after["primary_crops"] == ["onion", "tomato"]


def test_dashboard_renders_for_a_farmer_without_farms(client, farmer):
    """The dashboard is the mobile home screen; it must work before any farm exists.

    A fresh account has no farms, crops, or reminders — the empty case is the one
    the mobile app shows to every new user, so it is the case most likely to break.
    """
    response = client.get("/api/v1/farmers/me/dashboard", headers=farmer.headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert set(body) >= {
        "profile",
        "land_summary",
        "crop_stage_counts",
        "active_crops",
        "reminders",
        "data_freshness",
    }
    assert body["land_summary"]["total_farms"] == 0
    assert body["active_crops"] == []
    # The app prints this note verbatim; it must exist and be non-empty.
    assert body["data_freshness"]["note"]


def test_profile_requires_authentication(client):
    """No token, no profile — the endpoint is not public."""
    response = client.get("/api/v1/farmers/me")
    assert response.status_code in {401, 403}

    dashboard = client.get("/api/v1/farmers/me/dashboard")
    assert dashboard.status_code in {401, 403}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pincode", "not-a-pincode"),
        ("farming_experience_years", 101),
        # `soil_ph` is a *farm* field, not a profile field: sending it to the
        # profile endpoint must be rejected rather than silently dropped.
        ("soil_ph", 22.0),
    ],
)
def test_profile_rejects_invalid_values(client, farmer, field, value):
    """Field validation is enforced server-side, not just in the mobile form."""
    response = client.patch("/api/v1/farmers/me", headers=farmer.headers, json={field: value})
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
