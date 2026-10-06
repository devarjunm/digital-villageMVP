"""Unit conversion helpers.

Only exact, definitional conversions live here (an acre *is* 0.40468564224 ha).
Non-definitional agronomic quantities (e.g. expected yield) are never estimated
by this module — model output is the only source for those.
"""

from __future__ import annotations

from app.core.enums import AreaUnit

# Exact conversion factors to hectares.
AREA_TO_HECTARE: dict[str, float] = {
    AreaUnit.ACRE.value: 0.40468564224,
    AreaUnit.HECTARE.value: 1.0,
    AreaUnit.GUNTHA.value: 0.01011714106,  # 1 guntha = 1/40 acre
    AreaUnit.BIGHa.value: 0.2529285264,  # state-variable in reality; documented assumption
    AreaUnit.SQUARE_METRE.value: 0.0001,
}

# Units whose value differs by state are labelled so callers can warn users.
STATE_VARIABLE_UNITS = {AreaUnit.BIGHa.value}
AREA_UNIT_NOTES = {
    AreaUnit.BIGHa.value: (
        "Bigha is not a standard unit: its size varies by state. Digital Village "
        "uses 1 bigha = 0.25293 ha as a documented approximation and recommends "
        "entering area in acres or hectares for accurate calculations."
    )
}


def to_hectares(value: float, unit: AreaUnit | str) -> float:
    key = unit.value if isinstance(unit, AreaUnit) else str(unit)
    if key not in AREA_TO_HECTARE:
        raise ValueError(f"Unsupported area unit: {unit}")
    return float(value) * AREA_TO_HECTARE[key]


def from_hectares(value_ha: float, unit: AreaUnit | str) -> float:
    key = unit.value if isinstance(unit, AreaUnit) else str(unit)
    if key not in AREA_TO_HECTARE:
        raise ValueError(f"Unsupported area unit: {unit}")
    return float(value_ha) / AREA_TO_HECTARE[key]


def area_unit_note(unit: AreaUnit | str) -> str | None:
    key = unit.value if isinstance(unit, AreaUnit) else str(unit)
    return AREA_UNIT_NOTES.get(key)


def crop_age_days(sowing_date, on=None) -> int | None:
    """Days since sowing — a factual calculation from farmer-entered data."""
    if sowing_date is None:
        return None
    from datetime import date

    return ((on or date.today()) - sowing_date).days
