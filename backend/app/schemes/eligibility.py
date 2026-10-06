"""Deterministic scheme eligibility evaluation.

Design rules (from the specification):
  * rules are *data* (`scheme_eligibility_rules`), never executable code — the
    evaluator resolves `field` against a fixed vocabulary and rejects unknown ones;
  * a rule may be a hard requirement (failing it disqualifies) or soft (failing it
    lowers suitability only);
  * when a required input is unknown the outcome is `unknown`, never `eligible`:
    the API never claims eligibility from incomplete information;
  * every evaluation returns rule-by-rule reasoning plus the scheme's official
    source, so a farmer can verify the result themselves.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.units import to_hectares

# Fields a rule may reference, with the farmer-side input each maps to.
SUPPORTED_FIELDS: dict[str, str] = {
    "land_holding_hectares": "farm area converted to hectares (sum of the farmer's farms)",
    "age_years": "farmer age (not collected by default; unknown unless supplied)",
    "state": "farm/farmer state name",
    "district": "farm/farmer district name",
    "crop_codes": "crops grown (catalog codes)",
    "irrigation_type": "irrigation method recorded on the farm",
    "soil_type": "soil type recorded on the farm",
    "has_kcc": "whether the farmer reports holding a Kisan Credit Card",
    "is_tenant_farmer": "ownership type 'leased'/'shared'",
    "annual_income_inr": "self-reported annual income",
    "is_small_marginal": "derived: land holding ≤ 2 hectares",
    "category_caste": "self-reported social category (optional; only when a scheme explicitly requires it)",
}

SUPPORTED_OPERATORS = {
    "<=",
    "<",
    ">=",
    ">",
    "==",
    "!=",
    "in",
    "not_in",
    "contains",
    "is_true",
    "is_false",
}

# Operators that read naturally as "lower is better" for the field below; used to
# explain a failure in plain language.
FIELD_LABELS = {
    "land_holding_hectares": "land holding (hectares)",
    "age_years": "age (years)",
    "state": "state",
    "district": "district",
    "crop_codes": "crops grown",
    "irrigation_type": "irrigation type",
    "soil_type": "soil type",
    "has_kcc": "Kisan Credit Card held",
    "is_tenant_farmer": "tenant farmer",
    "annual_income_inr": "annual income (INR)",
    "is_small_marginal": "small/marginal farmer",
}


@dataclass(slots=True)
class RuleOutcome:
    field: str
    operator: str
    required_value: Any
    actual_value: Any
    status: str  # passed | failed | unknown | not_applicable
    is_hard_requirement: bool
    explanation: str
    source_reference: str | None = None


@dataclass(slots=True)
class EligibilityResult:
    scheme_slug: str
    scheme_name: str
    status: str  # likely_eligible | likely_not_eligible | needs_more_information
    confidence: str  # qualitative: high | medium | low
    passed: list[RuleOutcome] = field(default_factory=list)
    failed: list[RuleOutcome] = field(default_factory=list)
    unknown: list[RuleOutcome] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    configuration_warnings: list[str] = field(default_factory=list)
    explanation: str = ""
    official_source_name: str = ""
    official_source_url: str = ""
    last_verified_on: date | None = None
    verification_status: str = "unverified"
    disclaimer: str = (
        "This is a rule-based screening against information recorded in your profile, not a government "
        "decision. Final eligibility is decided by the implementing agency — always confirm at the official "
        "source before applying."
    )


# How the comparison value is read out of `scheme_eligibility_rules.value`.
# The column is JSONB and three spellings exist in real rows (the seed fixture,
# hand-written SQL and older imports), so the contract is declared here once and
# used by every evaluation path:
#
#   {"value": 2.0}          {"threshold": 2.0}      2.0        # scalars
#   {"options": ["on"]}     {"values": ["on"]}      ["on"]     # set membership
#
# `is_true` / `is_false` need no comparison value at all.
_SCALAR_KEYS = ("value", "threshold", "max", "min", "limit")
_SET_KEYS = ("options", "values", "value", "threshold", "allowed", "crops", "states")
BOOLEAN_OPERATORS = frozenset({"is_true", "is_false"})
SET_OPERATORS = frozenset({"in", "not_in", "contains"})
NUMERIC_OPERATORS = frozenset({"<", "<=", ">", ">="})


def rule_expectation(value: Any, operator: str) -> tuple[Any, str | None]:
    """Return ``(expected, error)`` for one rule row.

    ``error`` is set — and ``expected`` is None — when the stored rule value does
    not supply what the operator needs. That case must never be reported as a
    failed requirement: an unreadable rule is a data problem, not a fact about
    the farmer.
    """
    if operator in BOOLEAN_OPERATORS:
        return None, None
    if not isinstance(value, dict):
        if value in (None, "", {}):
            return None, f"the rule for operator '{operator}' has no comparison value"
        return value, None
    keys = _SET_KEYS if operator in SET_OPERATORS else _SCALAR_KEYS
    for key in keys:
        if key in value and value[key] is not None:
            return value[key], None
    if operator in SET_OPERATORS and isinstance(value.get("value"), list):
        return value["value"], None
    present = ", ".join(sorted(value)) or "none"
    return None, (
        f"the rule for operator '{operator}' has no usable value "
        f"(expected one of: {', '.join(keys)}; found: {present})"
    )


def _compare(operator: str, actual: Any, expected: Any) -> bool | None:
    """Returns True/False, or None when comparison is not possible."""
    if actual is None:
        return None
    try:
        if operator == "<=":
            return float(actual) <= float(expected)
        if operator == "<":
            return float(actual) < float(expected)
        if operator == ">=":
            return float(actual) >= float(expected)
        if operator == ">":
            return float(actual) > float(expected)
        if operator == "==":
            return str(actual).strip().lower() == str(expected).strip().lower()
        if operator == "!=":
            return str(actual).strip().lower() != str(expected).strip().lower()
        if operator == "in":
            options = expected if isinstance(expected, list | tuple | set) else [expected]
            return str(actual).strip().lower() in {str(o).strip().lower() for o in options}
        if operator == "not_in":
            options = expected if isinstance(expected, list | tuple | set) else [expected]
            return str(actual).strip().lower() not in {str(o).strip().lower() for o in options}
        if operator == "contains":
            options = expected if isinstance(expected, list | tuple | set) else [expected]
            actuals = actual if isinstance(actual, list | tuple | set) else [actual]
            normalized = {str(a).strip().lower() for a in actuals}
            return any(str(o).strip().lower() in normalized for o in options)
        if operator == "is_true":
            return bool(actual) is True
        if operator == "is_false":
            return bool(actual) is False
    except (TypeError, ValueError):
        return None
    return None


def _explain(field_name: str, operator: str, expected: Any, actual: Any, status: str) -> str:
    label = FIELD_LABELS.get(field_name, field_name)
    if status == "unknown":
        return f"Could not check {label}: the needed information is not recorded yet."
    if status == "passed":
        return f"{label} satisfies the requirement ({operator} {expected!r}); recorded: {actual!r}."
    phrases = {
        "<=": f"must be at most {expected!r}",
        "<": f"must be less than {expected!r}",
        ">=": f"must be at least {expected!r}",
        ">": f"must be more than {expected!r}",
        "==": f"must equal {expected!r}",
        "!=": f"must not be {expected!r}",
        "in": f"must be one of {expected!r}",
        "not_in": f"must not be one of {expected!r}",
        "contains": f"must include one of {expected!r}",
        "is_true": "must be true",
        "is_false": "must be false",
    }
    return f"{label} {phrases.get(operator, operator)}; recorded: {actual!r}."


@dataclass(slots=True)
class FarmerContext:
    """Everything the evaluator is allowed to know. Missing values stay None and
    therefore produce `unknown`, never a guess."""

    land_holding_hectares: float | None = None
    state: str | None = None
    district: str | None = None
    crop_codes: list[str] = field(default_factory=list)
    irrigation_types: list[str] = field(default_factory=list)
    soil_types: list[str] = field(default_factory=list)
    is_tenant_farmer: bool | None = None
    age_years: int | None = None
    has_kcc: bool | None = None
    annual_income_inr: float | None = None
    category_caste: str | None = None

    @property
    def is_small_marginal(self) -> bool | None:
        if self.land_holding_hectares is None:
            return None
        return self.land_holding_hectares <= 2.0

    def value_for(self, field_name: str) -> Any:
        if field_name == "is_small_marginal":
            return self.is_small_marginal
        if not hasattr(self, field_name):
            return None
        value = getattr(self, field_name)
        if isinstance(value, list):
            return value or None
        return value


def build_context(
    *, farms: list[Any], profile: Any | None, extra: dict[str, Any] | None = None
) -> FarmerContext:
    """Build the evaluation context from stored farm/profile data only."""
    total_ha = 0.0
    states, districts, crops, irrigation, soils = set(), set(), set(), set(), set()
    has_any_area = False
    for farm in farms:
        if getattr(farm, "deleted_at", None) is not None:
            continue
        try:
            total_ha += to_hectares(float(farm.area_value), farm.area_unit)
            has_any_area = True
        except (TypeError, ValueError):
            pass
        if farm.state:
            states.add(farm.state)
        if farm.district:
            districts.add(farm.district)
        if getattr(farm, "irrigation_type", None) is not None:
            irrigation.add(
                farm.irrigation_type.value
                if hasattr(farm.irrigation_type, "value")
                else str(farm.irrigation_type)
            )
        if getattr(farm, "soil_type", None) is not None:
            soils.add(
                farm.soil_type.value if hasattr(farm.soil_type, "value") else str(farm.soil_type)
            )
        if farm.ownership_type is not None and farm.ownership_type.value in ("leased", "shared"):
            pass
        for crop in getattr(farm, "crops", []) or []:
            if getattr(crop, "deleted_at", None) is None and crop.crop_code:
                crops.add(crop.crop_code)

    context = FarmerContext(
        land_holding_hectares=round(total_ha, 4) if has_any_area else None,
        state=next(iter(states)) if len(states) == 1 else None,
        district=next(iter(districts)) if len(districts) == 1 else None,
        crop_codes=sorted(crops),
        irrigation_types=sorted(irrigation),
        soil_types=sorted(soils),
    )
    if profile is not None:
        if not context.state and profile.state:
            context.state = profile.state
        if not context.district and profile.district:
            context.district = profile.district
        if (
            profile.farming_experience_years
            and profile.total_land_area
            and context.land_holding_hectares is None
        ):
            with contextlib.suppress(TypeError, ValueError):
                context.land_holding_hectares = to_hectares(
                    float(profile.total_land_area), profile.total_land_unit or "acre"
                )
    for key, value in (extra or {}).items():
        if key in SUPPORTED_FIELDS and value is not None:
            setattr(context, key, value)
    return context


def evaluate(scheme: Any, context: FarmerContext) -> EligibilityResult:
    outcomes: list[RuleOutcome] = []
    unknown_fields: list[str] = []
    configuration_warnings: list[str] = []
    for rule in scheme.eligibility_rules:
        expected, rule_error = rule_expectation(rule.value, rule.operator)
        if rule_error is not None:
            # Reported as unknown (never as "failed"), and flagged separately from
            # missing farmer information so the two are not confused in the UI.
            message = f"{scheme.slug}: rule on '{rule.field}' cannot be evaluated — {rule_error}."
            configuration_warnings.append(message)
            outcomes.append(
                RuleOutcome(
                    field=rule.field,
                    operator=rule.operator,
                    required_value=None,
                    actual_value=context.value_for(rule.field),
                    status="unknown",
                    is_hard_requirement=rule.is_hard_requirement,
                    explanation=(
                        "This requirement cannot be checked because the scheme's rule data is "
                        "incomplete; check the official source before applying."
                    ),
                    source_reference=rule.source_reference,
                )
            )
            if rule.is_hard_requirement:
                # Still blocks a positive verdict: we cannot claim eligibility.
                pass
            continue
        if rule.field not in SUPPORTED_FIELDS:
            # A rule we cannot evaluate is reported as unknown rather than skipped,
            # so an unevaluated requirement never silently becomes a "pass".
            outcomes.append(
                RuleOutcome(
                    field=rule.field,
                    operator=rule.operator,
                    required_value=expected,
                    actual_value=None,
                    status="unknown",
                    is_hard_requirement=rule.is_hard_requirement,
                    explanation=(
                        f"Rule for '{rule.field}' cannot be evaluated by this version of Digital Village; "
                        "please check the official scheme guidelines."
                    ),
                    source_reference=rule.source_reference,
                )
            )
            unknown_fields.append(rule.field)
            continue
        actual = context.value_for(rule.field)
        result = _compare(rule.operator, actual, expected)
        status = "unknown" if result is None else ("passed" if result else "failed")
        outcomes.append(
            RuleOutcome(
                field=rule.field,
                operator=rule.operator,
                required_value=expected,
                actual_value=actual,
                status=status,
                is_hard_requirement=rule.is_hard_requirement,
                explanation=_explain(rule.field, rule.operator, expected, actual, status),
                source_reference=rule.source_reference,
            )
        )
        if status == "unknown" and rule.is_hard_requirement:
            unknown_fields.append(rule.field)

    if configuration_warnings and status == "likely_eligible":
        status = "needs_more_information"
        confidence = "low"
        explanation = (
            "Some requirements could not be checked because the scheme's rule data is incomplete, "
            "so eligibility cannot be confirmed: " + "; ".join(configuration_warnings[:3])
        )

    hard_failed = [o for o in outcomes if o.status == "failed" and o.is_hard_requirement]
    hard_unknown = [o for o in outcomes if o.status == "unknown" and o.is_hard_requirement]
    soft_failed = [o for o in outcomes if o.status == "failed" and not o.is_hard_requirement]

    if hard_failed:
        status = "likely_not_eligible"
        confidence = "medium"
        explanation = (
            "Based on the information recorded, at least one required condition does not appear to be met: "
            + "; ".join(o.explanation for o in hard_failed[:3])
        )
    elif hard_unknown:
        status = "needs_more_information"
        confidence = "low"
        explanation = (
            "Required information is missing, so eligibility cannot be determined: "
            + "; ".join(o.explanation for o in hard_unknown[:3])
        )
    else:
        status = "likely_eligible"
        confidence = "high" if not soft_failed else "medium"
        explanation = "All recorded hard requirements appear to be met."
        if soft_failed:
            explanation += (
                " Some preference conditions are not met, which may affect priority: "
                + "; ".join(o.explanation for o in soft_failed[:3])
            )

    return EligibilityResult(
        scheme_slug=scheme.slug,
        scheme_name=scheme.name_en,
        status=status,
        confidence=confidence,
        passed=[o for o in outcomes if o.status == "passed"],
        failed=[o for o in outcomes if o.status == "failed"],
        unknown=[o for o in outcomes if o.status == "unknown"],
        missing_inputs=sorted(set(unknown_fields)),
        configuration_warnings=sorted(set(configuration_warnings)),
        explanation=explanation,
        official_source_name=scheme.official_source_name,
        official_source_url=scheme.official_source_url,
        last_verified_on=scheme.last_verified_on,
        verification_status=scheme.verification_status.value
        if hasattr(scheme.verification_status, "value")
        else str(scheme.verification_status),
    )
