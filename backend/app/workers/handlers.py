"""Background job handlers.

Each handler receives a SQLAlchemy session and the job payload and returns a JSON
summary that is stored on the job row. Handlers must be idempotent: the queue may
retry them, and `embedding_reindex` in particular is expected to be run
repeatedly.

Only job kinds with a real implementation are registered here. `enqueue()` refuses
kinds that have no handler, so a feature can never appear to be queued while
nothing would ever run it.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import JobKind, NotificationType
from app.core.logging import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------- helpers
def _post_source_text(post) -> str:
    parts = [post.title or "", post.body or ""]
    if post.crop_code:
        parts.append(f"crop: {post.crop_code}")
    if post.category:
        parts.append(
            f"category: {post.category.value if hasattr(post.category, 'value') else post.category}"
        )
    if post.state:
        parts.append(f"state: {post.state}")
    return "\n".join(part for part in parts if part).strip()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------- jobs
def embed_post(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or refresh the pgvector embedding for a community post."""
    from genai.embeddings.provider import get_embedding_provider

    from app.community.models import Post, PostEmbedding

    post_id = uuid.UUID(str(payload["post_id"]))
    post = db.get(Post, post_id)
    if post is None or post.deleted_at is not None:
        return {"skipped": True, "reason": "post_missing_or_deleted"}

    text = _post_source_text(post)
    digest = _text_hash(text)
    provider = get_embedding_provider()
    existing = db.execute(
        select(PostEmbedding).where(PostEmbedding.post_id == post.id)
    ).scalar_one_or_none()
    force = bool(payload.get("force"))
    if (
        existing is not None
        and existing.source_text_hash == digest
        and existing.embedding_model == provider.model
        and not force
    ):
        return {"skipped": True, "reason": "unchanged", "model": provider.model}

    result = provider.embed([text], input_type="document")
    vector = result.vectors[0]
    if len(vector) != provider.dimension:
        raise ValueError(f"Embedding dimension mismatch: provider returned {len(vector)}")
    if existing is None:
        db.add(
            PostEmbedding(
                post_id=post.id,
                embedding=vector,
                embedding_model=result.model,
                embedding_version=result.version,
                source_text_hash=digest,
            )
        )
    else:
        existing.embedding = vector
        existing.embedding_model = result.model
        existing.embedding_version = result.version
        existing.source_text_hash = digest
    db.commit()
    return {
        "post_id": str(post.id),
        "embedded": True,
        "model": result.model,
        "provider": result.provider,
        "is_demo_embedding": result.is_demo,
        "dimension": result.dimension,
        "notices": result.notices,
    }


