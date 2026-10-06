#!/usr/bin/env python
"""Model health and usage report, read straight from the application database.

Answers the questions an operator actually asks about a deployed model:

  * is an artefact installed for each capability, and which version is being served?
  * how many inferences ran, how many failed, and how slow are they?
  * has the input distribution moved away from what the model was trained on?

    python mlops/monitor_models.py                     # 7-day window
    python mlops/monitor_models.py --days 30
    python mlops/monitor_models.py --json              # machine-readable, for a cron/cronjob

Nothing here is estimated. If the events table is empty the report says "no
inferences recorded", which is itself the finding: either nothing has been used, or
instrumentation is broken. Drift is reported as *distance from the recorded training
envelope*, not as a verdict, and no accuracy figure is claimed from production data
(there are no ground-truth labels in production, so any such number would be fiction).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_WINDOW_DAYS = 7


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def collect(days: int) -> dict:
    import sqlalchemy as sa

    from app.ai.models import ModelInferenceEvent, ModelRegistryEntry
    from app.ai.registry import available_versions, pinned_version
    from app.database.session import session_scope

    since = datetime.now(UTC) - timedelta(days=days)
    report: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": days,
        "since": since.isoformat(),
        "capabilities": {},
        "inference": {},
        "registry": {},
        "notes": [],
    }

    with session_scope() as db:
        # ---- what is installed / pinned (the serving-side truth) -------------
        for model_dir in sorted(
            p for p in (REPO_ROOT / "artifacts" / "models").glob("*") if p.is_dir()
        ):
            name = model_dir.name
            report["capabilities"][name] = {
                "installed_versions": available_versions(name),
                "pinned_version": pinned_version(name),
            }

        # ---- registry rows (what training recorded) --------------------------
        rows = db.execute(
            sa.select(
                ModelRegistryEntry.name,
                ModelRegistryEntry.version,
                ModelRegistryEntry.stage,
            )
        ).all()
        report["registry"] = {
            "entries": len(rows),
            "by_stage": dict(Counter(str(stage) for _, _, stage in rows)),
        }
        if not rows:
            report["notes"].append(
                "No registry entries: register a trained version (`ai/*/train.py --register`) so the "
                "serving path and the training record agree."
            )

        # ---- inference events ------------------------------------------------
        events = db.execute(
            sa.select(
                ModelInferenceEvent.model_name,
                ModelInferenceEvent.model_version,
                ModelInferenceEvent.outcome,
                ModelInferenceEvent.latency_ms,
                ModelInferenceEvent.error_code,
                ModelInferenceEvent.input_features,
                ModelInferenceEvent.created_at,
            ).where(ModelInferenceEvent.created_at >= since)
        ).all()

        if not events:
            report["notes"].append(
                f"No model inferences recorded in the last {days} day(s). Either the AI features have "
                "not been used, or inference events are not being written."
            )
            return report

        per_model: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "by_outcome": Counter(), "latencies": []}
        )
        errors: Counter = Counter()
        versions_in_use: dict[str, Counter] = defaultdict(Counter)
        feature_samples: dict[str, list[dict]] = defaultdict(list)

        for name, version, outcome, latency, error_code, features, _created in events:
            entry = per_model[name]
            entry["total"] += 1
            entry["by_outcome"][str(outcome)] += 1
            if latency is not None:
                entry["latencies"].append(float(latency))
            if error_code:
                errors[f"{name}:{error_code}"] += 1
            versions_in_use[name][str(version)] += 1
            if isinstance(features, dict) and len(feature_samples[name]) < 500:
                feature_samples[name].append(features)

        for name, entry in per_model.items():
            latencies = entry.pop("latencies")
            entry["by_outcome"] = dict(entry["by_outcome"])
            entry["latency_ms"] = {
                "p50": _percentile(latencies, 0.5),
                "p95": _percentile(latencies, 0.95),
                "max": max(latencies) if latencies else None,
            }
            entry["versions_in_use"] = dict(versions_in_use[name])
            entry["error_breakdown"] = {
                key.split(":", 1)[1]: count
                for key, count in errors.items()
                if key.startswith(f"{name}:")
            }

        report["inference"] = per_model
        report["drift"] = _drift_summary(feature_samples)
    return report


def _drift_summary(samples: dict[str, list[dict]]) -> dict:
    """Compare recent input distributions with the documented training envelope.

    The envelope is read from the artefact's own `feature_names.json`
    (`crops.<crop>.preferred`), which is the same source the API uses to refuse
    out-of-range inputs — so a "drift" here means real inputs are arriving outside
    what the model was built for.
    """
    import json as _json

    feature_ranges: dict[str, dict] = {}
    models_dir = REPO_ROOT / "artifacts" / "models"
    for feature_file in models_dir.glob("*/v*/feature_names.json"):
        try:
            payload = _json.loads(feature_file.read_text())
        except (OSError, _json.JSONDecodeError):
            continue
        ranges: dict[str, tuple[float, float]] = {}
        for crop in (payload.get("crops") or {}).values():
            for feature, bounds in (crop.get("preferred") or {}).items():
                if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
                    low, high = float(bounds[0]), float(bounds[1])
                    existing = ranges.get(feature)
                    ranges[feature] = (
                        min(low, existing[0]) if existing else low,
                        max(high, existing[1]) if existing else high,
                    )
        feature_ranges[feature_file.parent.parent.name] = {"features": ranges}

    out: dict[str, dict] = {}
    for model_name, rows in samples.items():
        envelope = feature_ranges.get(model_name, {}).get("features") or {}
        if not envelope or not rows:
            continue
        outside: Counter = Counter()
        checked = Counter()
        for row in rows:
            for feature, bounds in envelope.items():
                value = row.get(feature)
                if value is None:
                    continue
                checked[feature] += 1
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if numeric < bounds[0] or numeric > bounds[1]:
                    outside[feature] += 1
        out[model_name] = {
            feature: {
                "outside_envelope": outside[feature],
                "checked": checked[feature],
                "share_outside": round(outside[feature] / checked[feature], 3)
                if checked[feature]
                else None,
                "documented_range": list(envelope[feature]),
            }
            for feature in envelope
            if checked[feature]
        }
    return out


def render(report: dict) -> None:
    print(
        f"Model report — window: last {report['window_days']} day(s) (since {report['since']})\n"
    )

    print("Capabilities (serving side)")
    if not report["capabilities"]:
        print("  no artefact directories found under artifacts/models")
    for name, info in report["capabilities"].items():
        installed = ", ".join(info["installed_versions"]) or "none installed"
        pinned = info["pinned_version"] or "not pinned (newest installed is used)"
        print(f"  {name:<22} installed: {installed}")
        print(f"  {' ' * 22} pinned:    {pinned}")

    registry = report.get("registry", {})
    print(
        f"\nRegistry: {registry.get('entries', 0)} entr(ies) {registry.get('by_stage', {})}"
    )

    print("\nInference (last window)")
    if not report["inference"]:
        print("  none recorded")
    for name, entry in report["inference"].items():
        latency = entry["latency_ms"]
        print(f"  {name:<22} total: {entry['total']}  outcomes: {entry['by_outcome']}")
        print(
            f"  {' ' * 22} latency p50/p95/max: "
            f"{latency['p50']}/{latency['p95']}/{latency['max']} ms"
        )
        if entry.get("error_breakdown"):
            print(f"  {' ' * 22} errors: {entry['error_breakdown']}")
        print(f"  {' ' * 22} versions in use: {entry['versions_in_use']}")

    drift = report.get("drift") or {}
    print("\nInput drift vs the artefact's documented envelope")
    if not drift:
        print(
            "  not computed (no stored input features, or no envelope in the artefact)"
        )
    for name, features in drift.items():
        for feature, stats in features.items():
            share = stats["share_outside"]
            flag = "  <-- review" if (share or 0) >= 0.2 else ""
            print(
                f"  {name} {feature}: {stats['outside_envelope']}/{stats['checked']} outside "
                f"documented range {stats['documented_range']}{flag}"
            )

    for note in report.get("notes", []):
        print(f"\nNOTE: {note}")
    print(
        "\nNo accuracy figure is reported from production traffic: ground-truth labels do not exist for "
        "served requests, so any such number would be fabricated. Offline metrics live in each model card."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_WINDOW_DAYS, help="look-back window in days"
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON instead of a report"
    )
    args = parser.parse_args(argv)

    if not os.environ.get("DATABASE_URL"):
        print(
            "DATABASE_URL is not set. Example:\n"
            "  DATABASE_URL='postgresql+psycopg://dv:dv_password@localhost:5432/digital_village' "
            "python mlops/monitor_models.py",
        )
        return 2

    report = collect(args.days)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        render(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
