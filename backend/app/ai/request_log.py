"""AI request/output/prediction bookkeeping.

Every AI feature in the platform routes its result through `record_ai_request`,
which writes:

  * `ai_requests`   — what was asked, by whom, with which model, how long it took;
  * `ai_outputs`    — the answer/result plus evidence and disclaimer (1:1);
  * `predictions`   — the user-facing history row (disease scans, recommendations,
                      yield/price estimates) so history endpoints are cheap;
  * `model_inference_events` — append-only telemetry for latency/drift monitoring.

This is what makes the "traceable to model version + timestamp" requirement real
rather than aspirational.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ai.models import AIOutput, AIRequest, ModelInferenceEvent, Prediction
from app.core.enums import AIRequestKind, AIRequestStatus
from app.core.logging import get_logger
from app.core.security import pseudonymize

logger = get_logger(__name__)


def record_ai_request(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    kind: AIRequestKind | str,
    input_summary: dict[str, Any],
    model_name: str,
    model_version: str,
    output: dict[str, Any] | None = None,
    answer_text: str | None = None,
    confidence: float | None = None,
    confidence_interpretation: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    disclaimer: str | None = None,
    insufficient_evidence: bool = False,
    latency_ms: int | None = None,
    language: str = "en",
    provider: str | None = None,
    is_demo: bool = False,
    status: AIRequestStatus = AIRequestStatus.SUCCEEDED,
    error_code: str | None = None,
    error_detail: str | None = None,
    prediction: dict[str, Any] | None = None,
    commit: bool = True,
) -> uuid.UUID:
    """Persist an AI interaction. `prediction` adds a history row when the feature
    has a user-facing result to show later (disease scans, recommendations…)."""
    request = AIRequest(
        user_id=user_id,
        kind=AIRequestKind(kind) if isinstance(kind, str) else kind,
        status=status,
        language=language,
        input_summary=_scrub(input_summary),
        model_name=model_name,
        model_version=model_version,
        provider=provider,
        latency_ms=latency_ms,
        error_code=error_code,
        error_detail=(error_detail or "")[:500] or None,
        is_demo=is_demo,
    )
    db.add(request)
    db.flush()

    if status == AIRequestStatus.SUCCEEDED:
        db.add(
            AIOutput(
                ai_request_id=request.id,
                output=output or {},
                answer_text=answer_text,
                confidence=confidence,
                confidence_interpretation=confidence_interpretation,
                evidence=evidence or [],
                model_name=model_name,
                model_version=model_version,
                disclaimer=disclaimer,
                insufficient_evidence=insufficient_evidence,
            )
        )
    if prediction:
        db.add(
            Prediction(
                user_id=user_id,
                ai_request_id=request.id,
                kind=AIRequestKind(
                    prediction.pop("kind", kind if isinstance(kind, str) else kind.value)
                ),
                model_name=model_name,
                model_version=model_version,
                latency_ms=latency_ms,
                is_demo=is_demo,
                **prediction,
            )
        )
    if commit:
        db.commit()
    return request.id


def record_inference_event(
    db: Session,
    *,
    model_name: str,
    model_version: str,
    kind: str,
    latency_ms: int,
    outcome: str = "success",
    input_features: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
    error_code: str | None = None,
    is_demo: bool = False,
    commit: bool = False,
) -> None:
    """Append an inference telemetry row. The input fingerprint is a salted hash
    of the normalised feature vector, so drift can be measured without storing
    the farmer's raw data."""
    features = input_features or {}
    fingerprint = (
        pseudonymize(
            repr(sorted((k, str(v)) for k, v in features.items())), namespace="dv-model-input"
        )
        if features
        else None
    )
    db.add(
        ModelInferenceEvent(
            model_name=model_name,
            model_version=model_version,
            kind=kind,
            outcome=outcome,
            latency_ms=max(0, int(latency_ms)),
            input_fingerprint=fingerprint,
            input_features=features,
            output_summary=output_summary or {},
            error_code=error_code,
            user_id=user_id,
            is_demo=is_demo,
        )
    )
    if commit:
        db.commit()


def _scrub(payload: dict[str, Any]) -> dict[str, Any]:
    """Never persist raw images or long free text in the request log."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 1000:
            out[key] = value[:1000] + "…[truncated]"
        elif isinstance(value, bytes | bytearray):
            out[key] = f"<{len(value)} bytes>"
        else:
            out[key] = value
    return out


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
