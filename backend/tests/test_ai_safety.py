"""AI behaviour tests — the safety rules, enforced.

The project's rules for AI output are product requirements, not style
preferences, so they are asserted here:

  * every result is labelled as model output and carries the model name, version
    and a confidence interpretation — never a bare number;
  * a score is never described as a probability unless the model card records a
    calibration step;
  * when no artefact exists for a model, the endpoint says so and returns no
    result at all (it must not invent a plausible label);
  * a disease scan outside the model's trained classes is refused/flagged rather
    than answered;
  * any recommendation that could lead to a consequential decision carries a
    "not a confirmed diagnosis / consult a professional" disclaimer;
  * requests are recorded (auditability) and provenance is reported.

The tests exercise the real endpoints with the real (seeded) artefacts on disk
and the mock LLM provider configured for development.
"""

from __future__ import annotations

import io

import pytest


def _png_bytes(width: int = 256, height: int = 256) -> bytes:
    """A real, decodable PNG (the upload validation checks content, not just MIME)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (60, 120, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def uploaded_leaf(client, farmer):
    """Upload a vegetable-leaf image through the media endpoint.

    This also verifies the upload path itself: the bytes go to the object-storage
    abstraction (not into PostgreSQL) and are validated server-side.
    """
    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("leaf.png", _png_bytes(), "image/png")},
        data={"purpose": "disease_scan"},
        headers=farmer.headers,
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["media"]["id"]
    assert payload["media"]["storage_backend"] in {"local", "s3", "gcs"}
    assert payload["validation"]["format"] == "PNG"
    assert payload["validation"]["width"] and payload["validation"]["height"]
    return payload["media"]


#: A complete, plausible input set for the crop-recommendation model. The model
#: requires every feature (it refuses to guess missing ones), so tests that expect
#: a 200 must supply all of them.
FULL_FEATURES = {
    "nitrogen": 90,
    "phosphorus": 42,
    "potassium": 43,
    "temperature_c": 26,
    "humidity_percent": 82,
    "ph": 6.5,
    "rainfall_mm": 200,
}


def test_crop_recommendation_reports_model_provenance(client, farmer):
    response = client.post(
        "/api/v1/ai/crop-recommendation",
        json={
            "nitrogen": 90,
            "phosphorus": 42,
            "potassium": 43,
            "temperature_c": 26,
            "humidity_percent": 82,
            "ph": 6.5,
            "rainfall_mm": 200,
            "top_k": 3,
        },
        headers=farmer.headers,
    )
    if response.status_code == 503:
        pytest.skip("no crop-recommendation artefact installed: " + response.text[:120])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_class"] == "model_output"
    assert body["model_name"] and body["model_version"]
    assert body["ranked"], "a successful recommendation must include ranked crops"
    # A score must be explained, not presented as a bare probability.
    assert body["score_type"]
    assert body["score_type_note"]
    assert body["confidence_interpretation"]
    assert (
        "probability" not in body["score_type"].lower()
        or "not" in body["confidence_interpretation"].lower()
    )
    # Provenance of every input is reported so the farmer can see what was used.
    assert set(body["inputs_used"]) == set(body["input_sources"])
    assert body["disclaimer"]
    assert body["limitations"], "limitations must accompany a recommendation"


def test_crop_recommendation_asks_for_missing_inputs(client, farmer):
    """Garbage-in must be refused with an explanation, not silently clamped."""
    response = client.post("/api/v1/ai/crop-recommendation", json={}, headers=farmer.headers)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] in {"validation_error", "insufficient_evidence"}


def test_disease_detection_is_labelled_and_cautious(client, farmer, uploaded_leaf):
    response = client.post(
        "/api/v1/ai/disease-detection",
        json={"media_id": uploaded_leaf["id"], "crop_code": "onion", "plant_part": "leaf"},
        headers=farmer.headers,
    )
    if response.status_code == 503:
        # No artefact installed: the platform must say so, never guess.
        error = response.json()["error"]
        assert error["code"] == "model_unavailable"
        assert "model" in error["message"].lower()
        pytest.skip("disease model artefact is not installed in this environment")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_class"] == "model_output"
    assert body["model_name"] and body["model_version"]
    assert body["confidence_interpretation"]
    assert body["recommendation"]
    assert body["disclaimer"]
    # "AI-assisted" framing is mandatory; a scan result is never a diagnosis.
    assert "diagnos" in body["disclaimer"].lower() or "confirm" in body["disclaimer"].lower()
    assert body["model_trained_classes"], "the trained label set must be disclosed"
    for prediction in body["predictions"]:
        assert prediction["label"] in body["model_trained_classes"]
        assert 0.0 <= prediction["score"] <= 1.0
        assert prediction["score_display"] <= 1.0
    # Extra context may reference retrieved knowledge, but only with real sources.
    for item in body.get("related_knowledge", []):
        assert item.get("source") or item.get("source_name") or item.get("document_id")


def test_disease_detection_refuses_an_unknown_crop(client, farmer, uploaded_leaf):
    response = client.post(
        "/api/v1/ai/disease-detection",
        json={"media_id": uploaded_leaf["id"], "crop_code": "unobtainium"},
        headers=farmer.headers,
    )
    assert response.status_code in {400, 404, 422}, response.text


def test_disease_detection_cannot_read_someone_elses_photo(
    client, farmer, other_farmer, uploaded_leaf
):
    response = client.post(
        "/api/v1/ai/disease-detection",
        json={"media_id": uploaded_leaf["id"], "crop_code": "onion"},
        headers=other_farmer.headers,
    )
    assert response.status_code == 404


def test_ai_history_lists_my_requests_with_model_versions(client, farmer):
    served = client.post(
        "/api/v1/ai/crop-recommendation",
        json={**FULL_FEATURES, "top_k": 2},
        headers=farmer.headers,
    )
    history = client.get("/api/v1/ai/history", headers=farmer.headers)
    assert history.status_code == 200
    items = history.json()["items"]
    if served.status_code == 503:
        pytest.skip("no crop-recommendation artefact installed in this environment")
    assert served.status_code == 200, served.text
    assert items, "an AI request that was served must appear in the caller's history"
    assert all(item.get("kind") for item in items)
    # The farmer (and an operator) must be able to see which model produced a result.
    assert any(item.get("model_name") for item in items)


YIELD_FEATURES = {
    "crop_code": "onion",
    "area_hectares": 1.5,
    "soil_ph": 7.2,
    "nitrogen": 90,
    "phosphorus": 42,
    "potassium": 43,
    "rainfall_mm": 200,
    "temperature_mean_c": 26,
    "irrigation_type": "drip",
}


def test_yield_prediction_asks_for_what_it_needs(client, farmer):
    """An estimate with missing inputs names the missing fields instead of guessing."""
    response = client.post(
        "/api/v1/ai/yield-prediction",
        json={"crop_code": "onion", "area_hectares": 1.5},
        headers=farmer.headers,
    )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert details.get("missing"), "the response must list the missing inputs"


def test_yield_prediction_states_its_basis_or_refuses(client, farmer):
    response = client.post(
        "/api/v1/ai/yield-prediction",
        json=YIELD_FEATURES,
        headers=farmer.headers,
    )
    if response.status_code == 503:
        assert response.json()["error"]["code"] in {"model_unavailable", "insufficient_evidence"}
        return
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_class"] == "model_output"
    assert body["unit"]
    assert body["range_basis"], "an estimate must say what its range is based on"
    assert body["score_type"] and body["confidence_interpretation"]
    assert body["disclaimer"]


def test_price_estimate_reports_absence_instead_of_inventing_prices(client, farmer):
    response = client.post(
        "/api/v1/ai/price-estimate",
        json={"crop_code": "onion", "horizon_days": 3},
        headers=farmer.headers,
    )
    assert response.status_code in {200, 503}, response.text
    if response.status_code == 503:
        assert response.json()["error"]["code"] in {"model_unavailable", "insufficient_evidence"}
        return
    body = response.json()
    if not body.get("available"):
        # No model/history: the response must explain why instead of returning numbers.
        assert body["reason"]
        assert not body["points"]
    else:
        assert body["model_name"] and body["model_version"]
        assert body["confidence_interpretation"]


def test_model_registry_is_publicly_described(client, farmer):
    response = client.get("/api/v1/ai/models", headers=farmer.headers)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["models"], list)
    assert body["artifacts_dir"]
    assert body["registry_note"]
    for model in body["models"]:
        assert "name" in model and "version" in model


def test_ai_health_is_staff_only_and_discloses_providers(client, farmer, admin):
    """AI health exposes infrastructure detail, so it is gated — and honest."""
    assert client.get("/api/v1/ai/health", headers=farmer.headers).status_code in {401, 403}
    response = client.get("/api/v1/ai/health", headers=admin.headers)
    assert response.status_code == 200, response.text
    text = response.text.lower()
    assert "provider" in text
    assert "mock" in text, "development builds must disclose that providers are mock"


def test_feedback_can_only_target_my_own_result(client, farmer, other_farmer):
    served = client.post(
        "/api/v1/ai/crop-recommendation",
        json={**FULL_FEATURES, "top_k": 2},
        headers=farmer.headers,
    )
    if served.status_code == 503:
        pytest.skip("no crop-recommendation artefact installed in this environment")
    assert served.status_code == 200, served.text
    request_id = served.json()["request_id"]
    assert request_id, "the response must carry the request id used for feedback"

    # Legitimate feedback on my own result is accepted and is never auto-applied.
    mine = client.post(
        "/api/v1/ai/feedback",
        json={"ai_request_id": request_id, "verdict": "helpful", "comment": "Matched my field."},
        headers=farmer.headers,
    )
    assert mine.status_code in {200, 201}, mine.text
    body = mine.json()
    assert body["consent_to_train"] is False
    assert "review" in body["review_note"].lower()

    foreign = client.post(
        "/api/v1/ai/feedback",
        json={"ai_request_id": request_id, "verdict": "helpful", "comment": "Not mine."},
        headers=other_farmer.headers,
    )
    assert foreign.status_code == 404, "another account must not learn that this request exists"


def test_served_prediction_writes_an_inference_event(client, db, farmer):
    """Regression: `model_inference_events` stayed empty because the row was never committed.

    Monitoring and drift reporting read this table, so a silent write failure makes
    the whole model-observability story fiction.
    """
    from sqlalchemy import select

    from app.ai.models import ModelInferenceEvent

    response = client.post(
        "/api/v1/ai/crop-recommendation",
        json={**FULL_FEATURES, "top_k": 2},
        headers=farmer.headers,
    )
    if response.status_code == 503:
        pytest.skip("no crop-recommendation artefact installed in this environment")
    assert response.status_code == 200, response.text

    rows = list(
        db.execute(
            select(ModelInferenceEvent).where(
                ModelInferenceEvent.model_name == response.json()["model_name"]
            )
        )
        .scalars()
        .all()
    )
    assert rows, "a served prediction must leave an inference telemetry row"
    event = rows[-1]
    assert event.outcome == "succeeded"
    assert event.model_version
    assert event.latency_ms is not None and event.latency_ms >= 0
    # Drift can be measured later without keeping the raw input next to a person:
    # the fingerprints are salted, and the stored features carry no identifiers.
    assert event.input_fingerprint
    assert "user" not in (event.input_features or {})


def test_inference_telemetry_failure_does_not_break_the_request(client, farmer, monkeypatch):
    """Telemetry is best-effort: losing a metric must not lose a farmer's prediction."""
    from app.ai import service as ai_service

    def _explode(*_args, **_kwargs):
        raise RuntimeError("telemetry backend down")

    monkeypatch.setattr(ai_service, "record_inference_event", _explode)
    response = client.post(
        "/api/v1/ai/crop-recommendation",
        json={**FULL_FEATURES, "top_k": 2},
        headers=farmer.headers,
    )
    if response.status_code == 503:
        pytest.skip("no crop-recommendation artefact installed in this environment")
    assert response.status_code == 200, "a telemetry failure must not fail the request"
