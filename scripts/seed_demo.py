#!/usr/bin/env python
"""Seed a development database with clearly-labelled demo data.

What this script creates (every row has `is_demo=True` unless noted):

  * four demo accounts — farmer, farmer, expert, moderator, admin — all using the
    password from `DEMO_USER_PASSWORD`. The script prints that fact and refuses to
    run when `APP_ENV=production` unless `ALLOW_PROD_SEED=1` is set explicitly;
  * farms with crops and one soil test, so farm/crop/weather/risk paths have data;
  * community posts with replies, reactions and one official-source post, so trust
    labels, ranking and moderation can be exercised;
  * knowledge documents that describe the *platform* (how notices work, what the
    labels mean) plus short placeholder documents marked as demo — the script never
    invents agronomic or government facts;
  * market prices pulled from the active (demo) market provider, stored with
    `is_demo=True`;
  * the trained crop-recommendation artefact registered in `model_registry_entries`
    if an artefact exists on disk.

Nothing here is safe to run against production data. Demo rows are flagged so the
API can exclude them and so the admin console can count them separately.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import app.models  # noqa: E402,F401  (registers every mapped class before use)
from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import session_scope  # noqa: E402

logger = get_logger("seed")


DEMO_NOTE = "DEMO DATA — created by scripts/seed_demo.py for development only."


def guard() -> None:
    if (
        settings.app_env == "production"
        and not settings.allow_prod_seed
        and os.environ.get("ALLOW_PROD_SEED") != "1"
    ):
        print(
            "Refusing to seed: APP_ENV=production and ALLOW_PROD_SEED is not set.\n"
            "Demo data must never be mixed into a production database.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def upsert_user(
    db,
    *,
    phone: str,
    full_name: str,
    role: str,
    profile: dict,
    extra_roles: list[str] | None = None,
):  # noqa: ANN001
    from app.core.enums import Language, Role, UserStatus
    from app.farmers.models import FarmerProfile
    from app.users.models import User, UserRole

    existing = db.query(User).filter(User.phone_e164 == phone).one_or_none()
    if existing is None:
        user = User(
            phone_e164=phone,
            full_name=full_name,
            primary_role=Role(role),
            preferred_language=Language.MR if role == "farmer" else Language.EN,
            status=UserStatus.ACTIVE,
            password_hash=hash_password(settings.demo_user_password),
            phone_verified_at=datetime.now(UTC),
            is_demo=True,
        )
        db.add(user)
        db.flush()
    else:
        user = existing

    for extra in extra_roles or []:
        role_value = Role(extra)
        exists = (
            db.query(UserRole)
            .filter(UserRole.user_id == user.id, UserRole.role == role_value)
            .one_or_none()
        )
        if exists is None:
            db.add(UserRole(user_id=user.id, role=role_value))

    profile_row = (
        db.query(FarmerProfile).filter(FarmerProfile.user_id == user.id).one_or_none()
    )
    if profile_row is None:
        profile_row = FarmerProfile(user_id=user.id, **profile)
        db.add(profile_row)
    db.flush()
    return user


def seed(db) -> dict[str, int]:  # noqa: ANN001
    from app.community.models import Comment, Post, Reaction, SavedPost
    from app.community.trust import assess
    from app.core.enums import (
        ContentStatus,
        CropStage,
        CropStatus,
        IrrigationType,
        OwnershipType,
        PostCategory,
        ReactionKind,
        Role,
        Season,
        SoilType,
        VerificationStatus,
    )
    from app.core.enums import ConsentKind, ConsentSource
    from app.crops.models import Crop, CropEvent
    from app.farms.models import Farm, SoilTest
    from app.schemes.models import Scheme, SchemeEligibilityRule
    from app.users.consent import ConsentService
    from app.knowledge.models import KnowledgeDocument
    from genai.rag.pipeline import build_document_from_text

    counts: dict[str, Any] = {}

    # ------------------------------------------------------------------ users
    farmer = upsert_user(
        db,
        phone="+919000000001",
        full_name="Demo Farmer (Nashik)",
        role=Role.FARMER.value,
        profile={
            "display_name": "Demo Farmer (Nashik)",
            "village": "Sample Village",
            "taluka": "Sample Taluka",
            "district": "Nashik",
            "state": "Maharashtra",
            "pincode": "422001",
            "latitude": 19.9975,
            "longitude": 73.7898,
            "farming_experience_years": 12,
            "primary_crops": ["onion", "tomato", "soybean"],
            "bio": DEMO_NOTE,
        },
    )
    farmer2 = upsert_user(
        db,
        phone="+919000000002",
        full_name="Demo Farmer (Jalgaon)",
        role=Role.FARMER.value,
        profile={
            "display_name": "Demo Farmer (Jalgaon)",
            "village": "Sample Village 2",
            "district": "Jalgaon",
            "state": "Maharashtra",
            "latitude": 21.0077,
            "longitude": 75.5626,
            "primary_crops": ["cotton", "soybean"],
            "bio": DEMO_NOTE,
        },
    )
    expert = upsert_user(
        db,
        phone="+919000000003",
        full_name="Demo Agronomist (KVK)",
        role=Role.EXPERT.value,
        profile={
            "display_name": "Demo Agronomist (KVK)",
            "district": "Nashik",
            "state": "Maharashtra",
            "organisation": "Demo Krishi Vigyan Kendra (seeded)",
            "farming_experience_years": 15,
            "primary_crops": ["onion", "tomato"],
            "bio": DEMO_NOTE,
        },
        extra_roles=[Role.EXPERT.value],
    )
    moderator = upsert_user(
        db,
        phone="+919000000004",
        full_name="Demo Moderator",
        role=Role.MODERATOR.value,
        profile={
            "display_name": "Demo Moderator",
            "district": "Nashik",
            "state": "Maharashtra",
            "bio": DEMO_NOTE,
        },
    )
    admin = upsert_user(
        db,
        phone="+919000000005",
        full_name="Demo Administrator",
        role=Role.ADMIN.value,
        profile={
            "display_name": "Demo Administrator",
            "state": "Maharashtra",
            "bio": DEMO_NOTE,
        },
        extra_roles=[Role.MODERATOR.value],
    )
    counts["users"] = 5

    # -------------------------------------------------------------- consent
    # Consent is *recorded data*, never a default: the demo accounts are given
    # explicit decisions so the analytics pipeline has a legitimate reason to
    # exist for them, and the records themselves demonstrate the audit fields.
    consent_service = ConsentService(db)
    demo_consents = {
        farmer.id: {
            ConsentKind.ANALYTICS: True,
            ConsentKind.MODEL_TRAINING: False,
            ConsentKind.PERSONALISATION: True,
            ConsentKind.MARKETING: False,
        },
        farmer2.id: {
            ConsentKind.ANALYTICS: True,
            ConsentKind.PERSONALISATION: True,
        },
        expert.id: {ConsentKind.ANALYTICS: True, ConsentKind.RESEARCH: True},
        moderator.id: {ConsentKind.ANALYTICS: True},
        admin.id: {ConsentKind.ANALYTICS: True},
    }
    for user_id, decisions in demo_consents.items():
        for kind, granted in decisions.items():
            consent_service.record(
                user_id=user_id,
                kind=kind,
                granted=granted,
                source=ConsentSource.SEED,
                note="Seeded demo decision for local development.",
            )
    counts["consent_records"] = sum(len(d) for d in demo_consents.values())

    # Purposes the demo farmer was NOT asked about stay unanswered on purpose, so
    # the "no recorded decision counts as refused" path is exercised locally.

    # ------------------------------------------------------- crop catalog + farm
    # The crop catalog is *reference data*, not demo data: it is loaded by
    # scripts/load_reference_data.py (which is production-safe) and reused here so
    # a development database and a production database share the same catalogue.
    from load_reference_data import load as load_reference_data

    reference = load_reference_data(db)
    counts["crop_catalog_entries"] = reference["total"]

    farm = (
        db.query(Farm)
        .filter(Farm.name == "Demo Plot (Nashik)", Farm.owner_id == farmer.id)
        .one_or_none()
    )
    if farm is None:
        farm = Farm(
            owner_id=farmer.id,
            name="Demo Plot (Nashik)",
            area_value=1.2,
            area_unit="acre",
            village="Sample Village",
            taluka="Sample Taluka",
            district="Nashik",
            state="Maharashtra",
            pincode="422001",
            latitude=19.9975,
            longitude=73.7898,
            soil_type=SoilType.BLACK_COTTON,
            soil_ph=7.4,
            irrigation_type=IrrigationType.DRIP,
            ownership_type=OwnershipType.OWNED,
            notes=DEMO_NOTE,
            is_demo=True,
        )
        db.add(farm)
        db.flush()
        db.add(
            SoilTest(
                farm_id=farm.id,
                tested_on=date.today() - timedelta(days=45),
                ph=7.4,
                nitrogen_kg_per_ha=112,
                phosphorus_kg_per_ha=38,
                potassium_kg_per_ha=64,
                organic_carbon_percent=0.52,
                lab_name="Demo Soil Testing Laboratory (seeded)",
                notes="Sample values for development. Not a real soil test report.",
            )
        )
    crop = (
        db.query(Crop)
        .filter(Crop.farm_id == farm.id, Crop.crop_code == "onion")
        .one_or_none()
    )
    if crop is None:
        crop = Crop(
            farm_id=farm.id,
            crop_code="onion",
            variety="Bhima Super (example)",
            season=Season.RABI,
            sowing_date=date.today() - timedelta(days=35),
            area_value=1.2,
            area_unit="acre",
            stage=CropStage.VEGETATIVE,
            status=CropStatus.ACTIVE,
            irrigation_method=IrrigationType.DRIP,
            seed_source="Local dealer (seeded example)",
            notes=DEMO_NOTE,
            is_demo=True,
        )
        db.add(crop)
        db.flush()
        db.add(
            CropEvent(
                crop_id=crop.id,
                created_by_id=farmer.id,
                event_type="irrigation",
                event_date=date.today() - timedelta(days=4),
                notes="Drip irrigation 40 minutes (seeded example).",
            )
        )
    counts["farms"] = 1
    counts["crops"] = 1

    # ------------------------------------------------------------- community
    def post_if_missing(
        *,
        title: str,
        body: str,
        category: PostCategory,
        author,
        crop_code=None,
        sources=None,
        comments=None,
    ):  # noqa: ANN001
        existing = db.query(Post).filter(Post.title == title).one_or_none()
        if existing is not None:
            return existing
        text = body + (
            ("\n\n" + "\n".join(f"Reference: {url}" for url in sources))
            if sources
            else ""
        )
        assessment = assess(
            author_roles=author.role_names,
            category=category.value,
            source_urls=sources or [],
        )
        post = Post(
            author_id=author.id,
            title=title,
            body=text,
            category=category,
            crop_code=crop_code,
            language="en",
            state="Maharashtra",
            district="Nashik",
            trust_label=assessment.label,
            status=ContentStatus.PUBLISHED,
            is_demo=True,
        )
        db.add(post)
        db.flush()
        for comment_body, comment_author in comments or []:
            assessment_c = assess(
                author_roles=comment_author.role_names, category=None, source_urls=[]
            )
            db.add(
                Comment(
                    post_id=post.id,
                    author_id=comment_author.id,
                    body=comment_body,
                    trust_label=assessment_c.label,
                    is_demo=True,
                )
            )
            post.comment_count += 1
        return post

    # Kept as a named local: a later step attaches the expert reply to this post.
    q1 = post_if_missing(
        title="Onion leaves turning pale with white patches — what should I check first?",
        body=(
            "My onion crop (35 days after transplanting) has pale leaves and white patches. I irrigate by drip "
            "every third day. What should I check first before spraying anything? (Demo question for development.)"
        ),
        category=PostCategory.DISEASE,
        author=farmer,
        crop_code="onion",
        comments=[
            (
                "Check the underside of the leaves and the field edges first, and photograph the affected patch. "
                "Do not spray before identifying the problem — share photos with your local KVK or the expert "
                "queue here. (Demo reply.)",
                expert,
            ),
            (
                "I had similar patches last season in my plot and it helped to improve drainage and reduce "
                "evening irrigation. This is only my experience on my field, not verified advice. (Demo reply.)",
                farmer2,
            ),
        ],
    )
    post_if_missing(
        title="Official reference: how to read a soil health card (demo post)",
        body=(
            "This demo post shows how an official source appears in the community. The linked page is the "
            "Government of India soil health card portal. Read the nutrient status columns, then confirm crop "
            "and dose recommendations with your local agriculture officer. (Demo content — verify before use.)"
        ),
        category=PostCategory.GOVERNMENT_SCHEME,
        author=moderator,
        sources=["https://soilhealth.dac.gov.in/"],
    )
    post_if_missing(
        title="Demo success story: mulching reduced my irrigation trips",
        body=(
            "I mulched part of my plot with crop residue and irrigated less often in the same period. This is a "
            "single-plot observation, not a trial, and results will differ by soil. (Demo post.)"
        ),
        category=PostCategory.FARMING_TECHNIQUE,
        author=farmer2,
        crop_code="tomato",
    )
    db.flush()

    posts = db.query(Post).filter(Post.is_demo.is_(True)).all()
    if posts:
        first = posts[0]
        has_reaction = (
            db.query(Reaction)
            .filter(Reaction.user_id == farmer2.id, Reaction.post_id == first.id)
            .one_or_none()
        )
        if has_reaction is None:
            db.add(
                Reaction(
                    user_id=farmer2.id, post_id=first.id, kind=ReactionKind.HELPFUL
                )
            )
            first.reaction_count += 1
        has_save = (
            db.query(SavedPost)
            .filter(SavedPost.user_id == expert.id, SavedPost.post_id == first.id)
            .one_or_none()
        )
        if has_save is None:
            db.add(SavedPost(user_id=expert.id, post_id=first.id))
            first.save_count += 1
    # The demo farmer also saves the onion question, so the saved-posts screen and
    # the personalised feed have something real to show for a farmer account.
    has_q1_save = (
        db.query(SavedPost)
        .filter(SavedPost.user_id == farmer.id, SavedPost.post_id == q1.id)
        .one_or_none()
    )
    if has_q1_save is None:
        db.add(SavedPost(user_id=farmer.id, post_id=q1.id))
        q1.save_count += 1
    db.flush()
    counts["community_posts"] = len(posts)

    # ------------------------------------------------------------- knowledge
    platform_docs = [
        (
            "How Digital Village labels information (platform guide)",
            "This document explains the platform's own labels. Each post or answer carries a trust label: "
            "Farmer experience means a farmer shared their own observation; Community supported means other "
            "farmers or a linked source agree; Expert information means an account with the expert role wrote or "
            "reviewed it; Official information means platform staff cited a government or institutional source; "
            "AI prediction means a model produced the result. Popularity never changes a label: a post with many "
            "likes is still Farmer experience. Model results always show the model name and version, and are "
            "presented as AI-assisted, never as a confirmed diagnosis.",
            "platform_documentation",
            "article",
            [],
        ),
        (
            "How to use the AI crop recommendation result",
            "The crop recommendation feature ranks crops using soil and climate inputs. Scores are relative "
            "model scores unless the model card records a calibration step. The result never accounts for market "
            "demand, water availability, labour or rotation. Treat it as one input for planning and confirm the "
            "final choice with your local agriculture officer or Krishi Vigyan Kendra. If any input is outside "
            "the supported range the app asks you to correct it instead of silently clamping the value.",
            "platform_documentation",
            "faq",
            [],
        ),
        (
            "Demo placeholder: crop disease detection guidance",
            "DEMO PLACEHOLDER DOCUMENT. This text exists so the retrieval pipeline has content to return while "
            "the platform is under development. It intentionally contains no agronomic instructions, no "
            "pesticide names and no dosages. Replace it with a licensed, expert-reviewed document (for example "
            "from ICAR or your state agricultural university) before using this feature with real farmers. "
            "Photos submitted to disease detection are analysed by the installed model only if one is present; "
            "otherwise the app says that no model is installed rather than guessing a result.",
            "demo_placeholder",
            "disease_info",
            ["onion"],
        ),
    ]
    created_docs = 0
    for title, text, source_name, doc_type, crops in platform_docs:
        if (
            db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.title == title)
            .one_or_none()
        ):
            continue
        build_document_from_text(
            db,
            title=title,
            text=text,
            source_name=source_name,
            source_url=None,
            language="en",
            doc_type=doc_type,
            crop_codes=crops,
            state_codes=[],
            verification_status="community_reviewed"
            if source_name == "platform_documentation"
            else "unverified",
            is_demo=True,
        )
        created_docs += 1
    counts["knowledge_documents"] = created_docs or len(
        db.query(KnowledgeDocument).filter(KnowledgeDocument.is_demo.is_(True)).all()
    )

    # --------------------------------------------------------------- schemes
    # Content is deliberately generic: this demo record exists to exercise the
    # eligibility/reminder flows. Rules are data (SchemeEligibilityRule), so every
    # `field` must come from app.schemes.eligibility.SUPPORTED_FIELDS and every
    # `operator` from SUPPORTED_OPERATORS (the DB has a matching CHECK constraint).
    demo_schemes = [
        {
            "slug": "demo-pm-kisan",
            "name_en": "PM-KISAN income support (demo record)",
            "description_en": (
                f"{DEMO_NOTE} Income support for landholding farmer families, paid in instalments to "
                "bank accounts. This record is a development placeholder: the ceiling below is "
                "illustrative and must be replaced with the current official notification before "
                "production use."
            ),
            "benefits_en": "Income support paid in instalments (see the official portal for the current amount).",
            "eligibility_summary_en": "Landholding farmer families, subject to the exclusion criteria in the official scheme rules.",
            "application_process_en": "Apply through the official portal or your local agriculture office / CSC.",
            "documents_required": [
                "Land records",
                "Bank account details",
                "Identity proof",
            ],
            "category": "income_support",
            "level": "central",
            "state_codes": [],
            "crop_codes": [],
            "official_source_name": "PM-KISAN official portal",
            "official_source_url": "https://pmkisan.gov.in/",
            "application_url": "https://pmkisan.gov.in/",
            "helpline": "See the official portal for the current helpline number.",
            "rules": [
                {
                    "field": "land_holding_hectares",
                    "operator": "<=",
                    "value": {"threshold": 2.0},
                    "is_hard_requirement": True,
                    "note_en": "Illustrative ceiling used in the demo record only.",
                },
                {
                    "field": "has_kcc",
                    "operator": "is_true",
                    "value": {},
                    "is_hard_requirement": False,
                    "note_en": "Recorded Kisan Credit Card status only; not an official requirement of this demo record.",
                },
            ],
        },
        {
            "slug": "demo-drip-irrigation-subsidy",
            "name_en": "Micro-irrigation subsidy (demo record)",
            "description_en": (
                f"{DEMO_NOTE} Support for drip/sprinkler installation under a national micro-irrigation "
                "programme administered by the state. Percentages, ceilings and land-size limits differ "
                "by state and category — check the official state portal before applying."
            ),
            "benefits_en": "Subsidy on micro-irrigation system cost (state-specific percentage; check the official portal).",
            "eligibility_summary_en": "Farmers installing approved drip/sprinkler systems, subject to state rules.",
            "application_process_en": "Apply through the state agriculture department portal or the district office.",
            "documents_required": [
                "Land records",
                "Aadhaar",
                "Bank details",
                "Quotation from an empanelled supplier",
            ],
            "category": "irrigation",
            "level": "state",
            "state_codes": ["Maharashtra"],
            "crop_codes": [],
            "official_source_name": "State agriculture department (demo record — replace with the current portal)",
            "official_source_url": "https://krishi.maharashtra.gov.in/",
            "application_url": "https://krishi.maharashtra.gov.in/",
            "helpline": "See the official state portal.",
            "rules": [
                {
                    "field": "state",
                    "operator": "in",
                    "value": {"options": ["Maharashtra"]},
                    "is_hard_requirement": True,
                    "note_en": "Demo record is scoped to Maharashtra.",
                },
                {
                    "field": "irrigation_type",
                    "operator": "in",
                    "value": {
                        "options": ["rainfed", "canal", "flood", "tank", "other"]
                    },
                    "is_hard_requirement": False,
                    "note_en": "Programme targets plots without an existing micro-irrigation system.",
                },
            ],
        },
        {
            "slug": "demo-crop-insurance-window",
            "name_en": "Crop insurance enrolment window (demo record)",
            "description_en": (
                f"{DEMO_NOTE} Crop insurance is offered through the national crop insurance scheme with "
                "state-specific cut-off dates and premium shares. This demo record exercises the "
                "eligibility and reminder flows; no dates, amounts or deadlines are stored here."
            ),
            "benefits_en": "Insurance cover against notified perils (see the official scheme guidelines).",
            "eligibility_summary_en": "Farmers growing notified crops in notified areas, enrolled before the cut-off date.",
            "application_process_en": "Enrol through your bank, CSC or the official portal before the cut-off date.",
            "documents_required": [
                "Land records",
                "Sowing certificate or self-declaration as per rules",
                "Bank details",
            ],
            "category": "insurance",
            "level": "central",
            "state_codes": [],
            "crop_codes": ["onion", "tomato"],
            "official_source_name": "Pradhan Mantri Fasal Bima Yojana official portal",
            "official_source_url": "https://pmfby.gov.in/",
            "application_url": "https://pmfby.gov.in/",
            "helpline": "See the official portal for the current helpline number.",
            "rules": [
                {
                    "field": "crop_codes",
                    "operator": "contains",
                    "value": {
                        "options": ["onion", "tomato", "wheat", "soybean", "cotton"]
                    },
                    "is_hard_requirement": False,
                    "note_en": "The scheme applies to notified crops; the demo list is illustrative.",
                }
            ],
        },
    ]
    created_schemes = 0
    for payload in demo_schemes:
        if db.query(Scheme).filter(Scheme.slug == payload["slug"]).one_or_none():
            continue
        rules = payload.pop("rules")
        scheme = Scheme(
            **payload,
            verification_status=VerificationStatus.UNVERIFIED,
            last_verified_on=None,
            is_demo=True,
        )
        for rule in rules:
            scheme.eligibility_rules.append(
                SchemeEligibilityRule(
                    field=rule["field"],
                    operator=rule["operator"],
                    value=rule["value"],
                    is_hard_requirement=rule["is_hard_requirement"],
                    note_en=rule["note_en"],
                    source_reference=scheme.official_source_url,
                )
            )
        db.add(scheme)
        created_schemes += 1
    db.flush()
    counts["schemes"] = created_schemes or len(
        db.query(Scheme).filter(Scheme.is_demo.is_(True)).all()
    )

    db.commit()

    # --------------------------------------------------------------- weather
    # Weather rows are cached provider responses (the demo provider is
    # deterministic), stored so the offline/stale-fallback path has something
    # real to fall back to and so weather analytics is not empty. They are
    # *not* presented as measured data: the provider name travels with every row.
    try:
        from app.weather.service import WeatherService

        weather = WeatherService(db)
        current = weather.current(
            latitude=19.9975, longitude=73.7898
        )  # Nashik demo farm
        forecast = weather.forecast(latitude=19.9975, longitude=73.7898, days=7)
        alerts = weather.alerts(state="Maharashtra", district="Nashik")
        stored_alerts = weather.store_alerts(alerts.alerts)
        counts["weather_observations"] = 1
        counts["weather_forecast_days"] = len(forecast.days)
        counts["weather_alerts_cached"] = stored_alerts
        counts["weather_alerts_supported"] = alerts.supported
        counts["weather_provider"] = current.provider
        # The mock provider publishes no real warnings; say so in the seed output
        # rather than leaving an empty alert list that looks like "all clear".
        if not alerts.supported:
            logger.warning(
                "weather_alerts_not_supported",
                extra={
                    "extra_fields": {
                        "provider": alerts.provider,
                        "notice": alerts.notice,
                    }
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "weather_seed_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
        )
        counts["weather_observations"] = 0

    # --------------------------------------------------------------- markets
    try:
        from app.markets.service import MarketService

        service = MarketService(db)
        stored = 0
        today = date.today()
        for crop_code in ("onion", "tomato", "wheat"):
            result = service.prices(
                crop_code=crop_code,
                state="Maharashtra",
                from_date=today - timedelta(days=7),
                to_date=today,
            )
            stored += len(result.items)
        counts["market_price_rows"] = stored
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "market_seed_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
        )
        counts["market_price_rows"] = 0

    # ------------------------------------------------------- model registry
    try:
        from app.ai.registry import (
            MODEL_NAMES,
            ModelRegistryService,
            available_versions,
        )
        import json

        registered = 0
        for name in MODEL_NAMES.values():
            versions = available_versions(name)
            if not versions:
                continue
            version = versions[-1]
            directory = settings.models_path / name / version
            card = {}
            card_path = directory / "model_card.json"
            if card_path.exists():
                card = json.loads(card_path.read_text())
            ModelRegistryService(db).register(
                name=name,
                version=version,
                display_name=card.get("name", name.replace("-", " ").title()),
                task=card.get("task", "unknown"),
                framework=card.get("framework", "unknown"),
                mlflow_run_id=(card.get("mlflow") or {}).get("run_id"),
                artifact_uri=str(directory),
                metrics=card.get("metrics", {}),
                parameters=card.get("parameters", {}),
                training_data=card.get("dataset", {}),
                evaluation_report=card.get("metrics", {}),
                stage=__import__(
                    "app.core.enums", fromlist=["ModelStage"]
                ).ModelStage.PRODUCTION,
                notes="Registered by scripts/seed_demo.py from the artefact on disk (metrics copied verbatim).",
            )
            registered += 1
        counts["model_registry_entries"] = registered
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "model_registry_seed_failed",
            extra={"extra_fields": {"error": str(exc)[:200]}},
        )
        counts["model_registry_entries"] = 0

    # -------------------------------------------------- notifications (demo)
    try:
        from app.core.enums import NotificationType
        from app.notifications.service import NotificationService

        service = NotificationService(db)
        outcome = service.create(
            user_id=farmer.id,
            type=NotificationType.SYSTEM,
            title="Welcome to the Digital Village development build",
            body=(
                "This account and all seeded content are demo data. AI results are model outputs, not "
                "diagnoses; scheme records are placeholders. Read /moderation/policy for the community rules."
            ),
            deep_link="digitalvillage://home",
            payload={"seeded": True},
        )
        counts["notifications"] = 1 if outcome.get("created") else 0
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notification_seed_failed",
            extra={"extra_fields": {"error": str(exc)[:200]}},
        )
        counts["notifications"] = 0

    # ------------------------------------------------- embeddings (best effort)
    try:
        from app.workers.handlers import embedding_reindex

        summary = embedding_reindex(db, {"scope": "all", "limit": 50})
        counts["embedded"] = int((summary.get("posts") or {}).get("embedded", 0))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "embedding_seed_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
        )
        counts["embedded"] = 0

    counts["demo_accounts"] = 5
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the per-table counts; suppress the demo-account reminder block.",
    )
    args = parser.parse_args()

    configure_logging()
    guard()
    with session_scope() as db:
        counts = seed(db)

    print("\nDemo seed complete. Created/verified:")
    for key, value in counts.items():
        print(f"  {key:>22}: {value}")
    if args.quiet:
        return 0
    print(
        "\nDemo accounts (development only):\n"
        "  farmer     +919000000001\n"
        "  farmer     +919000000002\n"
        "  expert     +919000000003\n"
        "  moderator  +919000000004\n"
        "  admin      +919000000005\n"
        f"  password   {settings.demo_user_password}   (DEMO_USER_PASSWORD)\n"
        "\nAll seeded rows carry is_demo=True. Do not use this data as agricultural, market or scheme advice."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
