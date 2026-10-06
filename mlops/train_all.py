#!/usr/bin/env python
"""Train every model that has a training entrypoint, and say out loud what it skipped.

Why a wrapper instead of one script per model: the release process needs a single
command that produces artefacts for the whole platform, and it must be impossible
for that command to *pretend* to have trained something. So this script discovers
trainable components by looking for `ai/<component>/train.py`, runs each one, then
validates the artefacts it produced with `mlops/validate_artifacts.py`.

    python mlops/train_all.py                     # every trainable component
    python mlops/train_all.py --only crop_recommendation
    python mlops/train_all.py --register          # also register in the app database
    python mlops/train_all.py --dry-run           # print the plan, train nothing

Components without a training entrypoint are reported as **skipped with the
reason** and make the exit code non-zero unless `--allow-skips` is passed: a
release that silently ships only one of the four AI capabilities is exactly the
kind of surprise this script exists to prevent.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = REPO_ROOT / "ai"

# Components the platform serves from `app/ai/`. Kept explicit (rather than "any
# directory under ai/") so a new capability is a deliberate addition here too.
EXPECTED_COMPONENTS = (
    "crop_recommendation",
    "disease_detection",
    "yield_prediction",
    "price_prediction",
)

# Components whose serving path is a documented deterministic baseline rather than a
# learned model. They are not "missing a trainer" — they are designed this way.
BASELINE_COMPONENTS = {
    "yield_prediction": "served by a documented deterministic baseline (see app/ai/service.py); no learned model required",
    "price_prediction": "served by a documented deterministic baseline plus the market provider; no learned model required",
}


@dataclass
class Outcome:
    component: str
    status: str  # trained | skipped | failed
    detail: str


def trainable() -> dict[str, Path]:
    return {
        component: AI_ROOT / component / "train.py"
        for component in EXPECTED_COMPONENTS
        if (AI_ROOT / component / "train.py").exists()
    }


def plan(only: list[str]) -> tuple[dict[str, Path], list[Outcome]]:
    available = trainable()
    skipped: list[Outcome] = []
    selected: dict[str, Path] = {}
    for component in EXPECTED_COMPONENTS:
        if only and component not in only:
            continue
        script = available.get(component)
        if script is not None:
            selected[component] = script
            continue
        reason = BASELINE_COMPONENTS.get(component) or (
            f"no training entrypoint at ai/{component}/train.py — the model cannot be trained by this script"
        )
        skipped.append(Outcome(component, "skipped", reason))
    for component in only:
        if component not in EXPECTED_COMPONENTS:
            skipped.append(
                Outcome(
                    component,
                    "skipped",
                    "unknown component (not one of EXPECTED_COMPONENTS)",
                )
            )
    return selected, skipped


def run_training(
    component: str, script: Path, *, register: bool, extra: list[str], quiet: bool
) -> Outcome:
    command = [sys.executable, str(script)]
    if register:
        command.append("--register")
    command.extend(extra)
    print(f"\n==> {component}: {' '.join(command)}")
    env = {**os.environ, "PYTHONPATH": f"{REPO_ROOT}:{REPO_ROOT / 'backend'}"}
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True)
    if completed.returncode != 0:
        return Outcome(
            component, "failed", f"training exited with {completed.returncode}"
        )
    return Outcome(
        component, "trained", f"artefact written via {script.relative_to(REPO_ROOT)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="train just this component (repeatable)",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="register trained versions in the app database",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan and exit"
    )
    parser.add_argument(
        "--allow-skips",
        action="store_true",
        help="exit 0 even when components were skipped",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        help="extra argument forwarded to the training script (repeatable), e.g. --extra=--seed=7",
    )
    parser.add_argument("--quiet", action="store_true", help="less output")
    args = parser.parse_args(argv)

    if not AI_ROOT.exists():
        print(f"No ai/ package at {AI_ROOT}; nothing to train.")
        return 1

    selected, skipped = plan(args.only)

    print("Training plan")
    for component, script in selected.items():
        print(f"  [train ] {component}  ({script.relative_to(REPO_ROOT)})")
    for outcome in skipped:
        print(f"  [skip  ] {outcome.component}  {outcome.detail}")

    if args.dry_run:
        print("\nDry run: nothing was trained.")
        return 0

    outcomes: list[Outcome] = list(skipped)
    for component, script in selected.items():
        outcomes.append(
            run_training(
                component,
                script,
                register=args.register,
                extra=args.extra,
                quiet=args.quiet,
            )
        )

    print("\nValidation of the artefacts now on disk:")
    validator = REPO_ROOT / "mlops" / "validate_artifacts.py"
    validation = subprocess.run([sys.executable, str(validator)], cwd=REPO_ROOT)
    validation_ok = validation.returncode == 0

    print("\nSummary")
    for outcome in outcomes:
        print(f"  {outcome.status:<8} {outcome.component}: {outcome.detail}")

    failed = [o for o in outcomes if o.status == "failed"]
    still_skipped = [o for o in outcomes if o.status == "skipped"]
    if failed:
        print("\nTraining failed for: " + ", ".join(o.component for o in failed))
        return 1
    if not validation_ok:
        print(
            "\nAn artefact failed validation — do not deploy it (see the report above)."
        )
        return 1
    if still_skipped and not args.allow_skips:
        print(
            "\nSome components were not trained. If that is intended (they have no learned model by "
            "design), re-run with --allow-skips so the release is recorded as a deliberate decision."
        )
        return 1
    print("\nDone. Artefacts validated; nothing was deployed by this script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