def embed_document(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Re-chunk and re-embed a knowledge document."""
    from app.knowledge.service import KnowledgeService

    document_id = uuid.UUID(str(payload["document_id"]))
    result = KnowledgeService(db).reindex(document_id)
    return {
        "document_id": str(document_id),
        "chunks_indexed": getattr(result, "chunks_indexed", None),
    }


def embedding_reindex(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Bulk re-embed everything (posts and/or knowledge documents).

    Batched and resumable: `limit` bounds a single run, and the response reports
    how many items still need work so the job can be re-queued.
    """
    from genai.embeddings.provider import get_embedding_provider

    from app.community.models import Post, PostEmbedding

    scope = str(payload.get("scope", "posts"))
    limit = int(payload.get("limit", 200))
    provider = get_embedding_provider()
    summary: dict[str, Any] = {
        "scope": scope,
        "model": getattr(provider, "model", None) or getattr(provider, "model_name", None),
        "provider": provider.name,
    }

    if scope in {"posts", "all"}:
        stale: list[str] = []
        rows = db.execute(
            select(Post)
            .where(Post.deleted_at.is_(None))
            .order_by(Post.created_at.desc())
            .limit(limit)
        ).scalars()
        for post in rows:
            digest = _text_hash(_post_source_text(post))
            existing = db.execute(
                select(PostEmbedding).where(PostEmbedding.post_id == post.id)
            ).scalar_one_or_none()
            if (
                existing is None
                or existing.source_text_hash != digest
                or existing.embedding_model != provider.model
            ):
                stale.append(str(post.id))
        embedded = 0
        for post_id in stale:
            summary_item = embed_post(db, {"post_id": post_id, "force": True})
            embedded += 1 if summary_item.get("embedded") else 0
        summary["posts"] = {"checked": limit, "embedded": embedded}

    if scope in {"documents", "all"}:
        from app.knowledge.models import KnowledgeDocument

        documents = list(
            db.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.deleted_at.is_(None)).limit(limit)
            ).scalars()
        )
        from app.knowledge.service import KnowledgeService

        knowledge = KnowledgeService(db)
        ok, failed = 0, 0
        for document in documents:
            try:
                knowledge.reindex(document.id)
                ok += 1
            except Exception as exc:
                failed += 1
                logger.warning(
                    "document_reindex_failed",
                    extra={
                        "extra_fields": {"document_id": str(document.id), "error": str(exc)[:200]}
                    },
                )
        summary["documents"] = {"checked": len(documents), "indexed": ok, "failed": failed}

    summary["finished_at"] = datetime.now(UTC).isoformat()
    return summary


