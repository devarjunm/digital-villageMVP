"""Farm and crop lifecycle, including ownership enforcement.

The important assertions here are the authorisation ones: a farmer must not be
able to read or modify another farmer's farm, crop or soil test, and the API must
answer with 404 (not 403) so it does not confirm that the row exists.
"""

from __future__ import annotations

from datetime import date, timedelta


def _farm_payload(**overrides):
    payload = {
        "name": "Survey 42 — onion plot",
        "area_value": 2.5,
        "area_unit": "acre",
        "village": "Sample Village",
        "taluka": "Sample Taluka",
        "district": "Nashik",
        "state": "Maharashtra",
        "latitude": 19.9975,
        "longitude": 73.7898,
        "soil_type": "black_cotton",
        "soil_ph": 7.4,
        "irrigation_type": "drip",
        "ownership_type": "owned",
    }
    payload.update(overrides)
    return payload


def test_create_and_read_a_farm(client, farmer):
    created = client.post("/api/v1/farms", json=_farm_payload(), headers=farmer.headers)
    assert created.status_code == 201, created.text
    farm = created.json()
    assert farm["name"] == "Survey 42 — onion plot"
    # Areas are converted once, server-side, so clients never re-implement unit maths.
    assert (
        farm["area_hectares"] == round(2.5 * 0.4046856, 4)
        or abs(farm["area_hectares"] - 1.0117) < 0.01
    )

    listed = client.get("/api/v1/farms", headers=farmer.headers).json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert [str(item["id"]) for item in items] == [farm["id"]]

    detail = client.get(f"/api/v1/farms/{farm['id']}", headers=farmer.headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == farm["id"]


def test_farm_requires_authentication(client):
    assert client.post("/api/v1/farms", json=_farm_payload()).status_code == 401


def test_farm_validation_rejects_impossible_values(client, farmer):
    assert (
        client.post(
            "/api/v1/farms", json=_farm_payload(area_value=0), headers=farmer.headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/farms", json=_farm_payload(soil_ph=18), headers=farmer.headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/farms", json=_farm_payload(latitude=200), headers=farmer.headers
        ).status_code
        == 422
    )


def test_another_farmer_cannot_touch_my_farm(client, farmer, other_farmer):
    farm = client.post("/api/v1/farms", json=_farm_payload(), headers=farmer.headers).json()

    assert (
        client.get(f"/api/v1/farms/{farm['id']}", headers=other_farmer.headers).status_code == 404
    )
    update = client.patch(
        f"/api/v1/farms/{farm['id']}", json={"name": "Hijacked plot"}, headers=other_farmer.headers
    )
    assert update.status_code == 404
    delete = client.delete(f"/api/v1/farms/{farm['id']}", headers=other_farmer.headers)
    assert delete.status_code == 404
    # And the farm is untouched.
    still_there = client.get(f"/api/v1/farms/{farm['id']}", headers=farmer.headers)
    assert still_there.status_code == 200
    assert still_there.json()["name"] == "Survey 42 — onion plot"


def test_crop_lifecycle_and_catalog_link(client, farmer):
    farm = client.post("/api/v1/farms", json=_farm_payload(), headers=farmer.headers).json()

    catalog = client.get("/api/v1/crops/catalog", headers=farmer.headers)
    assert catalog.status_code == 200
    codes = {entry["code"] for entry in catalog.json()}
    assert "onion" in codes, "the crop catalog must be populated (see scripts/seed_demo.py)"

    sowing = date.today() - timedelta(days=30)
    created = client.post(
        f"/api/v1/farms/{farm['id']}/crops",
        json={
            "crop_code": "onion",
            "variety": "Bhima Super",
            "season": "rabi",
            "sowing_date": sowing.isoformat(),
            "area_value": 1.5,
            "area_unit": "acre",
            "stage": "vegetative",
            "irrigation_method": "drip",
        },
        headers=farmer.headers,
    )
    assert created.status_code == 201, created.text
    crop = created.json()
    assert crop["crop_code"] == "onion"
    assert crop["stage"] == "vegetative"

    detail = client.get(f"/api/v1/crops/{crop['id']}", headers=farmer.headers)
    assert detail.status_code == 200

    updated = client.patch(
        f"/api/v1/crops/{crop['id']}", json={"stage": "flowering"}, headers=farmer.headers
    )
    assert updated.status_code == 200
    assert updated.json()["stage"] == "flowering"

    # Crop events are the farm diary; an event must be recorded, not inferred.
    event = client.post(
        f"/api/v1/crops/{crop['id']}/events",
        json={
            "event_type": "irrigation",
            "event_date": date.today().isoformat(),
            "notes": "Drip run for 45 minutes.",
            "quantity": 45,
            "unit": "minutes",
        },
        headers=farmer.headers,
    )
    assert event.status_code in {200, 201}, event.text
    events = client.get(f"/api/v1/crops/{crop['id']}/events", headers=farmer.headers).json()
    items = events["items"] if isinstance(events, dict) else events
    assert any(item.get("event_type") == "irrigation" for item in items)


def test_crop_rejects_unknown_crop_code(client, farmer):
    farm = client.post("/api/v1/farms", json=_farm_payload(), headers=farmer.headers).json()
    response = client.post(
        f"/api/v1/farms/{farm['id']}/crops",
        json={"crop_code": "unobtainium", "area_value": 1, "area_unit": "acre"},
        headers=farmer.headers,
    )
    assert response.status_code in {400, 404, 422}


def test_other_farmer_cannot_add_crops_to_my_farm(client, farmer, other_farmer):
    farm = client.post("/api/v1/farms", json=_farm_payload(), headers=farmer.headers).json()
    response = client.post(
        f"/api/v1/farms/{farm['id']}/crops",
        json={"crop_code": "onion", "area_value": 1, "area_unit": "acre"},
        headers=other_farmer.headers,
    )
    assert response.status_code == 404


def test_farm_summary_is_scoped_to_the_owner(client, farmer, other_farmer):
    farm = client.post("/api/v1/farms", json=_farm_payload(), headers=farmer.headers).json()
    assert (
        client.get(f"/api/v1/farms/{farm['id']}/summary", headers=farmer.headers).status_code == 200
    )
    assert (
        client.get(f"/api/v1/farms/{farm['id']}/summary", headers=other_farmer.headers).status_code
        == 404
    )


def test_soft_deleted_farm_disappears_from_the_list(client, farmer):
    farm = client.post("/api/v1/farms", json=_farm_payload(), headers=farmer.headers).json()
    assert client.delete(f"/api/v1/farms/{farm['id']}", headers=farmer.headers).status_code in {
        200,
        204,
    }
    listed = client.get("/api/v1/farms", headers=farmer.headers).json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert str(farm["id"]) not in {str(item["id"]) for item in items}
    # A deleted farm must not be readable any more either.
    assert client.get(f"/api/v1/farms/{farm['id']}", headers=farmer.headers).status_code == 404
