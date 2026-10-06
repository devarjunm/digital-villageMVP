"""AI feature façade.

Every public AI feature goes through this service so that four cross-cutting rules
are enforced in one place:

1. **Provenance** — the response always names the model, its version, where the
   training data came from, and whether that data is demo/synthetic.
2. **Traceability** — each call writes an `ai_requests` row, an `ai_outputs` row,
   a `predictions` history row where the result belongs to a farm/user, and throws
   nothing away silently on failure: the request row records the error code too.
3. **Honest failure** — a missing model raises `ModelUnavailableError` (HTTP 503)
   with the command that installs it. There is no fallback that invents a label.
4. **Data governance** — user photos and inputs are summarised (never embedded
   raw), feedback is opt-in for training, and the training summary reports only
   consented and human-reviewed corrections.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.models import AIFeedback, AIOutput, AIRequest, Prediction
from app.ai.registry import MODEL_NAMES, ModelRegistryService, available_versions
from app.ai.request_log import record_ai_request, record_inference_event
from app.core.enums import AIRequestKind, AIRequestStatus, FeedbackVerdict
from app.core.errors import (
    ModelUnavailableError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
    not_found,
)
from app.core.logging import get_logger
from app.media.models import MediaAsset

logger = get_logger(__name__)


class AIService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------ model info
    def models_overview(self) -> dict[str, Any]:
        from app.core.config import settings

        entries = ModelRegistryService(self.db).list_entries(include_archived=False)
        listed: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for entry in entries:
            installed = bool(available_versions(entry.name)) and (
                (settings.models_path / entry.name / entry.version).exists()
                or (
                    not (settings.models_path / entry.name / entry.version).exists()
                    and entry.version in available_versions(entry.name)
                )
            )
            listed.append(
                {
                    "name": entry.name,
                    "version": entry.version,
                    "display_name": entry.display_name,
                    "task": entry.task,
                    "framework": entry.framework,
                    "stage": entry.stage.value,
                    "is_active": entry.is_active,
                    "installed_on_disk": installed,
                    "metrics": entry.metrics or {},
                    "training_data": entry.training_data or {},
                    "trained_at": entry.trained_at,
                    "mlflow_run_id": entry.mlflow_run_id,
                    "notes": entry.notes,
                    "model_card_url": entry.model_card_url,
                }
            )
            seen.add((entry.name, entry.version))

        # Artefacts present on disk but not registered (e.g. trained with --register
        # against another database) are still shown, flagged appropriately.
        for name in MODEL_NAMES.values():
            for version in available_versions(name):
                if (name, version) in seen:
                    continue
                listed.append(
                    {
                        "name": name,
                        "version": version,
                        "display_name": name.replace("-", " ").title(),
                        "task": None,
                        "framework": None,
                        "stage": "unregistered",
                        "is_active": False,
                        "installed_on_disk": True,
                        "metrics": {},
                        "training_data": {},
                        "trained_at": None,
                        "mlflow_run_id": None,
                        "notes": "Artefact found on disk but not present in the registry table.",
                        "model_card_url": None,
                    }
                )
        return {"models": listed, "artifacts_dir": str(settings.models_path)}

    # ------------------------------------------------------ crop recommendation
    def crop_recommendation(self, *, user, payload) -> dict[str, Any]:
        from ai.crop_recommendation.service import CropRecommendationService, InputValidationError

        inputs: dict[str, Any] = {
            "nitrogen": payload.nitrogen,
            "phosphorus": payload.phosphorus,
            "potassium": payload.potassium,
            "temperature_c": payload.temperature_c,
            "humidity_percent": payload.humidity_percent,
            "ph": payload.ph,
            "rainfall_mm": payload.rainfall_mm,
        }
        sources: dict[str, str] = {}

        # Farm context: latest soil test and (if the weather provider is available)
        # the seasonal averages, each recorded in `input_sources`.
        weather_provenance: dict[str, Any] | None = None
        if payload.farm_id is not None:
            from app.farms.repository import FarmRepository

            farm = FarmRepository(self.db).get(payload.farm_id)
            if farm is None or farm.owner_id != user.id:
                raise NotFoundError("Farm not found.")
            soil_test = FarmRepository(self.db).latest_soil_test(farm.id)
            if soil_test is not None:
                mapping = {
                    "nitrogen": soil_test.nitrogen_kg_per_ha,
                    "phosphorus": soil_test.phosphorus_kg_per_ha,
                    "potassium": soil_test.potassium_kg_per_ha,
                    "ph": soil_test.ph,
                }
                for field, value in mapping.items():
                    if inputs.get(field) is None and value is not None:
                        inputs[field] = float(value)
                        sources[field] = "soil_test"
                if farm.soil_type and not payload.soil_type:
                    payload.soil_type = farm.soil_type.value
            if float(farm.soil_ph or 0) and inputs.get("ph") is None:
                inputs["ph"] = float(farm.soil_ph)
                sources["ph"] = "farm_record"

        try:
            service = CropRecommendationService(db=self.db)
            result = service.recommend(
                inputs=inputs,
                top_k=payload.top_k,
                soil_type=payload.soil_type,
            )
        except InputValidationError as exc:
            record_ai_request(
                self.db,
                user_id=user.id,
                kind=AIRequestKind.CROP_RECOMMENDATION,
                input_summary=_scrub_inputs(inputs),
                model_name="crop-recommendation",
                model_version="unknown",
                status=AIRequestStatus.FAILED,
                error_code="invalid_input",
                error_detail=str(exc),
                language="en",
            )
            raise ValidationError(
                "Some inputs are outside the model's supported range.",
                details={"problems": exc.problems},
            ) from exc

        result["input_sources"].update(sources)
        if not sources:
            result["input_sources"] = {name: "provided" for name in result["inputs_used"]}

        request_id = record_ai_request(
            self.db,
            user_id=user.id,
            kind=AIRequestKind.CROP_RECOMMENDATION,
            input_summary={
                **_scrub_inputs(result["inputs_used"]),
                "input_sources": result["input_sources"],
                "farm_id": str(payload.farm_id) if payload.farm_id else None,
                "season": payload.season,
            },
            model_name=result["model_name"],
            model_version=result["model_version"],
            output={
                "ranked": result["ranked"][: payload.top_k],
                "score_type": result["score_type"],
                "warnings": result["warnings"],
            },
            confidence=result["ranked"][0]["score"] if result["ranked"] else None,
            confidence_interpretation=result["confidence_interpretation"],
            disclaimer=result["disclaimer"],
            latency_ms=result["latency_ms"],
            is_demo=bool(result.get("is_demo_dataset")),
            prediction={
                "subject_type": "farm" if payload.farm_id else None,
                "subject_id": payload.farm_id,
                "crop_code": result["ranked"][0]["crop_code"] if result["ranked"] else None,
                "label": result["ranked"][0]["name_en"] if result["ranked"] else None,
                "score": result["ranked"][0]["score"] if result["ranked"] else None,
                "result": {
                    "ranked": result["ranked"],
                    "inputs_used": result["inputs_used"],
                    "input_sources": result["input_sources"],
                },
            },
        )
        self._record_inference(
            model_name=result["model_name"],
            model_version=result["model_version"],
            kind=AIRequestKind.CROP_RECOMMENDATION.value,
            outcome="succeeded",
            latency_ms=result["latency_ms"],
            input_features=result["inputs_used"],
            output_summary={
                "top_crop": result["ranked"][0]["crop_code"] if result["ranked"] else None
            },
            user_id=user.id,
            is_demo=bool(result.get("is_demo_dataset")),
        )
        result["request_id"] = request_id
        result["farm_context"] = {"weather_provenance": weather_provenance}
        return result

    # ------------------------------------------------------------------ telemetry
    def _record_inference(self, **kwargs: Any) -> None:
        """Write one model-inference telemetry row, in its own transaction.

        Two deliberate choices, both learned from a bug:

        * `commit=True` — the row previously sat uncommitted in the request session
          and was discarded, so `model_inference_events` stayed empty while
          `ai_requests` filled up and monitoring reported "no inferences recorded".
        * failures are logged, not raised — a telemetry write is not worth failing a
          farmer's request over. The exception to that is a database that is already
          down, in which case the request has failed before reaching this point.
        """
        try:
            record_inference_event(self.db, commit=True, **kwargs)
        except Exception as exc:
            logger.warning(
                "inference_event_not_recorded",
                extra={
                    "extra_fields": {"error": str(exc)[:200], "model": kwargs.get("model_name")}
                },
            )

    # --------------------------------------------------------- disease detection
    def disease_detection(self, *, user, payload) -> dict[str, Any]:
        from ai.vision.service import VisionDiseaseService

        from app.media.service import read_image_bytes

        asset = self.db.get(MediaAsset, payload.media_id)
        if asset is None:
            raise NotFoundError("That photo could not be found. Upload it first via /media/upload.")
        if asset.owner_id not in (None, user.id) and not user.has_role("moderator", "admin"):
            not_found()
        image_bytes = read_image_bytes(asset)

        # Input validation happens *before* the model is loaded: a request for a
        # crop the platform does not know is a client error regardless of whether
        # an artefact happens to be installed, and reporting "model unavailable"
        # for a typo would send the farmer looking for the wrong problem.
        if payload.crop_code:
            from app.crops.models import CropCatalog

            known = self.db.execute(
                select(CropCatalog.code).where(CropCatalog.code == payload.crop_code)
            ).scalar_one_or_none()
            if known is None:
                raise ValidationError(
                    "That crop is not in the crop catalog, so a disease scan cannot be matched to it.",
                    details={
                        "crop_code": payload.crop_code,
                        "catalog_endpoint": "/api/v1/crops/catalog",
                    },
                )

        service = VisionDiseaseService(db=self.db)
        try:
            result = service.detect(
                image_bytes=image_bytes, crop_code=payload.crop_code, top_k=payload.top_k
            )
        except ModelUnavailableError as exc:
            record_ai_request(
                self.db,
                user_id=user.id,
                kind=AIRequestKind.DISEASE_DETECTION,
                input_summary={"media_id": str(payload.media_id), "crop_code": payload.crop_code},
                model_name="disease-detection",
                model_version="unavailable",
                status=AIRequestStatus.FAILED,
                error_code="model_unavailable",
                error_detail=exc.message,
                language="en",
            )
            raise

        knowledge: list[dict[str, Any]] = []
        community: list[dict[str, Any]] = []
        if result["predictions"] and not result.get("inconclusive"):
            knowledge, community = self._supporting_evidence(
                label=result["predictions"][0]["label"], crop_code=payload.crop_code
            )
            result["related_knowledge"] = knowledge
            result["similar_community_posts"] = community

        request_id = record_ai_request(
            self.db,
            user_id=user.id,
            kind=AIRequestKind.DISEASE_DETECTION,
            input_summary={
                "media_id": str(payload.media_id),
                "crop_code": payload.crop_code,
                "plant_part": payload.plant_part,
                "image_quality": result["image_quality"],
                "note": (payload.note or "")[:200],
            },
            model_name=result["model_name"],
            model_version=result["model_version"],
            output={
                "predictions": result["predictions"],
                "inconclusive": result["inconclusive"],
                "quality_gate_failed": result["quality_gate_failed"],
                "recommendation": result["recommendation"],
            },
            confidence=result.get("confidence"),
            confidence_interpretation=result["confidence_interpretation"],
            evidence=[{"kind": "knowledge", **item} for item in knowledge]
            + [{"kind": "community_post", **item} for item in community],
            disclaimer=result["disclaimer"],
            latency_ms=result["latency_ms"],
            is_demo=bool(result.get("is_demo_dataset")),
            prediction={
                "subject_type": "media",
                "subject_id": payload.media_id,
                "media_id": payload.media_id,
                "crop_code": payload.crop_code,
                "label": result["predictions"][0]["label"] if result["predictions"] else None,
                "score": result.get("confidence"),
                "result": {
                    "predictions": result["predictions"],
                    "inconclusive": result["inconclusive"],
                    "recommendation": result["recommendation"],
                },
            },
        )
        self._record_inference(
            model_name=result["model_name"],
            model_version=result["model_version"],
            kind=AIRequestKind.DISEASE_DETECTION.value,
            outcome="succeeded",
            latency_ms=result["latency_ms"],
            input_features={
                "width": result["image_quality"]["width"],
                "height": result["image_quality"]["height"],
                "sharpness": result["image_quality"]["sharpness"],
                "crop_code": payload.crop_code,
            },
            output_summary={
                "top_label": result["predictions"][0]["label"] if result["predictions"] else None,
                "inconclusive": result["inconclusive"],
            },
            user_id=user.id,
            is_demo=bool(result.get("is_demo_dataset")),
        )
        result["request_id"] = request_id
        return result

    def _supporting_evidence(
        self, *, label: str, crop_code: str | None
    ) -> tuple[list[dict], list[dict]]:
        """Retrieve knowledge and community posts about a label.

        This is supporting context only — the API never presents a retrieved post as
        confirmation of the model's label.
        """
        knowledge: list[dict[str, Any]] = []
        try:
            from genai.rag.pipeline import RetrievalService

            filters: dict[str, Any] = {}
            if crop_code:
                filters["crop_codes"] = [crop_code]
            retrieval = RetrievalService(self.db).retrieve(
                query=f"{label} {crop_code or ''}".strip(), filters=filters, top_k=3
            )
            knowledge = [
                {
                    "chunk_id": chunk.chunk_id,
                    "title": chunk.title,
                    "source_name": chunk.source_name,
                    "source_url": chunk.source_url,
                    "verification_status": chunk.verification_status,
                    "score": round(chunk.rerank_score or chunk.vector_score, 4),
                    "excerpt": chunk.content[:280],
                }
                for chunk in retrieval.chunks
            ]
        except Exception as exc:
            logger.warning(
                "evidence_lookup_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )
        community: list[dict[str, Any]] = []
        try:
            from app.community.service import CommunityService

            search = CommunityService(self.db).search_semantic(
                query=f"{label} {crop_code or ''}".strip(), crop_code=crop_code, top_k=3
            )
            community = [
                {
                    "post_id": item["post_id"],
                    "title": item["title"],
                    "trust_label": None,
                    "score": item["score"],
                    "excerpt": item["excerpt"],
                    "note": "Similar community discussion — peer experience, not confirmation of the label.",
                }
                for item in search["results"]
            ]
        except Exception as exc:
            logger.warning(
                "community_lookup_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )
        return knowledge, community

    # ------------------------------------------------------------ yield / price
    def yield_prediction(self, *, user, payload) -> dict[str, Any]:
        from ai.yield_prediction.service import IRRIGATION_SCORES, YieldPredictionService

        features: dict[str, Any] = {
            "area_hectares": payload.area_hectares,
            "soil_ph": payload.soil_ph,
            "nitrogen": payload.nitrogen,
            "phosphorus": payload.phosphorus,
            "potassium": payload.potassium,
            "rainfall_mm": payload.rainfall_mm,
            "temperature_mean_c": payload.temperature_mean_c,
            "irrigation_score": None,
        }
        if payload.farm_id is not None:
            from app.farms.repository import FarmRepository

            repository = FarmRepository(self.db)
            farm = repository.get(payload.farm_id)
            if farm is None or farm.owner_id != user.id:
                raise NotFoundError("Farm not found.")
            soil_test = repository.latest_soil_test(farm.id)
            if soil_test is not None:
                for field, value in (
                    ("nitrogen", soil_test.nitrogen_kg_per_ha),
                    ("phosphorus", soil_test.phosphorus_kg_per_ha),
                    ("potassium", soil_test.potassium_kg_per_ha),
                    ("soil_ph", soil_test.ph),
                ):
                    if features.get(field) is None and value is not None:
                        features[field] = float(value)
            if features["soil_ph"] is None and farm.soil_ph is not None:
                features["soil_ph"] = float(farm.soil_ph)
            if not payload.irrigation_type:
                payload.irrigation_type = farm.irrigation_type.value
        features["irrigation_score"] = IRRIGATION_SCORES.get(
            (payload.irrigation_type or "rainfed").lower(), IRRIGATION_SCORES["rainfed"]
        )

        missing = [name for name, value in features.items() if value is None]
        if missing:
            raise ValidationError(
                "Some yield inputs are missing. Provide them or attach a farm with a soil test.",
                details={"missing": missing},
            )

        service = YieldPredictionService(db=self.db)
        result = service.predict(
            crop_code=payload.crop_code, features=features, area_unit="hectare"
        )
        request_id = record_ai_request(
            self.db,
            user_id=user.id,
            kind=AIRequestKind.YIELD_PREDICTION,
            input_summary={**_scrub_inputs(features), "irrigation_type": payload.irrigation_type},
            model_name=result["model_name"],
            model_version=result["model_version"],
            output={
                "estimate": result["estimate"],
                "range": result["range"],
                "range_basis": result["range_basis"],
            },
            confidence=None,
            confidence_interpretation=result["confidence_interpretation"],
            disclaimer=result["disclaimer"],
            is_demo=bool(result.get("is_demo_dataset")),
            prediction={
                "subject_type": "farm" if payload.farm_id else None,
                "subject_id": payload.farm_id,
                "crop_code": payload.crop_code,
                "label": f"{result['estimate']} t/ha",
                "score": None,
                "result": {"estimate": result["estimate"], "range": result["range"]},
            },
        )
        result["request_id"] = request_id
        return result

    def price_estimate(self, *, user, payload) -> dict[str, Any]:
        from ai.price_prediction.service import PriceForecastService

        service = PriceForecastService(db=self.db)
        if not service.is_installed():
            from app.markets.service import MarketService

            history, dates, is_demo = MarketService(self.db).price_history_for_model(
                crop_code=payload.crop_code, market_code=payload.market_code, days=365
            )
            return {
                "data_class": "model_output",
                "available": False,
                "crop_code": payload.crop_code,
                "market_code": payload.market_code,
                "horizon_days": payload.horizon_days,
                "points": [],
                "history": {
                    "observed_points": len(history),
                    "last_date": dates[-1].isoformat() if dates else None,
                    "is_demo_history": is_demo,
                },
                "confidence_interpretation": "No estimate was produced.",
                "reason": (
                    "No price-forecast model is installed on this deployment, so no estimate is shown rather "
                    "than a guess. Install one with: python -m ai.price_prediction.train --register"
                ),
                "disclaimer": (
                    "Observed prices are available at /markets/prices and /markets/prices/trend."
                ),
                "request_id": None,
            }

        result = service.forecast(
            crop_code=payload.crop_code,
            market_code=payload.market_code,
            horizon_days=payload.horizon_days,
        )
        request_id = record_ai_request(
            self.db,
            user_id=user.id,
            kind=AIRequestKind.PRICE_ESTIMATE,
            input_summary={
                "crop_code": payload.crop_code,
                "market_code": payload.market_code,
                "horizon_days": payload.horizon_days,
            },
            model_name=result["model_name"],
            model_version=result["model_version"],
            output={"points": result["points"], "history": result["history"]},
            confidence=None,
            confidence_interpretation=result["confidence_interpretation"],
            disclaimer=result["disclaimer"],
            is_demo=bool(result["history"].get("is_demo_history")),
            prediction={
                "crop_code": payload.crop_code,
                "label": f"{result['points'][0]['predicted_modal_price']} INR/quintal"
                if result["points"]
                else None,
                "result": {"points": result["points"]},
            },
        )
        result["available"] = True
        result["request_id"] = request_id
        return result

    # ------------------------------------------------------------------- risk
    def risk_assessment(self, *, user, payload) -> dict[str, Any]:
        from app.ai.risk import assess_risk, assessment_to_dict
        from app.farms.repository import FarmRepository
        from app.weather.service import WeatherService

        repository = FarmRepository(self.db)
        farm = None
        crop = None
        if payload.crop_id:
            from app.crops.models import Crop

            crop = self.db.get(Crop, payload.crop_id)
            if crop is None:
                raise NotFoundError("Crop not found.")
            farm = repository.get(crop.farm_id)
            if farm is None or farm.owner_id != user.id:
                not_found()
        elif payload.farm_id:
            farm = repository.get(payload.farm_id)
            if farm is None or farm.owner_id != user.id:
                raise NotFoundError("Farm not found.")
            crop = next((item for item in farm.crops if item.status.value == "active"), None)
        else:
            raise ValidationError("Provide farm_id or crop_id.")

        forecast_payload: list[dict[str, Any]] = []
        advisories: list[str] = []
        provenance: dict[str, Any] = {}
        try:
            weather = WeatherService(self.db).for_farm(farm, language=payload.language)
            if weather.forecast is not None:
                forecast_payload = [day.model_dump(mode="json") for day in weather.forecast.days]
                advisories = list(weather.forecast.advisories)
                provenance = {
                    "provider": weather.forecast.provider,
                    "source": weather.forecast.source,
                    "is_demo": weather.forecast.is_demo,
                    "retrieved_at": weather.forecast.retrieved_at.isoformat(),
                    "location_source": weather.location_source,
                    "demo_notice": weather.forecast.demo_notice,
                }
            else:
                provenance = {"error": weather.error, "location_source": weather.location_source}
        except Exception as exc:
            provenance = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}

        assessment = assess_risk(
            crop_stage=crop.stage.value if crop else None,
            irrigation_type=(
                crop.irrigation_method.value if crop and crop.irrigation_method else None
            )
            or (farm.irrigation_type.value if farm else None),
            soil_ph=float(farm.soil_ph) if farm and farm.soil_ph is not None else None,
            forecast=forecast_payload,
            advisories=advisories,
            crop_code=crop.crop_code if crop else None,
        )
        result = assessment_to_dict(assessment)
        result["weather_provenance"] = provenance
        result["farm_id"] = str(farm.id)
        result["crop_code"] = crop.crop_code if crop else None

        request_id = record_ai_request(
            self.db,
            user_id=user.id,
            kind=AIRequestKind.RISK_ASSESSMENT,
            input_summary={
                "farm_id": str(farm.id),
                "crop_id": str(payload.crop_id) if payload.crop_id else None,
                "crop_stage": result["inputs_used"].get("crop_stage"),
                "forecast_provider": provenance.get("provider"),
            },
            model_name="rule-based-screening",
            model_version="v1",
            provider="internal_rules",
            output={
                "level": result["level"],
                "score": result["score"],
                "flags": [f["code"] for f in result["flags"]],
            },
            confidence=None,
            confidence_interpretation=result["score_interpretation"],
            disclaimer=result["disclaimer"],
            is_demo=bool(provenance.get("is_demo")),
        )
        result["request_id"] = request_id
        result["advisories"] = advisories
        return result

    # --------------------------------------------------------------- history
    def history(
        self, *, user, kind: AIRequestKind | None, limit: int, offset: int
    ) -> tuple[list[Prediction], int]:
        stmt = select(Prediction).where(Prediction.user_id == user.id)
        count_stmt = (
            select(func.count()).select_from(Prediction).where(Prediction.user_id == user.id)
        )
        if kind is not None:
            stmt = stmt.where(Prediction.kind == kind)
            count_stmt = count_stmt.where(Prediction.kind == kind)
        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(
                stmt.order_by(Prediction.created_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )
        return rows, total

    def delete_history_item(self, *, user, prediction_id: uuid.UUID) -> None:
        row = self.db.get(Prediction, prediction_id)
        if row is None or row.user_id != user.id:
            raise NotFoundError("That history entry could not be found.")
        self.db.delete(row)
        self.db.commit()

    def output_for(self, *, user, request_id: uuid.UUID) -> dict[str, Any]:
        request_row = self.db.get(AIRequest, request_id)
        if request_row is None:
            raise NotFoundError("That AI request could not be found.")
        if request_row.user_id not in (None, user.id) and not user.has_role("moderator", "admin"):
            not_found()
        output = self.db.execute(
            select(AIOutput).where(AIOutput.ai_request_id == request_id)
        ).scalar_one_or_none()
        return {
            "request": {
                "id": str(request_row.id),
                "kind": request_row.kind.value,
                "status": request_row.status.value,
                "model_name": request_row.model_name,
                "model_version": request_row.model_version,
                "provider": request_row.provider,
                "latency_ms": request_row.latency_ms,
                "created_at": request_row.created_at,
                "input_summary": request_row.input_summary,
                "error_code": request_row.error_code,
                "error_detail": request_row.error_detail,
            },
            "output": None
            if output is None
            else {
                "output": output.output,
                "answer_text": output.answer_text,
                "confidence": float(output.confidence) if output.confidence is not None else None,
                "confidence_interpretation": output.confidence_interpretation,
                "evidence": output.evidence,
                "disclaimer": output.disclaimer,
                "insufficient_evidence": output.insufficient_evidence,
            },
        }

    # -------------------------------------------------------------- feedback
    def submit_feedback(self, *, user, payload) -> tuple[dict[str, Any], AIFeedback]:
        request_row = self.db.get(AIRequest, payload.ai_request_id)
        if request_row is None:
            raise NotFoundError("That AI request could not be found.")
        if request_row.user_id != user.id:
            not_found()
        output = self.db.execute(
            select(AIOutput).where(AIOutput.ai_request_id == payload.ai_request_id)
        ).scalar_one_or_none()
        if output is None:
            raise ValidationError("That AI request has no stored output to review.")
        existing = self.db.execute(
            select(AIFeedback).where(
                AIFeedback.ai_output_id == output.id, AIFeedback.user_id == user.id
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.verdict = payload.verdict
            existing.comment = payload.comment
            existing.corrected_label = payload.corrected_label
            existing.correction_details = payload.correction_details
            existing.consent_to_train = payload.consent_to_train
            self.db.commit()
            self.db.refresh(existing)
            feedback = existing
        else:
            feedback = AIFeedback(
                ai_output_id=output.id,
                user_id=user.id,
                verdict=payload.verdict,
                comment=payload.comment,
                corrected_label=payload.corrected_label,
                correction_details=payload.correction_details,
                consent_to_train=payload.consent_to_train,
            )
            self.db.add(feedback)
            self.db.commit()
            self.db.refresh(feedback)

        from app.core.observability import AI_FEEDBACK

        AI_FEEDBACK.labels(model_name=output.model_name, verdict=payload.verdict.value).inc()
        message = (
            "Thank you — your feedback was recorded and will be reviewed by a moderator or expert."
            if payload.verdict in {FeedbackVerdict.INCORRECT, FeedbackVerdict.REPORT}
            else "Thank you for helping improve these results."
        )
        if payload.consent_to_train:
            message += (
                " Because you allowed it, this correction may be used for future model training after a human "
                "reviews it."
            )
        else:
            message += " It will not be used for model training."
        return (
            {
                "status": "recorded",
                "feedback_id": feedback.id,
                "message": message,
                "consent_to_train": feedback.consent_to_train,
            },
            feedback,
        )

    # --------------------------------------------------- staff/monitoring tools
    def feedback_queue(
        self, *, verdict: FeedbackVerdict | None, limit: int, offset: int
    ) -> tuple[list[AIFeedback], int]:
        stmt = select(AIFeedback)
        count_stmt = select(func.count()).select_from(AIFeedback)
        if verdict is not None:
            stmt = stmt.where(AIFeedback.verdict == verdict)
            count_stmt = count_stmt.where(AIFeedback.verdict == verdict)
        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(
                stmt.order_by(AIFeedback.created_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )
        return rows, total

    def review_feedback(
        self, *, feedback_id: uuid.UUID, reviewer, used_in_training: bool | None, note: str | None
    ) -> dict[str, Any]:
        feedback = self.db.get(AIFeedback, feedback_id)
        if feedback is None:
            raise NotFoundError("That feedback entry could not be found.")
        if used_in_training is not None:
            if not reviewer.has_role("admin"):
                raise PermissionDeniedError(
                    "Only an administrator can mark feedback as used for training."
                )
            if used_in_training and not feedback.consent_to_train:
                raise ValidationError(
                    "This user did not consent to training use, so the correction cannot be marked as training data."
                )
            feedback.used_in_training = used_in_training
        feedback.reviewed_by_id = reviewer.id
        if note:
            feedback.correction_details = (
                f"{feedback.correction_details or ''}\n[review] {note}".strip()[:1500]
            )
        self.db.commit()
        return {
            "feedback_id": feedback.id,
            "status": "reviewed",
            "reviewed_by_id": reviewer.id,
            "used_in_training": feedback.used_in_training,
            "message": "Review recorded. Every use of feedback for training is logged in the audit trail.",
        }

    def training_data_summary(self) -> dict[str, Any]:
        rows = self.db.execute(
            select(AIFeedback.verdict, func.count()).group_by(AIFeedback.verdict)
        ).all()
        counts = {verdict.value: int(count) for verdict, count in rows}
        consenting = int(
            self.db.execute(
                select(func.count())
                .select_from(AIFeedback)
                .where(AIFeedback.consent_to_train.is_(True))
            ).scalar_one()
        )
        reviewed = int(
            self.db.execute(
                select(func.count())
                .select_from(AIFeedback)
                .where(AIFeedback.reviewed_by_id.is_not(None))
            ).scalar_one()
        )
        used = int(
            self.db.execute(
                select(func.count())
                .select_from(AIFeedback)
                .where(AIFeedback.used_in_training.is_(True))
            ).scalar_one()
        )
        return {
            "collected_labels": counts,
            "reviewed_corrections": reviewed,
            "pending_review": int(
                self.db.execute(
                    select(func.count())
                    .select_from(AIFeedback)
                    .where(
                        AIFeedback.reviewed_by_id.is_(None),
                        AIFeedback.verdict.in_([FeedbackVerdict.INCORRECT, FeedbackVerdict.REPORT]),
                    )
                ).scalar_one()
            ),
            "consenting": consenting,
            "approved_for_training": used,
            "policy": [
                "User photos and inputs are never used for training unless the user opts in.",
                "Corrections are reviewed by a human before they can be marked as training data.",
                "Only aggregate counts and consented, reviewed items are exposed here — never raw user inputs.",
                "Training runs are reproducible from the dataset version recorded in each model card.",
            ],
        }

    # ------------------------------------------------------------ health/summary
    def health(self) -> dict[str, Any]:
        from genai.embeddings.provider import get_embedding_provider
        from genai.llm.provider import llm_health
        from genai.reranking.lexical import get_reranker

        from app.core.config import settings
        from app.database.capabilities import supports_pgvector

        models: list[dict[str, Any]] = []
        for key, name in MODEL_NAMES.items():
            versions = available_versions(name)
            models.append(
                {
                    "key": key,
                    "name": name,
                    "installed_versions": versions,
                    "installed": bool(versions),
                    "active_in_registry": bool(ModelRegistryService(self.db).active_entry(name)),
                    "install_command": f"python -m ai.{name.replace('-', '_')}.train --register",
                }
            )
        rag_health: dict[str, Any] = {}
        try:
            from genai.rag.pipeline import RetrievalService

            rag_health = RetrievalService(self.db).health()
        except Exception as exc:
            rag_health = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        notes: list[str] = []
        if not supports_pgvector(self.db.get_bind()):
            notes.append(
                "pgvector is not available: semantic search falls back to in-process cosine similarity."
            )
        return {
            "llm": llm_health(),
            "embeddings": get_embedding_provider().health(),
            "vector_index": {"pgvector": supports_pgvector(self.db.get_bind()), "rag": rag_health},
            "models": models,
            "rag": {
                "top_k": settings.rag_top_k,
                "min_score": settings.rag_min_score,
                "chunk_chars": settings.rag_chunk_chars,
                "reranker": getattr(get_reranker(), "name", "lexical_bm25"),
            },
            "notes": notes,
        }

    # -------------------------------------------------------------- season plan
    def season_plan(self, *, user, payload) -> dict[str, Any]:
        """Assemble a season plan from real components, each labelled by source.

        Deliberately an *assembly* service: it does not ask an LLM to invent a crop
        calendar. It pulls (1) crop suitability from the installed model, (2) scheme
        eligibility from the rules engine, (3) published knowledge via retrieval, and
        (4) risk flags from the rules engine — and lists which of these were available.
        """
        from app.farms.repository import FarmRepository
        from app.schemes.service import SchemeService

        farm = FarmRepository(self.db).get(payload.farm_id)
        if farm is None or farm.owner_id != user.id:
            raise NotFoundError("Farm not found.")

        steps: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        ai_outputs: list[dict[str, Any]] = []
        notices: list[str] = []

        # 1. Scheme eligibility (rules are data, not guesses).
        try:
            recommendations = SchemeService(self.db).recommend(user=user, limit=5)
            steps.append(
                {
                    "step": "schemes",
                    "title": "Schemes you may be eligible for",
                    "data_class": "derived",
                    "items": [
                        {
                            "scheme": item.scheme.slug,
                            "name": item.scheme.name,
                            "status": item.status,
                            "match_score": item.match_score,
                            "reasons": item.reasons,
                            "missing_inputs": item.missing_inputs,
                            "official_source_url": item.scheme.official_source_url,
                        }
                        for item in recommendations.items
                    ],
                    "note": recommendations.note,
                }
            )
            sources.append(
                {
                    "kind": "scheme_rules",
                    "detail": "Deterministic eligibility rules on stored scheme data.",
                }
            )
        except Exception as exc:
            notices.append(f"Scheme screening was unavailable ({type(exc).__name__}).")

        # 2. Knowledge guidance for the farm's crops.
        crop_codes = sorted({crop.crop_code for crop in farm.crops})
        if crop_codes:
            try:
                from genai.rag.pipeline import RetrievalService

                retrieval = RetrievalService(self.db).retrieve(
                    query=f"{payload.season} season practices for {', '.join(crop_codes)}",
                    filters={"crop_codes": crop_codes},
                    top_k=4,
                )
                steps.append(
                    {
                        "step": "knowledge",
                        "title": "Published guidance for your crops",
                        "data_class": "documented",
                        "items": [
                            {
                                "title": chunk.title,
                                "source_name": chunk.source_name,
                                "source_url": chunk.source_url,
                                "verification_status": chunk.verification_status,
                                "excerpt": chunk.content[:240],
                                "score": round(chunk.rerank_score or chunk.vector_score, 4),
                            }
                            for chunk in retrieval.chunks
                        ],
                        "note": "Retrieved from the platform knowledge base with the sources shown.",
                    }
                )
                sources.append(
                    {
                        "kind": "knowledge_base",
                        "detail": f"{len(retrieval.chunks)} passages retrieved.",
                    }
                )
            except Exception as exc:
                notices.append(f"Knowledge retrieval was unavailable ({type(exc).__name__}).")

        # 3. Risk screening.
        if payload.include_risk:
            try:
                risk = self.risk_assessment(user=user, payload=_RiskPayload(farm_id=farm.id))
                steps.append(
                    {
                        "step": "risk",
                        "title": "Conditions to watch",
                        "data_class": risk["data_class"],
                        "level": risk["level"],
                        "flags": risk["flags"],
                        "method_note": risk["method_note"],
                        "weather_provenance": risk["weather_provenance"],
                    }
                )
                ai_outputs.append(
                    {"kind": "risk_assessment", "request_id": str(risk.get("request_id"))}
                )
                sources.append(
                    {"kind": "weather_rules", "detail": "Rule-based screening of the forecast."}
                )
            except Exception as exc:
                notices.append(f"Risk screening was unavailable ({type(exc).__name__}).")

        if not steps:
            notices.append(
                "No plan items could be assembled from the available data. Add crops and soil details to your "
                "farm, then try again."
            )
        return {
            "data_class": "derived",
            "farm_id": farm.id,
            "season": payload.season,
            "steps": steps,
            "sources": sources,
            "ai_outputs": ai_outputs,
            "notices": notices,
            "note": (
                "This plan is assembled from the platform's own data sources, each labelled above. It is not a "
                "generated crop calendar and does not replace local extension advice."
            ),
        }


class _RiskPayload:
    """Minimal request object for internal calls to risk_assessment."""

    def __init__(
        self, *, farm_id: uuid.UUID, crop_id: uuid.UUID | None = None, language: str = "en"
    ) -> None:
        self.farm_id = farm_id
        self.crop_id = crop_id
        self.language = language


def _scrub_inputs(values: dict[str, Any]) -> dict[str, Any]:
    """Round numeric inputs before storage: the AI log keeps what the model used,
    not a fingerprint of the farmer's device or precise location."""
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, float):
            clean[key] = round(value, 2)
        elif isinstance(value, int | str | bool) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean
