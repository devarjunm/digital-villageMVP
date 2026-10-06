#!/usr/bin/env python3
"""Load the platform's reference data (safe to run in production).

Reference data is the minimum set of rows the application needs to function:
the crop catalog that crops, community filters, the AI features and market codes
all reference. It contains no farmer data, no prices, no advisories and no demo
content, and every row is idempotent by natural key, so running it against an
existing database only fills in what is missing.

This is deliberately a *separate* script from `scripts/seed_demo.py`:

    load_reference_data.py   → production-safe, factual, no `is_demo` rows
    seed_demo.py             → development only, everything `is_demo=True`

Run order in deployment (see docs/deployment.md):
    alembic upgrade head && python scripts/load_reference_data.py

The catalog rows below are naming/coverage decisions, not agronomic claims:
`disease_model_labels` lists the class labels the disease model can emit for that
crop and is used to refuse scans outside the trained label set. Production values
must be regenerated from the trained model's own label map — the values here
match the labels of the sample dataset shipped in `data/datasets/`.

Usage:
    python scripts/load_reference_data.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(REPO_ROOT / "backend"), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import app.models  # noqa: E402,F401  (registers every mapped class)
from app.core.config import settings  # noqa: E402
from app.core.enums import CropStage, Season  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.crops.models import CropCatalog  # noqa: E402
from app.database.session import session_scope  # noqa: E402

logger = get_logger("reference_data")

#: `code`, English name, Marathi name, Hindi name, category, season, model labels.
#: The model labels are the *class names* the disease model was trained with; a
#: scan for a crop whose labels are empty is refused with an explanation instead
#: of returning a guess.
CROPS: tuple[tuple[str, str, str, str, str, Season, tuple[str, ...]], ...] = (
    (
        "onion",
        "Onion",
        "कांदा",
        "प्याज़",
        "vegetable",
        Season.RABI,
        ("onion_purple_blotch", "onion_downy_mildew"),
    ),
    (
        "tomato",
        "Tomato",
        "टोमॅटो",
        "टमाटर",
        "vegetable",
        Season.KHARIF,
        ("tomato_early_blight", "tomato_late_blight"),
    ),
    ("wheat", "Wheat", "गहू", "गेहूँ", "cereal", Season.RABI, ("wheat_rust",)),
    (
        "soybean",
        "Soybean",
        "सोयाबीन",
        "सोयाबीन",
        "oilseed",
        Season.KHARIF,
        ("soybean_rust",),
    ),
    ("cotton", "Cotton", "कापूस", "कपास", "fibre", Season.KHARIF, ("cotton_bollworm",)),
    ("rice", "Rice (paddy)", "भात", "धान", "cereal", Season.KHARIF, ()),
    ("maize", "Maize", "मका", "मक्का", "cereal", Season.KHARIF, ()),
    ("groundnut", "Groundnut", "भुईमूग", "मूंगफली", "oilseed", Season.KHARIF, ()),
    ("sugarcane", "Sugarcane", "ऊस", "गन्ना", "cash_crop", Season.PERENNIAL, ()),
    ("grape", "Grape", "द्राक्ष", "अंगूर", "fruit", Season.PERENNIAL, ()),
)

#: A reasonable default growth-stage track, used only when a crop row has no
#: crop-specific sequence; the app shows it as the standard sequence, not as
#: advice about a particular field.
DEFAULT_STAGES: tuple[str, ...] = (
    CropStage.PLANNED.value,
    CropStage.LAND_PREPARATION.value,
    CropStage.SOWING.value,
    CropStage.GERMINATION.value,
    CropStage.VEGETATIVE.value,
    CropStage.FLOWERING.value,
    CropStage.FRUITING.value,
    CropStage.MATURITY.value,
    CropStage.HARVEST.value,
    CropStage.POST_HARVEST.value,
)


def load(db, *, dry_run: bool = False) -> dict[str, int]:  # noqa: ANN001
    created = updated = 0
    for code, name_en, name_mr, name_hi, category, season, labels in CROPS:
        existing = db.query(CropCatalog).filter(CropCatalog.code == code).one_or_none()
        if existing is None:
            if not dry_run:
                db.add(
                    CropCatalog(
                        code=code,
                        name_en=name_en,
                        name_mr=name_mr,
                        name_hi=name_hi,
                        category=category,
                        season=season,
                        disease_model_labels=list(labels),
                        is_demo=False,
                    )
                )
            created += 1
            continue
        # Backfill translations / labels added by a later release without touching
        # anything an operator may have edited (only empty fields are filled).
        changed = False
        if not existing.name_hi and name_hi:
            existing.name_hi = name_hi
            changed = True
        if not existing.name_mr and name_mr:
            existing.name_mr = name_mr
            changed = True
        if not existing.disease_model_labels and labels:
            existing.disease_model_labels = list(labels)
            changed = True
        if changed:
            updated += 1
    if not dry_run:
        db.commit()
    return {"created": created, "updated": updated, "total": len(CROPS)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change, write nothing.",
    )
    args = parser.parse_args()

    configure_logging()
    with session_scope() as db:
        result = load(db, dry_run=args.dry_run)

    print(
        f"Reference data {'(dry run) ' if args.dry_run else ''}"
        f"crop catalog: {result['created']} created, {result['updated']} completed, "
        f"{result['total']} defined."
    )
    print(
        "Disease model labels are catalogue metadata, not a claim that a model exists: "
        f"models are loaded from {settings.models_path}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
