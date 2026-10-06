#!/usr/bin/env python3
"""Import every application module and report the ones that fail.

Why this exists: a broken import in one router is invisible until that route is
hit, and `pytest` never touches modules it does not import. This script walks the
whole package (`app`, `ai`, `genai`) and imports every module in a fresh
interpreter-tree, collecting failures instead of stopping at the first one, so a
refactor that renames a class is caught in one run.

It imports the modules — it does not call any endpoint and does not need a
database. A live database is only required for modules that connect at import
time (none should).

Usage:
    python scripts/check_imports.py            # human-readable summary
    python scripts/check_imports.py --json     # machine-readable (CI)
Exit code is 1 when at least one module fails to import.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Package roots to walk. `backend` carries the API, `ai`/`genai` the model and
#: LLM layers; the workspace root is on sys.path so all three resolve.
PACKAGES = ("app", "ai", "genai")

#: Modules that are allowed to be import-time heavy or environment specific.
SKIP_PREFIXES = ("app.__pycache__",)


def _iter_modules(package: str):
    module = importlib.import_module(package)
    if not hasattr(module, "__path__"):
        yield package
        return
    yield package
    for info in pkgutil.walk_packages(module.__path__, prefix=f"{package}."):
        if info.name.startswith(SKIP_PREFIXES):
            continue
        yield info.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of text."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print every module as it is imported.",
    )
    args = parser.parse_args()

    for path in (str(REPO_ROOT / "backend"), str(REPO_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)

    failures: list[dict[str, str]] = []
    tested = 0
    for package in PACKAGES:
        try:
            names = list(_iter_modules(package))
        except Exception as exc:  # noqa: BLE001 - the package root itself is broken
            failures.append(
                {
                    "module": package,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
            continue
        for name in names:
            tested += 1
            try:
                importlib.import_module(name)
                if args.verbose:
                    print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001 - we want every failure, not the first
                failures.append(
                    {
                        "module": name,
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    }
                )

    if args.json:
        print(json.dumps({"tested": tested, "failures": failures}, indent=2))
    else:
        for failure in failures:
            print(f"FAIL {failure['module']}\n     {failure['error']}")
        print(f"tested {tested} modules, {len(failures)} failures")
        if failures and not args.verbose:
            print("Re-run with --json for full tracebacks.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