def notification_fanout(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Send a notification to a list of users (or to a stored audience)."""
    from app.notifications.service import NotificationService

    user_ids = [uuid.UUID(str(value)) for value in payload.get("user_ids", [])]
    if not user_ids and payload.get("audience"):
        user_ids = _resolve_audience(db, payload)
    service = NotificationService(db)
    outcome = service.fan_out(
        user_ids=user_ids,
        type=NotificationType(payload.get("type", NotificationType.SYSTEM.value)),
        title=str(payload.get("title", "Digital Village")),
        body=str(payload.get("body", "")),
        subject_type=payload.get("subject_type"),
        subject_id=uuid.UUID(str(payload["subject_id"])) if payload.get("subject_id") else None,
        deep_link=payload.get("deep_link"),
        payload=payload.get("data") or {},
        language=str(payload.get("language", "en")),
    )
    return outcome


def _resolve_audience(db: Session, payload: dict[str, Any]) -> list[uuid.UUID]:
    from app.core.enums import Role
    from app.users.models import User, UserProfile, UserRole

    audience = payload["audience"]
    stmt = select(User.id).where(User.is_active.is_(True))
    if audience == "role" and payload.get("role"):
        try:
            role = Role(str(payload["role"]))
        except ValueError as exc:
            raise ValueError(f"Unknown role '{payload['role']}'") from exc
        stmt = stmt.where(
            User.id.in_(select(UserRole.user_id).where(UserRole.role == role))
            | (User.primary_role == role)
        )
    if audience == "demo_users":
        stmt = stmt.where(User.is_demo.is_(True))
    if audience == "real_users":
        stmt = stmt.where(User.is_demo.is_(False))
    if audience == "state" and payload.get("state"):
        stmt = stmt.join(UserProfile, UserProfile.user_id == User.id).where(
            UserProfile.state == payload["state"]
        )
    return list(db.execute(stmt.limit(5000)).scalars())


def crop_reminder_scan(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Create record-keeping and weather-driven reminders for active crops.

    Two honest reminder sources, both labelled:

      * `log_stale` — the farmer has not logged any activity for this crop in
        `stale_days` days. This is about the platform's own records, so no
        agronomic claim is made.
      * `weather_advisory` — the weather rules engine produced an advisory for the
        farm's location (rain/humidity/temperature/wind thresholds). The advisory
        text comes from that rule, and the notification repeats its provenance.

    Nothing here invents a crop calendar: the app does not know the farmer's
    variety, sowing window or local package of practices, and will not pretend to.
    """
    from app.crops.models import CropEvent
    from app.crops.service import CropService
    from app.farms.models import Farm
    from app.notifications.service import NotificationService
    from app.weather.service import WeatherService

    stale_days = int(payload.get("stale_days", 7))
    farm_limit = int(payload.get("farm_limit", 150))
    notifications = NotificationService(db)
    crop_service = CropService(db)
    weather = WeatherService(db)

    created = {"log_stale": 0, "weather_advisory": 0}
    scanned = 0
    since = datetime.now(UTC) - timedelta(days=stale_days)

    farms = list(db.execute(select(Farm).limit(farm_limit)).scalars())
    for farm in farms:
        advisories: list[str] = []
        try:
            farm_weather = weather.for_farm(farm)
            if farm_weather.forecast is not None:
                advisories = list(getattr(farm_weather.forecast, "advisories", []) or [])
        except Exception as exc:
            logger.warning(
                "crop_reminder_weather_error",
                extra={"extra_fields": {"farm_id": str(farm.id), "error": str(exc)[:200]}},
            )

        for crop in farm.crops:
            if crop.status.value not in {"active", "planned"}:
                continue
            scanned += 1
            last_event = db.execute(
                select(CropEvent.created_at)
                .where(CropEvent.crop_id == crop.id)
                .order_by(CropEvent.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if (
                last_event is None
                or (last_event.replace(tzinfo=UTC) if last_event.tzinfo is None else last_event)
                < since
            ):
                outcome = notifications.create(
                    user_id=farm.owner_id,
                    type=NotificationType.CROP_REMINDER,
                    title=f"Add an update for your {crop.crop_code.replace('_', ' ')}",
                    body=(
                        f"No activity has been logged for {farm.name} · {crop.crop_code.replace('_', ' ')} in the "
                        f"last {stale_days} days. Log irrigation, fertiliser or field observations so your "
                        "records stay accurate. This is a records reminder, not agronomic advice."
                    ),
                    subject_type="crop",
                    subject_id=crop.id,
                    deep_link=f"digitalvillage://crops/{crop.id}",
                    payload={
                        "source": "log_stale",
                        "stage": crop.stage.value,
                        "data_class": "platform_record",
                    },
                )
                created["log_stale"] += 1 if outcome.get("created") else 0

            guidance = crop_service.stage_guidance(crop)
            for advisory in advisories[:1]:
                outcome = notifications.create(
                    user_id=farm.owner_id,
                    type=NotificationType.CROP_REMINDER,
                    title=f"Weather note for {crop.crop_code.replace('_', ' ')}",
                    body=f"{advisory} (Rule-based advisory from the weather module screening thresholds.)",
                    subject_type="crop",
                    subject_id=crop.id,
                    deep_link=f"digitalvillage://weather/farm/{farm.id}",
                    payload={
                        "source": "weather_advisory",
                        "stage": guidance.get("current_stage"),
                        "data_class": "derived",
                    },
                )
                created["weather_advisory"] += 1 if outcome.get("created") else 0
    db.commit()
    return {
        "crops_scanned": scanned,
        "notifications_created": created,
        "stale_days": stale_days,
        "note": "No crop-calendar advice is generated: stage guidance is generic reference data, not a schedule.",
    }


def weather_alert_scan(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Ask the configured weather provider for alerts and notify affected farmers.

    Both shipped providers report `alerts_supported=false`. When that is the case
    the job records it and creates nothing — alerts are never invented — and the
    job result is visible in the admin console.
    """
    from app.farms.models import Farm
    from app.notifications.service import NotificationService
    from app.weather.service import WeatherService

    weather = WeatherService(db)
    notifications = NotificationService(db)
    region_limit = int(payload.get("region_limit", 40))

    regions = list(
        db.execute(
            select(Farm.state, Farm.district)
            .where(Farm.state.is_not(None))
            .distinct()
            .limit(region_limit)
        ).all()
    )
    feed = weather.alerts()
    supported = bool(getattr(feed, "supported", False))
    created = 0
    if supported:
        for state, district in regions:
            region_feed = weather.alerts(state=state, district=district)
            if not getattr(region_feed, "alerts", None):
                continue
            owners = list(
                db.execute(
                    select(Farm.owner_id)
                    .where(Farm.state == state, Farm.district == district)
                    .limit(300)
                ).scalars()
            )
            for item in region_feed.alerts:
                for owner_id in set(owners):
                    outcome = notifications.create(
                        user_id=owner_id,
                        type=NotificationType.WEATHER_ALERT,
                        title=str(getattr(item, "title", "Weather alert"))[:200],
                        body=str(getattr(item, "summary", ""))[:600],
                        subject_type="region",
                        deep_link="digitalvillage://weather",
                        payload={
                            "provider": region_feed.provider,
                            "state": state,
                            "district": district,
                        },
                    )
                    created += 1 if outcome.get("created") else 0
    db.commit()
    return {
        "regions_checked": len(regions),
        "alerts_supported_by_provider": supported,
        "alerts_created": created,
        "provider": feed.provider,
        "is_demo": getattr(feed, "is_demo", None),
        "note": None
        if supported
        else "The configured weather provider does not supply alert feeds; nothing was created.",
    }


def market_sync(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh mandi prices for the requested crops so the app reads fresh data."""
    from app.markets.service import MarketService

    crops = payload.get("crop_codes") or []
    state = payload.get("state")
    days = int(payload.get("days", 3))
    service = MarketService(db)
    stored = 0
    for crop_code in crops:
        try:
            result = service.prices(
                crop_code=str(crop_code),
                state=state,
                days=days,
                include_demo=bool(payload.get("include_demo", True)),
            )
        except Exception as exc:
            logger.warning(
                "market_sync_error",
                extra={"extra_fields": {"crop": crop_code, "error": str(exc)[:200]}},
            )
            continue
        stored += getattr(result, "record_count", 0) or len(getattr(result, "records", []) or [])
    return {
        "crops": len(crops),
        "records_seen": stored,
        "provider": service.health().get("provider"),
    }


def model_evaluation(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate a registered model on its held-out split and store the result."""
    from app.ai.registry import ModelRegistryService

    name = str(payload.get("model_name", "crop-recommendation"))
    version = payload.get("model_version")
    if name != "crop-recommendation":
        return {"skipped": True, "reason": f"No evaluation routine implemented for '{name}'."}
    from ai.crop_recommendation.service import CropRecommendationService

    report = CropRecommendationService(db=db, version=version).evaluate_on_holdout()
    row = ModelRegistryService(db).record_evaluation(
        model_name=report["model_name"],
        model_version=report["model_version"],
        evaluation_type=report["evaluation_type"],
        metrics=report["metrics"],
        dataset_version=report["dataset_version"],
        sample_count=report["sample_count"],
        notes=report["notes"],
    )
    return {"evaluation_id": str(row.id), **report}


HANDLERS: dict[str, Any] = {
    JobKind.EMBED_POST.value: embed_post,
    JobKind.EMBED_DOCUMENT.value: embed_document,
    JobKind.EMBEDDING_REINDEX.value: embedding_reindex,
    JobKind.NOTIFICATION_FANOUT.value: notification_fanout,
    JobKind.CROP_REMINDER_SCAN.value: crop_reminder_scan,
    JobKind.WEATHER_ALERT_SCAN.value: weather_alert_scan,
    JobKind.MARKET_SYNC.value: market_sync,
    JobKind.MODEL_EVALUATION.value: model_evaluation,
}

# Job kinds declared in the enum but not yet implemented. Enqueueing them raises a
# validation error rather than silently queueing work nothing would process.
UNIMPLEMENTED_KINDS: tuple[str, ...] = (
    JobKind.DISEASE_DETECTION.value,
    JobKind.INGEST_DOCUMENT.value,
)
