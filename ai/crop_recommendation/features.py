"""Feature contract for crop recommendation — shared by training and serving.

Both sides import this module, so a training/serving skew in feature order or
name is impossible by construction (the artefact also stores the list and the
service verifies it).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    unit: str
    minimum: float
    maximum: float
    description: str


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec("nitrogen", "kg/ha", 0, 200, "Available soil nitrogen (N)"),
    FeatureSpec("phosphorus", "kg/ha", 0, 200, "Available soil phosphorus (P)"),
    FeatureSpec("potassium", "kg/ha", 0, 250, "Available soil potassium (K)"),
    FeatureSpec(
        "temperature_c", "°C", -10, 55, "Mean temperature during the growing window"
    ),
    FeatureSpec("humidity_percent", "%", 0, 100, "Relative humidity"),
    FeatureSpec("ph", "pH", 0, 14, "Soil pH"),
    FeatureSpec("rainfall_mm", "mm", 0, 4000, "Rainfall over the growing window"),
)

FEATURE_NAMES: list[str] = [spec.name for spec in FEATURE_SPECS]
FEATURE_RANGES: dict[str, tuple[float, float]] = {
    s.name: (s.minimum, s.maximum) for s in FEATURE_SPECS
}

# Crops the shipped sample model is trained on. Each entry documents the usual
# agronomic envelope used to generate the sample data and to explain rankings.
# The envelopes are broad, textbook ranges used for *sample generation*; they are
# deliberately wide and must be replaced by real regional datasets for production.
SAMPLE_CROPS: dict[str, dict] = {
    "rice": {
        "name_en": "Rice (paddy)",
        "name_mr": "भात",
        "name_hi": "धान",
        "preferred": {
            "nitrogen": (60, 120),
            "phosphorus": (35, 70),
            "potassium": (35, 80),
            "temperature_c": (20, 35),
            "humidity_percent": (70, 95),
            "ph": (5.5, 7.0),
            "rainfall_mm": (150, 300),
        },
    },
    "wheat": {
        "name_en": "Wheat",
        "name_mr": "गहू",
        "name_hi": "गेहूं",
        "preferred": {
            "nitrogen": (80, 140),
            "phosphorus": (40, 70),
            "potassium": (30, 70),
            "temperature_c": (10, 25),
            "humidity_percent": (40, 70),
            "ph": (6.0, 7.5),
            "rainfall_mm": (40, 120),
        },
    },
    "maize": {
        "name_en": "Maize",
        "name_mr": "मका",
        "name_hi": "मक्का",
        "preferred": {
            "nitrogen": (70, 140),
            "phosphorus": (35, 70),
            "potassium": (35, 90),
            "temperature_c": (18, 32),
            "humidity_percent": (50, 80),
            "ph": (5.8, 7.2),
            "rainfall_mm": (60, 200),
        },
    },
    "cotton": {
        "name_en": "Cotton",
        "name_mr": "कापूस",
        "name_hi": "कपास",
        "preferred": {
            "nitrogen": (50, 110),
            "phosphorus": (25, 60),
            "potassium": (40, 90),
            "temperature_c": (21, 35),
            "humidity_percent": (40, 70),
            "ph": (6.0, 8.0),
            "rainfall_mm": (50, 150),
        },
    },
    "soybean": {
        "name_en": "Soybean",
        "name_mr": "सोयाबीन",
        "name_hi": "सोयाबीन",
        "preferred": {
            "nitrogen": (20, 60),
            "phosphorus": (30, 70),
            "potassium": (30, 80),
            "temperature_c": (20, 32),
            "humidity_percent": (55, 85),
            "ph": (6.0, 7.5),
            "rainfall_mm": (60, 180),
        },
    },
    "onion": {
        "name_en": "Onion",
        "name_mr": "कांदा",
        "name_hi": "प्याज",
        "preferred": {
            "nitrogen": (50, 110),
            "phosphorus": (30, 60),
            "potassium": (40, 100),
            "temperature_c": (15, 30),
            "humidity_percent": (50, 75),
            "ph": (6.0, 7.5),
            "rainfall_mm": (40, 130),
        },
    },
    "tomato": {
        "name_en": "Tomato",
        "name_mr": "टोमॅटो",
        "name_hi": "टमाटर",
        "preferred": {
            "nitrogen": (60, 130),
            "phosphorus": (40, 80),
            "potassium": (50, 120),
            "temperature_c": (18, 30),
            "humidity_percent": (55, 80),
            "ph": (6.0, 7.0),
            "rainfall_mm": (40, 120),
        },
    },
    "groundnut": {
        "name_en": "Groundnut",
        "name_mr": "भुईमूग",
        "name_hi": "मूंगफली",
        "preferred": {
            "nitrogen": (20, 50),
            "phosphorus": (30, 60),
            "potassium": (30, 70),
            "temperature_c": (22, 33),
            "humidity_percent": (50, 80),
            "ph": (6.0, 7.5),
            "rainfall_mm": (50, 150),
        },
    },
    "sugarcane": {
        "name_en": "Sugarcane",
        "name_mr": "ऊस",
        "name_hi": "गन्ना",
        "preferred": {
            "nitrogen": (100, 200),
            "phosphorus": (40, 80),
            "potassium": (60, 150),
            "temperature_c": (20, 35),
            "humidity_percent": (60, 90),
            "ph": (6.0, 8.0),
            "rainfall_mm": (100, 250),
        },
    },
    "chickpea": {
        "name_en": "Chickpea (gram)",
        "name_mr": "हरभरा",
        "name_hi": "चना",
        "preferred": {
            "nitrogen": (15, 45),
            "phosphorus": (30, 60),
            "potassium": (25, 60),
            "temperature_c": (15, 30),
            "humidity_percent": (35, 65),
            "ph": (6.0, 8.0),
            "rainfall_mm": (30, 100),
        },
    },
}
